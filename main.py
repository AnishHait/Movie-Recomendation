"""
CINEVAULT / Movie Recommendation API
-------------------------------------
FastAPI backend for:
- TMDB movie discovery/search/details
- Local TF-IDF recommendations
- Genre-based TMDB recommendations
- Combined recommendation bundles
- Health/diagnostic endpoints

Authentication:
1. Preferred: TMDB_API_READ_ACCESS_TOKEN in .env
2. Fallback: TMDB_API_KEY in .env

The backend automatically uses Bearer authentication when the read-access
token exists, otherwise it uses the v3 api_key query parameter.
"""

from __future__ import annotations

import asyncio
import os
import pickle
import time
from contextlib import asynccontextmanager
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# =============================================================================
# 1. ENVIRONMENT & CONSTANTS
# =============================================================================

load_dotenv()

TMDB_BASE = os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3").rstrip("/")
TMDB_IMAGE_BASE = os.getenv(
    "TMDB_IMAGE_BASE_URL",
    "https://image.tmdb.org/t/p/w500",
).rstrip("/")

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_READ_ACCESS_TOKEN = os.getenv("TMDB_API_READ_ACCESS_TOKEN", "").strip()

REQUEST_TIMEOUT = float(os.getenv("TMDB_TIMEOUT", "20"))
RETRY_COUNT = int(os.getenv("TMDB_RETRY_COUNT", "2"))
CACHE_TTL = int(os.getenv("TMDB_CACHE_TTL", "300"))

ALLOWED_ORIGINS_RAW = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
ALLOWED_ORIGINS = (
    ["*"]
    if ALLOWED_ORIGINS_RAW == "*"
    else [x.strip() for x in ALLOWED_ORIGINS_RAW.split(",") if x.strip()]
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DF_PATH = os.path.join(BASE_DIR, "df.pkl")
INDICES_PATH = os.path.join(BASE_DIR, "indices.pkl")
TFIDF_MATRIX_PATH = os.path.join(BASE_DIR, "tfidf_matrix.pkl")
TFIDF_PATH = os.path.join(BASE_DIR, "tfidf.pkl")


def _auth_mode() -> str:
    if TMDB_READ_ACCESS_TOKEN:
        return "read_access_token"
    if TMDB_API_KEY:
        return "api_key"
    return "missing"


if _auth_mode() == "missing":
    raise RuntimeError(
        "TMDB credentials missing. Put TMDB_API_READ_ACCESS_TOKEN=... "
        "or TMDB_API_KEY=... in your .env file."
    )


# =============================================================================
# 2. APPLICATION STATE
# =============================================================================

df: Optional[pd.DataFrame] = None
indices_obj: Any = None
tfidf_matrix: Any = None
tfidf_obj: Any = None
TITLE_TO_IDX: Dict[str, int] = {}

_http_client: Optional[httpx.AsyncClient] = None

# Small in-memory TTL cache. This is intentionally simple and process-local.
_CACHE: Dict[str, Tuple[float, Any]] = {}


# =============================================================================
# 3. PYDANTIC RESPONSE MODELS
# =============================================================================

class TMDBMovieCard(BaseModel):
    tmdb_id: int
    title: str
    poster_url: Optional[str] = None
    release_date: Optional[str] = None
    vote_average: Optional[float] = None
    popularity: Optional[float] = None
    overview: Optional[str] = None


class TMDBMovieDetails(BaseModel):
    tmdb_id: int
    title: str
    original_title: Optional[str] = None
    overview: Optional[str] = None
    release_date: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
    popularity: Optional[float] = None
    runtime: Optional[int] = None
    status: Optional[str] = None
    tagline: Optional[str] = None
    genres: List[Dict[str, Any]] = Field(default_factory=list)
    production_companies: List[Dict[str, Any]] = Field(default_factory=list)
    spoken_languages: List[Dict[str, Any]] = Field(default_factory=list)


class TFIDFRecItem(BaseModel):
    title: str
    score: float
    tmdb: Optional[TMDBMovieCard] = None


class SearchBundleResponse(BaseModel):
    query: str
    movie_details: TMDBMovieDetails
    tfidf_recommendations: List[TFIDFRecItem] = Field(default_factory=list)
    genre_recommendations: List[TMDBMovieCard] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    tmdb_auth: str
    dataset_loaded: bool
    tfidf_loaded: bool
    dataset_rows: int
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


# =============================================================================
# 4. BASIC HELPERS
# =============================================================================

def _norm_title(title: str) -> str:
    """Normalize a title for reliable local-dataset matching."""
    return " ".join(str(title).strip().lower().split())


def _clean_query(query: str) -> str:
    return " ".join(str(query).strip().split())


def make_img_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    """Convert a TMDB relative image path into a full image URL."""
    if not path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


def _cache_get(key: str) -> Any:
    item = _CACHE.get(key)
    if item is None:
        return None

    created_at, value = item
    if time.monotonic() - created_at > CACHE_TTL:
        _CACHE.pop(key, None)
        return None

    return value


def _cache_set(key: str, value: Any) -> None:
    # Keep the process-local cache bounded.
    if len(_CACHE) >= 300:
        oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest_key, None)

    _CACHE[key] = (time.monotonic(), value)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# =============================================================================
# 5. FASTAPI LIFECYCLE
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Create one reusable HTTP client and load ML resources once.
    """
    global _http_client

    load_local_resources()

    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
        ),
        follow_redirects=True,
        headers={"Accept": "application/json"},
    )

    try:
        yield
    finally:
        if _http_client is not None:
            await _http_client.aclose()
        _http_client = None


app = FastAPI(
    lifespan=lifespan,
    title="CineVault Movie Recommendation API",
    description=(
        "A production-style movie recommendation backend combining "
        "TMDB discovery with local TF-IDF recommendations."
    ),
    version="4.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# =============================================================================
# 6. CORS
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# 7. LOCAL ML RESOURCE LOADING
# =============================================================================

def build_title_to_idx_map(indices: Any) -> Dict[str, int]:
    """
    Convert dict / pandas Series-like indices.pkl into:
        normalized_title -> integer_row_index
    """
    title_to_idx: Dict[str, int] = {}

    if isinstance(indices, dict):
        items = indices.items()
    else:
        try:
            items = indices.items()
        except AttributeError as exc:
            raise RuntimeError(
                "indices.pkl must be a dict or pandas Series-like object "
                "with .items()."
            ) from exc

    for title, idx in items:
        try:
            title_to_idx[_norm_title(title)] = int(idx)
        except (TypeError, ValueError):
            continue

    if not title_to_idx:
        raise RuntimeError("indices.pkl did not contain any usable title/index pairs.")

    return title_to_idx


def load_local_resources() -> None:
    """
    Load all recommendation artifacts and validate the important pieces.
    """
    global df, indices_obj, tfidf_matrix, tfidf_obj, TITLE_TO_IDX

    required_files = {
        "df.pkl": DF_PATH,
        "indices.pkl": INDICES_PATH,
        "tfidf_matrix.pkl": TFIDF_MATRIX_PATH,
        "tfidf.pkl": TFIDF_PATH,
    }

    missing = [name for name, path in required_files.items() if not os.path.exists(path)]
    if missing:
        raise RuntimeError(
            "Missing recommendation files: "
            + ", ".join(missing)
            + ". Put them in the same folder as main.py."
        )

    with open(DF_PATH, "rb") as file:
        df = pickle.load(file)

    with open(INDICES_PATH, "rb") as file:
        indices_obj = pickle.load(file)

    with open(TFIDF_MATRIX_PATH, "rb") as file:
        tfidf_matrix = pickle.load(file)

    with open(TFIDF_PATH, "rb") as file:
        tfidf_obj = pickle.load(file)

    if not isinstance(df, pd.DataFrame):
        raise RuntimeError("df.pkl must contain a pandas DataFrame.")

    if "title" not in df.columns:
        raise RuntimeError("df.pkl must contain a 'title' column.")

    TITLE_TO_IDX = build_title_to_idx_map(indices_obj)

    # Validate that the largest mapped index is inside the dataset.
    max_idx = max(TITLE_TO_IDX.values())
    if max_idx >= len(df):
        raise RuntimeError(
            f"indices.pkl contains index {max_idx}, but df.pkl has only "
            f"{len(df)} rows."
        )


# =============================================================================
# 8. TMDB HTTP LAYER
# =============================================================================

def _tmdb_request_config() -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Build TMDB authentication without ever logging the secret.

    Read Access Token:
        Authorization: Bearer <token>

    API Key:
        ?api_key=<key>
    """
    params: Dict[str, Any] = {}
    headers: Dict[str, str] = {}

    if TMDB_READ_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {TMDB_READ_ACCESS_TOKEN}"
    elif TMDB_API_KEY:
        params["api_key"] = TMDB_API_KEY
    else:
        raise RuntimeError("TMDB credentials are not configured.")

    return params, headers


async def tmdb_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Reliable TMDB GET:
    - reusable HTTP connection
    - small TTL cache
    - retry for transient failures
    - useful HTTP errors
    - no credential leakage in error messages
    """
    if _http_client is None:
        raise HTTPException(
            status_code=503,
            detail="TMDB client is not initialized yet.",
        )

    clean_params = dict(params or {})
    auth_params, auth_headers = _tmdb_request_config()

    # Cache only GET responses. Auth credentials are intentionally not part
    # of the cache key because they are process configuration, not request data.
    cache_key = f"{path}|{sorted(clean_params.items())}"

    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    request_params = {**clean_params, **auth_params}
    url = f"{TMDB_BASE}{path}"

    last_error: Optional[Exception] = None

    for attempt in range(RETRY_COUNT + 1):
        try:
            response = await _http_client.get(
                url,
                params=request_params,
                headers=auth_headers,
            )

            if response.status_code == 200:
                data = response.json()
                if use_cache:
                    _cache_set(cache_key, data)
                return data

            # Retry rate limits and server-side errors.
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < RETRY_COUNT:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 5.0) if retry_after else 0.6 * (attempt + 1)
                    except ValueError:
                        delay = 0.6 * (attempt + 1)

                    await asyncio.sleep(delay)
                    continue

            # Never include API key/token in the error.
            detail = response.text[:1000]

            if response.status_code in {401, 403}:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"TMDB authentication failed ({response.status_code}). "
                        "Check TMDB_API_READ_ACCESS_TOKEN or TMDB_API_KEY in .env."
                    ),
                )

            if response.status_code == 429:
                raise HTTPException(
                    status_code=429,
                    detail="TMDB rate limit reached. Please try again shortly.",
                )

            raise HTTPException(
                status_code=502,
                detail=f"TMDB returned HTTP {response.status_code}: {detail}",
            )

        except HTTPException:
            raise
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt < RETRY_COUNT:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
        except httpx.RequestError as exc:
            last_error = exc
            if attempt < RETRY_COUNT:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="TMDB returned an invalid JSON response.",
            ) from exc

    error_name = type(last_error).__name__ if last_error else "UnknownError"
    raise HTTPException(
        status_code=502,
        detail=f"Could not reach TMDB after retries ({error_name}).",
    )


# =============================================================================
# 9. TMDB DATA TRANSFORMERS
# =============================================================================

def tmdb_result_to_card(movie: Dict[str, Any]) -> TMDBMovieCard:
    return TMDBMovieCard(
        tmdb_id=_safe_int(movie.get("id")) or 0,
        title=movie.get("title") or movie.get("name") or "Unknown title",
        poster_url=make_img_url(movie.get("poster_path"), "w500"),
        release_date=movie.get("release_date") or movie.get("first_air_date"),
        vote_average=_safe_float(movie.get("vote_average")),
        popularity=_safe_float(movie.get("popularity")),
        overview=movie.get("overview"),
    )


def tmdb_cards_from_results(
    results: Optional[List[dict]],
    limit: int = 20,
) -> List[TMDBMovieCard]:
    cards: List[TMDBMovieCard] = []

    for movie in (results or [])[:limit]:
        try:
            card = tmdb_result_to_card(movie)
            if card.tmdb_id > 0 and card.title:
                cards.append(card)
        except Exception:
            continue

    return cards


async def tmdb_movie_details(movie_id: int) -> TMDBMovieDetails:
    if movie_id <= 0:
        raise HTTPException(status_code=400, detail="tmdb_id must be positive.")

    data = await tmdb_get(
        f"/movie/{movie_id}",
        {"language": "en-US"},
    )

    return TMDBMovieDetails(
        tmdb_id=int(data["id"]),
        title=data.get("title") or "",
        original_title=data.get("original_title"),
        overview=data.get("overview"),
        release_date=data.get("release_date"),
        poster_url=make_img_url(data.get("poster_path"), "w500"),
        backdrop_url=make_img_url(data.get("backdrop_path"), "original"),
        vote_average=_safe_float(data.get("vote_average")),
        vote_count=_safe_int(data.get("vote_count")),
        popularity=_safe_float(data.get("popularity")),
        runtime=_safe_int(data.get("runtime")),
        status=data.get("status"),
        tagline=data.get("tagline"),
        genres=data.get("genres") or [],
        production_companies=data.get("production_companies") or [],
        spoken_languages=data.get("spoken_languages") or [],
    )


async def tmdb_search_movies(
    query: str,
    page: int = 1,
) -> Dict[str, Any]:
    query = _clean_query(query)

    if not query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")

    return await tmdb_get(
        "/search/movie",
        {
            "query": query,
            "include_adult": "false",
            "language": "en-US",
            "page": page,
        },
    )


async def tmdb_search_first(query: str) -> Optional[dict]:
    data = await tmdb_search_movies(query=query, page=1)
    results = data.get("results") or []
    return results[0] if results else None


# =============================================================================
# 10. LOCAL TF-IDF RECOMMENDER
# =============================================================================

def get_local_idx_by_title(title: str) -> int:
    key = _norm_title(title)

    if not key:
        raise HTTPException(status_code=400, detail="Title cannot be empty.")

    if key in TITLE_TO_IDX:
        idx = int(TITLE_TO_IDX[key])
        if 0 <= idx < len(df):
            return idx

    # Friendly fallback for small spelling/title differences.
    matches = get_close_matches(
        key,
        TITLE_TO_IDX.keys(),
        n=1,
        cutoff=0.88,
    )

    if matches:
        idx = int(TITLE_TO_IDX[matches[0]])
        if 0 <= idx < len(df):
            return idx

    raise HTTPException(
        status_code=404,
        detail=f"Title not found in local dataset: '{title}'",
    )


def _matrix_row_to_dense(row: Any) -> np.ndarray:
    """
    Convert a sparse/dense matrix row into a flat numpy array.
    """
    if hasattr(row, "toarray"):
        row = row.toarray()

    array = np.asarray(row)

    if array.ndim == 2:
        array = array[0]

    return array.reshape(-1)


def _cosine_scores(query_vector: Any, matrix: Any) -> np.ndarray:
    """
    Calculate cosine similarity safely for both sparse and dense artifacts.
    The original project stores a TF-IDF matrix, so this also handles the
    common normalized-TFIDF case efficiently.
    """
    if hasattr(matrix, "__matmul__"):
        try:
            raw = matrix @ query_vector.T
            if hasattr(raw, "toarray"):
                raw = raw.toarray()
            scores = np.asarray(raw).reshape(-1)
        except Exception:
            scores = np.asarray(matrix) @ np.asarray(query_vector).reshape(-1)
    else:
        scores = np.asarray(matrix) @ np.asarray(query_vector).reshape(-1)

    # If vectors were not pre-normalized, normalize here.
    try:
        q = _matrix_row_to_dense(query_vector)
        matrix_dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
        norms = np.linalg.norm(matrix_dense, axis=1)
        q_norm = np.linalg.norm(q)

        if q_norm > 0:
            scores = scores / (norms * q_norm + 1e-12)
    except Exception:
        # For already normalized sparse TF-IDF matrices the matrix product
        # is already cosine similarity, so the fallback score is valid.
        pass

    return np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)


def tfidf_recommend_titles(
    query_title: str,
    top_n: int = 10,
) -> List[Tuple[str, float]]:
    """
    Return [(title, similarity_score), ...] from the local dataset.
    """
    if df is None or tfidf_matrix is None:
        raise HTTPException(
            status_code=503,
            detail="TF-IDF resources are not loaded.",
        )

    idx = get_local_idx_by_title(query_title)

    try:
        query_vector = tfidf_matrix[idx]
        scores = _cosine_scores(query_vector, tfidf_matrix)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not calculate TF-IDF similarity: {type(exc).__name__}",
        ) from exc

    order = np.argsort(-scores)

    recommendations: List[Tuple[str, float]] = []

    for row_idx in order:
        row_idx = int(row_idx)

        if row_idx == idx:
            continue

        try:
            title = str(df.iloc[row_idx]["title"]).strip()
        except Exception:
            continue

        if not title:
            continue

        recommendations.append(
            (
                title,
                round(float(scores[row_idx]), 6),
            )
        )

        if len(recommendations) >= top_n:
            break

    return recommendations


# =============================================================================
# 11. TMDB POSTER ENRICHMENT
# =============================================================================

async def attach_tmdb_card_by_title(
    title: str,
) -> Optional[TMDBMovieCard]:
    """
    Resolve a local recommendation title to a TMDB card.
    Failure is isolated so one missing movie never breaks the whole response.
    """
    try:
        movie = await tmdb_search_first(title)

        if not movie:
            return None

        return tmdb_result_to_card(movie)

    except Exception:
        return None


async def enrich_tfidf_recommendations(
    recommendations: List[Tuple[str, float]],
) -> List[TFIDFRecItem]:
    """
    Fetch recommendation posters concurrently.
    """
    if not recommendations:
        return []

    tasks = [
        attach_tmdb_card_by_title(title)
        for title, _score in recommendations
    ]

    cards = await asyncio.gather(*tasks, return_exceptions=True)

    output: List[TFIDFRecItem] = []

    for (title, score), card in zip(recommendations, cards):
        if isinstance(card, Exception):
            card = None

        output.append(
            TFIDFRecItem(
                title=title,
                score=score,
                tmdb=card,
            )
        )

    return output


# =============================================================================
# 12. RECOMMENDATION HELPERS
# =============================================================================

async def genre_recommendations_for_movie(
    tmdb_id: int,
    limit: int = 18,
) -> List[TMDBMovieCard]:
    details = await tmdb_movie_details(tmdb_id)

    if not details.genres:
        return []

    # Use the primary genre for predictable and fast recommendations.
    genre_id = details.genres[0].get("id")

    if not genre_id:
        return []

    discover = await tmdb_get(
        "/discover/movie",
        {
            "with_genres": int(genre_id),
            "language": "en-US",
            "sort_by": "popularity.desc",
            "include_adult": "false",
            "include_video": "false",
            "page": 1,
        },
    )

    cards = tmdb_cards_from_results(
        discover.get("results"),
        limit=min(limit + 5, 50),
    )

    return [
        card
        for card in cards
        if card.tmdb_id != tmdb_id
    ][:limit]


# =============================================================================
# 13. ROUTES
# =============================================================================

@app.get(
    "/",
    tags=["System"],
    summary="API welcome",
)
async def root() -> Dict[str, Any]:
    return {
        "name": "CineVault Movie Recommendation API",
        "version": app.version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Check backend health",
)
def health() -> HealthResponse:
    dataset_rows = len(df) if isinstance(df, pd.DataFrame) else 0

    return HealthResponse(
        status="ok",
        tmdb_auth=_auth_mode(),
        dataset_loaded=isinstance(df, pd.DataFrame),
        tfidf_loaded=tfidf_matrix is not None,
        dataset_rows=dataset_rows,
        message="CineVault backend is ready.",
    )


@app.get(
    "/config/status",
    tags=["System"],
    summary="Show safe configuration status",
)
def config_status() -> Dict[str, Any]:
    """
    Safe diagnostics. Never returns the API key or token.
    """
    return {
        "tmdb_base": TMDB_BASE,
        "tmdb_auth": _auth_mode(),
        "read_access_token_configured": bool(TMDB_READ_ACCESS_TOKEN),
        "api_key_configured": bool(TMDB_API_KEY),
        "dataset_loaded": df is not None,
        "tfidf_loaded": tfidf_matrix is not None,
        "dataset_rows": len(df) if isinstance(df, pd.DataFrame) else 0,
    }


@app.get(
    "/home",
    response_model=List[TMDBMovieCard],
    tags=["Discovery"],
    summary="Get a movie home feed",
)
async def home(
    category: str = Query(
        "popular",
        description="trending, popular, top_rated, upcoming, now_playing",
    ),
    limit: int = Query(24, ge=1, le=50),
) -> List[TMDBMovieCard]:
    category = category.strip().lower()

    if category == "trending":
        data = await tmdb_get(
            "/trending/movie/day",
            {"language": "en-US"},
        )
    elif category in {
        "popular",
        "top_rated",
        "upcoming",
        "now_playing",
    }:
        data = await tmdb_get(
            f"/movie/{category}",
            {
                "language": "en-US",
                "page": 1,
            },
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid category. Use: trending, popular, top_rated, "
                "upcoming, now_playing."
            ),
        )

    return tmdb_cards_from_results(
        data.get("results"),
        limit=limit,
    )


@app.get(
    "/tmdb/search",
    tags=["Discovery"],
    summary="Search movies directly on TMDB",
)
async def tmdb_search(
    query: str = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1, le=10),
) -> Dict[str, Any]:
    return await tmdb_search_movies(
        query=query,
        page=page,
    )


@app.get(
    "/movie/id/{tmdb_id}",
    response_model=TMDBMovieDetails,
    tags=["Movies"],
    summary="Get complete movie details",
)
async def movie_details_route(
    tmdb_id: int,
) -> TMDBMovieDetails:
    return await tmdb_movie_details(tmdb_id)


@app.get(
    "/recommend/genre",
    response_model=List[TMDBMovieCard],
    tags=["Recommendations"],
    summary="Recommend movies from the primary genre",
)
async def recommend_genre(
    tmdb_id: int = Query(..., gt=0),
    limit: int = Query(18, ge=1, le=50),
) -> List[TMDBMovieCard]:
    return await genre_recommendations_for_movie(
        tmdb_id=tmdb_id,
        limit=limit,
    )


@app.get(
    "/recommend/tfidf",
    tags=["Recommendations"],
    summary="Get local TF-IDF recommendations",
)
async def recommend_tfidf(
    title: str = Query(..., min_length=1, max_length=200),
    top_n: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Any]]:
    recommendations = tfidf_recommend_titles(
        title=title,
        top_n=top_n,
    )

    return [
        {
            "title": movie_title,
            "score": score,
        }
        for movie_title, score in recommendations
    ]


@app.get(
    "/movie/search",
    response_model=SearchBundleResponse,
    tags=["Recommendations"],
    summary="Get details + TF-IDF + genre recommendations",
)
async def search_bundle(
    query: str = Query(..., min_length=1, max_length=100),
    tfidf_top_n: int = Query(12, ge=1, le=30),
    genre_limit: int = Query(12, ge=1, le=30),
) -> SearchBundleResponse:
    """
    Full recommendation pipeline.

    Flow:
        user query
          -> TMDB best match
          -> movie details
          -> local TF-IDF recommendations
          -> TMDB poster enrichment
          -> genre recommendations
    """
    query = _clean_query(query)

    best = await tmdb_search_first(query)

    if not best:
        raise HTTPException(
            status_code=404,
            detail=f"No TMDB movie found for query: {query}",
        )

    tmdb_id = _safe_int(best.get("id"))
    if not tmdb_id:
        raise HTTPException(
            status_code=502,
            detail="TMDB returned a movie without a valid ID.",
        )

    details = await tmdb_movie_details(tmdb_id)

    # TF-IDF is intentionally isolated from the TMDB pipeline.
    # If a movie is absent from the local dataset, the rest still works.
    recommendations: List[Tuple[str, float]] = []

    try:
        recommendations = tfidf_recommend_titles(
            details.title,
            top_n=tfidf_top_n,
        )
    except HTTPException:
        try:
            recommendations = tfidf_recommend_titles(
                query,
                top_n=tfidf_top_n,
            )
        except HTTPException:
            recommendations = []

    tfidf_items = await enrich_tfidf_recommendations(
        recommendations
    )

    genre_recs: List[TMDBMovieCard] = []

    try:
        genre_recs = await genre_recommendations_for_movie(
            tmdb_id=tmdb_id,
            limit=genre_limit,
        )
    except HTTPException:
        # Keep the bundle useful even if the secondary recommendation call
        # fails independently.
        genre_recs = []

    return SearchBundleResponse(
        query=query,
        movie_details=details,
        tfidf_recommendations=tfidf_items,
        genre_recommendations=genre_recs,
    )


# =============================================================================
# 14. OPTIONAL CACHE CONTROL
# =============================================================================

@app.delete(
    "/cache",
    tags=["System"],
    summary="Clear the in-memory TMDB cache",
)
def clear_cache() -> Dict[str, Any]:
    count = len(_CACHE)
    _CACHE.clear()

    return {
        "status": "cleared",
        "removed_entries": count,
    }


# =============================================================================
# 15. REQUEST ERROR HANDLING
# =============================================================================

@app.middleware("http")
async def add_process_headers(request: Request, call_next):
    """
    Adds lightweight diagnostic headers without exposing secrets.
    """
    started = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-API-Version"] = app.version
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.2f}"

    return response


# =============================================================================
# 16. LOCAL DEVELOPMENT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
