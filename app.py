import streamlit as st
import requests
from typing import Any, Dict, List, Optional
from html import escape
from urllib.parse import quote
import time

# ============================================================
# CINEVAULT
# Professional Netflix-inspired Streamlit frontend
#
# Backend:
#   FastAPI -> http://127.0.0.1:8000
#
# Run:
#   python -m uvicorn main:app --reload
#   python -m streamlit run app.py
# ============================================================

st.set_page_config(
    page_title="CineVault",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

API_BASE = "http://127.0.0.1:8000"
POSTER_FALLBACK = "https://via.placeholder.com/500x750/151515/777?text=No+Poster"

# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "selected_movie": None,
    "selected_title": "",
    "page": "home",
    "search_query": "",
    "search_results": [],
    "watchlist": [],
    "toast": "",
    "toast_time": 0.0,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ============================================================
# GLOBAL CSS
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --bg: #070707;
    --surface: #101010;
    --surface-2: #151515;
    --surface-3: #1b1b1b;
    --border: #292929;
    --border-soft: #202020;
    --text: #f4f4f4;
    --muted: #909090;
    --muted-2: #686868;
    --accent: #e7e7e7;
}

html, body, [class*="css"] {
    font-family: "Inter", sans-serif;
}

.stApp {
    background: #070707;
    color: var(--text);
}

[data-testid="stHeader"] {
    background: rgba(7, 7, 7, 0.96);
}

.block-container {
    max-width: 1480px;
    padding-top: 1.15rem;
    padding-bottom: 3.5rem;
}

#MainMenu {
    visibility: hidden;
}

footer {
    visibility: hidden;
}

section[data-testid="stSidebar"] {
    background: #0a0a0a;
    border-right: 1px solid #202020;
}

/* ----------------------------------------------------------
   Header
---------------------------------------------------------- */

.brand {
    font-size: 28px;
    line-height: 1;
    font-weight: 800;
    letter-spacing: -1.5px;
    color: #fff;
}

.brand-sub {
    margin-top: 7px;
    color: #6f6f6f;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.7px;
}

.nav-caption {
    color: #6d6d6d;
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 5px;
}

/* ----------------------------------------------------------
   Inputs
---------------------------------------------------------- */

div[data-testid="stTextInput"] input {
    height: 44px;
    background: #121212;
    border: 1px solid #2b2b2b;
    border-radius: 8px;
    color: #f5f5f5;
    font-size: 13px;
}

div[data-testid="stTextInput"] input:hover {
    border-color: #3f3f3f;
}

div[data-testid="stTextInput"] input:focus {
    border-color: #666;
    box-shadow: none;
}

div[data-testid="stSelectbox"] > div > div {
    background: #121212;
    border: 1px solid #292929;
    border-radius: 8px;
    color: #eee;
}

/* ----------------------------------------------------------
   Buttons
---------------------------------------------------------- */

.stButton > button {
    min-height: 38px;
    background: #171717;
    border: 1px solid #303030;
    color: #eeeeee;
    border-radius: 8px;
    font-weight: 600;
    font-size: 12px;
    transition: all .18s ease;
}

.stButton > button:hover {
    background: #242424;
    border-color: #5b5b5b;
    color: #fff;
}

.stButton > button:focus {
    box-shadow: none;
}

.primary-btn .stButton > button {
    background: #f0f0f0;
    color: #090909;
    border-color: #f0f0f0;
}

.primary-btn .stButton > button:hover {
    background: #d5d5d5;
    border-color: #d5d5d5;
    color: #000;
}

/* ----------------------------------------------------------
   Dividers / headings
---------------------------------------------------------- */

.thin-line {
    height: 1px;
    background: #222;
    margin: 14px 0 20px;
}

.section-title {
    margin-top: 27px;
    margin-bottom: 5px;
    font-size: 21px;
    line-height: 1.2;
    font-weight: 750;
    letter-spacing: -.6px;
    color: #f5f5f5;
}

.section-caption {
    margin-bottom: 15px;
    color: #747474;
    font-size: 12px;
}

/* ----------------------------------------------------------
   Hero
---------------------------------------------------------- */

.hero {
    position: relative;
    min-height: 300px;
    border: 1px solid #292929;
    border-radius: 14px;
    overflow: hidden;
    background:
        linear-gradient(90deg, #151515 0%, #111 48%, #0b0b0b 100%);
}

.hero-image {
    position: absolute;
    right: 0;
    top: 0;
    width: 48%;
    height: 100%;
    object-fit: cover;
    opacity: .48;
    mask-image: linear-gradient(to right, transparent, black 32%);
    -webkit-mask-image: linear-gradient(to right, transparent, black 32%);
}

.hero-content {
    position: relative;
    z-index: 2;
    width: 61%;
    padding: 42px;
}

.hero-kicker {
    color: #8d8d8d;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.7px;
    text-transform: uppercase;
}

.hero-title {
    margin-top: 9px;
    color: #fff;
    font-size: 40px;
    line-height: 1.03;
    font-weight: 800;
    letter-spacing: -1.7px;
}

.hero-copy {
    margin-top: 14px;
    max-width: 690px;
    color: #a4a4a4;
    font-size: 13px;
    line-height: 1.75;
}

.hero-meta {
    margin-top: 18px;
    color: #c5c5c5;
    font-size: 11px;
}

/* ----------------------------------------------------------
   Movie cards
---------------------------------------------------------- */

.movie-card {
    background: #101010;
    border: 1px solid #242424;
    border-radius: 9px;
    overflow: hidden;
    transition: transform .18s ease, border-color .18s ease, background .18s ease;
}

.movie-card:hover {
    transform: translateY(-4px);
    border-color: #505050;
    background: #141414;
}

.poster-frame {
    position: relative;
    width: 100%;
    aspect-ratio: 2 / 3;
    overflow: hidden;
    background: #171717;
}

.poster-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

.poster-empty {
    width: 100%;
    height: 100%;
    min-height: 220px;
    display: flex;
    justify-content: center;
    align-items: center;
    color: #656565;
    font-size: 11px;
    background: #171717;
}

.rating-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    background: rgba(0,0,0,.78);
    border: 1px solid rgba(255,255,255,.14);
    color: #ddd;
    border-radius: 6px;
    padding: 4px 6px;
    font-size: 10px;
    font-weight: 700;
}

.movie-info {
    padding: 10px 10px 11px;
}

.movie-name {
    color: #ededed;
    font-size: 12px;
    font-weight: 650;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.movie-meta {
    color: #6e6e6e;
    font-size: 10px;
    margin-top: 5px;
}

/* ----------------------------------------------------------
   Detail page
---------------------------------------------------------- */

.detail-panel {
    background: #101010;
    border: 1px solid #292929;
    border-radius: 13px;
    padding: 25px;
}

.detail-title {
    color: #fff;
    font-size: 34px;
    line-height: 1.08;
    font-weight: 800;
    letter-spacing: -1.2px;
}

.detail-description {
    color: #a1a1a1;
    font-size: 13px;
    line-height: 1.8;
    margin-top: 15px;
}

.genre-pill {
    display: inline-block;
    margin: 3px 4px 3px 0;
    padding: 5px 9px;
    border: 1px solid #303030;
    border-radius: 99px;
    color: #bcbcbc;
    background: #181818;
    font-size: 10px;
}

/* ----------------------------------------------------------
   Search / status
---------------------------------------------------------- */

.search-summary {
    background: #101010;
    border: 1px solid #252525;
    border-radius: 10px;
    padding: 13px 15px;
    color: #8e8e8e;
    font-size: 12px;
    margin-bottom: 18px;
}

.status-box {
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    background: #111;
    padding: 15px;
    color: #999;
    font-size: 12px;
    line-height: 1.6;
}

.empty-state {
    border: 1px dashed #333;
    border-radius: 11px;
    background: #0d0d0d;
    padding: 45px 20px;
    text-align: center;
    color: #777;
    font-size: 13px;
}

/* ----------------------------------------------------------
   Watchlist
---------------------------------------------------------- */

.watchlist-count {
    display: inline-block;
    min-width: 20px;
    padding: 3px 6px;
    text-align: center;
    border: 1px solid #333;
    border-radius: 99px;
    color: #aaa;
    background: #151515;
    font-size: 9px;
}

/* ----------------------------------------------------------
   Mobile
---------------------------------------------------------- */

@media (max-width: 900px) {
    .hero-content {
        width: 100%;
        padding: 28px;
    }

    .hero-image {
        width: 60%;
        opacity: .25;
    }

    .hero-title {
        font-size: 31px;
    }

    .detail-title {
        font-size: 27px;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# HELPERS
# ============================================================

def safe_text(value: Any) -> str:
    """Convert a value to HTML-safe text."""
    if value is None:
        return ""
    return escape(str(value))


def year_from_date(value: Any) -> str:
    """Return YYYY from an API date."""
    if not value:
        return "—"
    text = str(value)
    return text[:4] if len(text) >= 4 else text


def rating_text(value: Any) -> str:
    """Format TMDB rating safely."""
    try:
        number = float(value)
        if number <= 0:
            return "—"
        return f"★ {number:.1f}"
    except (TypeError, ValueError):
        return "—"


def normalize_movie(movie: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize cards from different backend endpoints."""
    return {
        "tmdb_id": movie.get("tmdb_id", movie.get("id")),
        "title": movie.get("title") or movie.get("name") or "Untitled",
        "poster_url": movie.get("poster_url"),
        "backdrop_url": movie.get("backdrop_url"),
        "release_date": movie.get("release_date"),
        "vote_average": movie.get("vote_average"),
        "overview": movie.get("overview"),
        "genres": movie.get("genres") or [],
    }


def poster_url(movie: Dict[str, Any]) -> Optional[str]:
    """Get a usable poster URL from a normalized or raw TMDB object."""
    value = movie.get("poster_url")
    if value:
        return value

    path = movie.get("poster_path")
    if path:
        return f"https://image.tmdb.org/t/p/w500{path}"

    return None


def backdrop_url(movie: Dict[str, Any]) -> Optional[str]:
    """Get a usable backdrop URL."""
    value = movie.get("backdrop_url")
    if value:
        return value

    path = movie.get("backdrop_path")
    if path:
        return f"https://image.tmdb.org/t/p/w1280{path}"

    return None


def set_toast(message: str) -> None:
    """Show a short-lived message after reruns."""
    st.session_state["toast"] = message
    st.session_state["toast_time"] = time.time()


def show_toast() -> None:
    """Render the current toast if it is still fresh."""
    message = st.session_state.get("toast", "")
    timestamp = st.session_state.get("toast_time", 0.0)

    if message and time.time() - timestamp < 3:
        st.success(message)
    elif message:
        st.session_state["toast"] = ""


def in_watchlist(movie_id: Any) -> bool:
    """Check whether a movie ID is in the local session watchlist."""
    if movie_id is None:
        return False

    return any(
        str(item.get("tmdb_id")) == str(movie_id)
        for item in st.session_state["watchlist"]
    )


def add_to_watchlist(movie: Dict[str, Any]) -> None:
    """Add a normalized movie to the session watchlist."""
    movie = normalize_movie(movie)
    movie_id = movie.get("tmdb_id")

    if movie_id is None:
        return

    if not in_watchlist(movie_id):
        st.session_state["watchlist"].append(movie)
        set_toast(f"Added “{movie['title']}” to your watchlist.")


def remove_from_watchlist(movie_id: Any) -> None:
    """Remove a movie from the session watchlist."""
    st.session_state["watchlist"] = [
        item
        for item in st.session_state["watchlist"]
        if str(item.get("tmdb_id")) != str(movie_id)
    ]
    set_toast("Removed from your watchlist.")


# ============================================================
# API LAYER
# ============================================================

def api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 25,
) -> Optional[Any]:
    """
    Safe GET wrapper.

    It intentionally does not crash the Streamlit page when FastAPI/TMDB
    returns an error. This is important because /movie/search can fail
    independently of /home and /tmdb/search.
    """
    try:
        response = requests.get(
            f"{API_BASE}{path}",
            params=params or {},
            timeout=timeout,
        )

        if response.status_code >= 400:
            try:
                detail = response.json()
                detail = detail.get("detail", detail)
            except ValueError:
                detail = response.text

            return {
                "__error__": True,
                "status": response.status_code,
                "detail": str(detail),
            }

        return response.json()

    except requests.exceptions.ConnectionError:
        return {
            "__error__": True,
            "status": 0,
            "detail": (
                "FastAPI is not running. Start it with "
                "'python -m uvicorn main:app --reload'."
            ),
        }

    except requests.exceptions.Timeout:
        return {
            "__error__": True,
            "status": 0,
            "detail": "The backend request timed out. Please try again.",
        }

    except requests.exceptions.RequestException as exc:
        return {
            "__error__": True,
            "status": 0,
            "detail": f"Network error: {exc}",
        }

    except ValueError:
        return {
            "__error__": True,
            "status": 0,
            "detail": "The backend returned invalid JSON.",
        }


def is_api_error(data: Any) -> bool:
    """Return True when the API helper returned an error object."""
    return isinstance(data, dict) and bool(data.get("__error__"))


# ============================================================
# CACHED API FUNCTIONS
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_home(category: str) -> Any:
    """Load a dashboard collection."""
    return api_get(
        "/home",
        {"category": category, "limit": 24},
        timeout=30,
    )


@st.cache_data(ttl=300, show_spinner=False)
def search_tmdb(query: str) -> Any:
    """Search TMDB through the FastAPI backend."""
    return api_get(
        "/tmdb/search",
        {"query": query.strip(), "page": 1},
        timeout=30,
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_movie_details(movie_id: int) -> Any:
    """Load movie details."""
    return api_get(
        f"/movie/id/{movie_id}",
        timeout=30,
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_genre_recommendations(movie_id: int, limit: int = 12) -> Any:
    """Load genre recommendations independently of the bundle endpoint."""
    return api_get(
        "/recommend/genre",
        {"tmdb_id": movie_id, "limit": limit},
        timeout=35,
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_tfidf_recommendations(title: str, top_n: int = 12) -> Any:
    """Load local TF-IDF recommendations."""
    return api_get(
        "/recommend/tfidf",
        {"title": title, "top_n": top_n},
        timeout=35,
    )


@st.cache_data(ttl=300, show_spinner=False)
def find_tmdb_movie_by_title(title: str) -> Any:
    """Search TMDB for a recommendation title."""
    return api_get(
        "/tmdb/search",
        {"query": title, "page": 1},
        timeout=25,
    )


# ============================================================
# RENDERING
# ============================================================

def render_movie_card(movie: Dict[str, Any], key_prefix: str) -> None:
    """
    Render one movie card.

    The actual selection is done by a Streamlit button below the HTML card,
    so the page stays robust across Streamlit versions.
    """
    movie = normalize_movie(movie)
    title = movie["title"]
    movie_id = movie.get("tmdb_id")
    poster = poster_url(movie)
    year = year_from_date(movie.get("release_date"))
    rating = rating_text(movie.get("vote_average"))

    if poster:
        image_html = (
            f'<img class="poster-image" src="{escape(poster)}" '
            f'alt="{safe_text(title)}" loading="lazy">'
        )
    else:
        image_html = '<div class="poster-empty">POSTER UNAVAILABLE</div>'

    badge = ""
    if rating != "—":
        badge = f'<div class="rating-badge">{safe_text(rating)}</div>'

    st.markdown(
        f"""
        <div class="movie-card">
            <div class="poster-frame">
                {image_html}
                {badge}
            </div>
            <div class="movie-info">
                <div class="movie-name" title="{safe_text(title)}">
                    {safe_text(title)}
                </div>
                <div class="movie-meta">
                    {safe_text(year)}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    button_key = f"{key_prefix}_{movie_id or title}"

    if st.button(
        "View details",
        key=button_key,
        use_container_width=True,
    ):
        if movie_id is not None:
            st.session_state["selected_movie"] = movie_id
            st.session_state["selected_title"] = title
            st.session_state["page"] = "details"
            st.rerun()


def render_movie_grid(
    movies: List[Dict[str, Any]],
    key_prefix: str,
    columns: int = 6,
) -> None:
    """Render movies in stable rows."""
    if not movies:
        st.markdown(
            '<div class="empty-state">No movies available right now.</div>',
            unsafe_allow_html=True,
        )
        return

    for row_start in range(0, len(movies), columns):
        row = movies[row_start:row_start + columns]
        cols = st.columns(columns, gap="small")

        for index, movie in enumerate(row):
            with cols[index]:
                render_movie_card(
                    movie,
                    f"{key_prefix}_{row_start + index}",
                )


def render_error(data: Any, compact: bool = False) -> None:
    """Render a friendly API error instead of a traceback."""
    if not is_api_error(data):
        return

    status = data.get("status", "")
    detail = data.get("detail", "Unknown backend error.")

    if status == 502:
        title = "TMDB could not complete the request"
    elif status == 404:
        title = "Nothing was found"
    elif status == 0:
        title = "Backend connection problem"
    else:
        title = f"API request failed{f' ({status})' if status else ''}"

    if compact:
        st.warning(f"{title}: {detail}")
        return

    st.markdown(
        f"""
        <div class="status-box">
            <strong style="color:#ddd;">{safe_text(title)}</strong><br>
            <span>{safe_text(detail)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero(movie: Dict[str, Any], category: str) -> None:
    """Render the dashboard featured movie."""
    movie = normalize_movie(movie)
    title = movie["title"]
    backdrop = backdrop_url(movie)
    year = year_from_date(movie.get("release_date"))
    rating = rating_text(movie.get("vote_average"))

    image = ""
    if backdrop:
        image = (
            f'<img class="hero-image" src="{escape(backdrop)}" '
            f'alt="{safe_text(title)}">'
        )

    st.markdown(
        f"""
        <div class="hero">
            {image}
            <div class="hero-content">
                <div class="hero-kicker">
                    Featured · {safe_text(category)}
                </div>
                <div class="hero-title">
                    {safe_text(title)}
                </div>
                <div class="hero-copy">
                    Discover movies selected from your current TMDB feed,
                    then explore content-based recommendations from your
                    local recommendation model.
                </div>
                <div class="hero-meta">
                    {safe_text(year)}
                    &nbsp;&nbsp; • &nbsp;&nbsp;
                    {safe_text(rating)}
                    &nbsp;&nbsp; • &nbsp;&nbsp;
                    Movie
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    left, right = st.columns([1, 1])

    with left:
        if st.button(
            "Open featured movie",
            key="hero_open",
            use_container_width=True,
        ):
            if movie.get("tmdb_id") is not None:
                st.session_state["selected_movie"] = movie["tmdb_id"]
                st.session_state["selected_title"] = title
                st.session_state["page"] = "details"
                st.rerun()

    with right:
        if st.button(
            "Add to watchlist",
            key="hero_watchlist",
            use_container_width=True,
        ):
            add_to_watchlist(movie)
            st.rerun()


def render_search_results(data: Any, query: str) -> None:
    """Render search results from /tmdb/search."""
    if is_api_error(data):
        render_error(data)
        return

    if not isinstance(data, dict):
        st.warning("Unexpected response from the backend.")
        return

    raw_results = data.get("results", [])
    movies = [normalize_movie(item) for item in raw_results if isinstance(item, dict)]

    st.markdown(
        f"""
        <div class="search-summary">
            Showing results for <strong style="color:#ddd;">
            {safe_text(query)}
            </strong>
            &nbsp; · &nbsp; {len(movies)} results
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_movie_grid(movies, "search", 6)


def render_detail_page() -> None:
    """Render a complete movie detail page."""
    movie_id = st.session_state.get("selected_movie")
    fallback_title = st.session_state.get("selected_title", "")

    if movie_id is None:
        st.session_state["page"] = "home"
        st.rerun()

    top_left, top_right = st.columns([1, 5])

    with top_left:
        if st.button("← Dashboard", key="detail_back"):
            st.session_state["selected_movie"] = None
            st.session_state["selected_title"] = ""
            st.session_state["page"] = "home"
            st.rerun()

    with top_right:
        st.caption("MOVIE DETAILS")

    details = get_movie_details(int(movie_id))

    if is_api_error(details):
        render_error(details)
        return

    if not isinstance(details, dict):
        st.error("The backend returned an invalid movie response.")
        return

    details = normalize_movie(details)
    title = details.get("title") or fallback_title or "Movie"
    overview = details.get("overview") or "No synopsis is available."
    year = year_from_date(details.get("release_date"))
    rating = rating_text(details.get("vote_average"))
    poster = poster_url(details)
    genres = details.get("genres") or []

    left, right = st.columns([1.05, 2.35], gap="large")

    with left:
        if poster:
            st.image(poster, use_container_width=True)
        else:
            st.markdown(
                '<div class="poster-empty" style="min-height:400px;">'
                "POSTER UNAVAILABLE"
                "</div>",
                unsafe_allow_html=True,
            )

        if in_watchlist(movie_id):
            if st.button(
                "Remove from watchlist",
                key="detail_remove",
                use_container_width=True,
            ):
                remove_from_watchlist(movie_id)
                st.rerun()
        else:
            if st.button(
                "＋ Add to watchlist",
                key="detail_add",
                use_container_width=True,
            ):
                add_to_watchlist(details)
                st.rerun()

    with right:
        st.markdown('<div class="detail-panel">', unsafe_allow_html=True)

        st.markdown(
            f'<div class="detail-title">{safe_text(title)}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="movie-meta" style="font-size:12px;margin-top:10px;">
                {safe_text(year)}
                &nbsp; • &nbsp;
                {safe_text(rating)}
            </div>
            """,
            unsafe_allow_html=True,
        )

        if genres:
            pills = ""
            for genre in genres:
                if isinstance(genre, dict):
                    name = genre.get("name")
                else:
                    name = str(genre)
                pills += f'<span class="genre-pill">{safe_text(name)}</span>'

            st.markdown(
                f'<div style="margin-top:13px;">{pills}</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f"""
            <div class="detail-description">
                {safe_text(overview)}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------------------------
    # Independent recommendation sections
    # This deliberately avoids /movie/search so a TMDB 502
    # there does not destroy the entire movie detail page.
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">Because You Chose This</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-caption">'
        "Recommendations generated from your local TF-IDF model."
        "</div>",
        unsafe_allow_html=True,
    )

    tfidf = get_tfidf_recommendations(title, 12)

    if is_api_error(tfidf):
        st.info(
            "The local recommendation model could not find this title. "
            "You can still browse the genre recommendations below."
        )
    elif isinstance(tfidf, list):
        recommendation_cards: List[Dict[str, Any]] = []

        for item in tfidf:
            if not isinstance(item, dict):
                continue

            recommendation_title = item.get("title")
            if not recommendation_title:
                continue

            tmdb = item.get("tmdb")
            if isinstance(tmdb, dict):
                recommendation_cards.append(normalize_movie(tmdb))
                continue

            # Fallback: resolve each local title through TMDB search.
            # If one lookup fails, continue with the others.
            lookup = find_tmdb_movie_by_title(str(recommendation_title))

            if is_api_error(lookup):
                continue

            if isinstance(lookup, dict):
                results = lookup.get("results") or []
                if results:
                    recommendation_cards.append(
                        normalize_movie(results[0])
                    )

        # Remove duplicates while preserving order.
        unique_cards = []
        seen_ids = set()

        for card in recommendation_cards:
            card_id = card.get("tmdb_id")
            if card_id in seen_ids:
                continue
            seen_ids.add(card_id)
            unique_cards.append(card)

        if unique_cards:
            render_movie_grid(unique_cards[:12], "tfidf", 6)
        else:
            st.info(
                "No poster-backed TF-IDF recommendations were available "
                "for this title."
            )
    else:
        st.info("No local recommendations are available.")

    # --------------------------------------------------------
    # Genre recommendations
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">More Like This</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-caption">'
        "Popular movies from the selected movie's primary genre."
        "</div>",
        unsafe_allow_html=True,
    )

    genre_data = get_genre_recommendations(int(movie_id), 12)

    if is_api_error(genre_data):
        render_error(genre_data, compact=True)
    elif isinstance(genre_data, list):
        genre_movies = [
            normalize_movie(item)
            for item in genre_data
            if isinstance(item, dict)
        ]

        if genre_movies:
            render_movie_grid(genre_movies, "genre", 6)
        else:
            st.info("No genre recommendations are available.")
    else:
        st.info("No genre recommendations are available.")


def render_watchlist() -> None:
    """Render the session-local watchlist."""
    st.markdown(
        '<div class="section-title">My Watchlist</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-caption">'
        "Your saved movies for this browser session."
        "</div>",
        unsafe_allow_html=True,
    )

    movies = st.session_state["watchlist"]

    if not movies:
        st.markdown(
            """
            <div class="empty-state">
                <div style="font-size:22px;margin-bottom:8px;">＋</div>
                Your watchlist is empty.<br>
                Add movies from any movie card or detail page.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for row_start in range(0, len(movies), 6):
        row = movies[row_start:row_start + 6]
        cols = st.columns(6, gap="small")

        for index, movie in enumerate(row):
            with cols[index]:
                render_movie_card(
                    movie,
                    f"watchlist_{row_start + index}",
                )

                movie_id = movie.get("tmdb_id")
                if st.button(
                    "Remove",
                    key=f"remove_watch_{row_start}_{index}",
                    use_container_width=True,
                ):
                    remove_from_watchlist(movie_id)
                    st.rerun()


# ============================================================
# HEADER
# ============================================================

header_left, header_search, header_browse, header_watchlist = st.columns(
    [1.8, 3.0, 1.8, 1.0],
    gap="medium",
)

with header_left:
    st.markdown(
        """
        <div class="brand">CINEVAULT</div>
        <div class="brand-sub">PERSONAL MOVIE DISCOVERY</div>
        """,
        unsafe_allow_html=True,
    )

with header_search:
    search_value = st.text_input(
        "Search movies",
        value=st.session_state.get("search_query", ""),
        placeholder="Search movies, actors, titles...",
        label_visibility="collapsed",
        key="global_search_box",
    )

with header_browse:
    browse_value = st.selectbox(
        "Browse",
        [
            "Trending",
            "Popular",
            "Top Rated",
            "Upcoming",
            "Now Playing",
        ],
        label_visibility="collapsed",
        key="browse_select",
    )

with header_watchlist:
    st.markdown(
        '<div class="nav-caption">Saved</div>',
        unsafe_allow_html=True,
    )

    if st.button(
        f"Watchlist ({len(st.session_state['watchlist'])})",
        key="watchlist_nav",
        use_container_width=True,
    ):
        st.session_state["page"] = "watchlist"
        st.session_state["selected_movie"] = None
        st.rerun()

st.markdown('<div class="thin-line"></div>', unsafe_allow_html=True)

show_toast()

# ============================================================
# SEARCH ROUTING
# ============================================================

clean_search = search_value.strip()

if clean_search:
    st.session_state["search_query"] = clean_search
    st.session_state["page"] = "search"
    st.session_state["selected_movie"] = None

# ============================================================
# PAGE ROUTING
# ============================================================

current_page = st.session_state.get("page", "home")

if current_page == "details":
    render_detail_page()

elif current_page == "watchlist":
    render_watchlist()

elif current_page == "search":
    st.markdown(
        f'<div class="section-title">Search</div>',
        unsafe_allow_html=True,
    )

    if st.button("← Back to dashboard", key="search_back"):
        st.session_state["search_query"] = ""
        st.session_state["page"] = "home"
        st.rerun()

    query = st.session_state.get("search_query", "").strip()

    if not query:
        st.session_state["page"] = "home"
        st.rerun()

    data = search_tmdb(query)
    render_search_results(data, query)

else:
    # ========================================================
    # DASHBOARD
    # ========================================================

    category_map = {
        "Trending": "trending",
        "Popular": "popular",
        "Top Rated": "top_rated",
        "Upcoming": "upcoming",
        "Now Playing": "now_playing",
    }

    selected_category = category_map.get(
        browse_value,
        "popular",
    )

    feed = get_home(selected_category)

    if is_api_error(feed):
        render_error(feed)

        st.markdown(
            """
            <div class="section-caption" style="margin-top:15px;">
                The dashboard cannot load TMDB data until the FastAPI
                backend and TMDB credentials are working.
            </div>
            """,
            unsafe_allow_html=True,
        )

    elif isinstance(feed, list):
        movies = [
            normalize_movie(item)
            for item in feed
            if isinstance(item, dict)
        ]

        if movies:
            render_hero(movies[0], browse_value)

            st.markdown(
                f'<div class="section-title">{safe_text(browse_value)}</div>',
                unsafe_allow_html=True,
            )

            st.markdown(
                '<div class="section-caption">'
                "A clean selection from your current movie feed."
                "</div>",
                unsafe_allow_html=True,
            )

            render_movie_grid(movies, "dashboard", 6)

        else:
            st.markdown(
                """
                <div class="empty-state">
                    No movies were returned by the backend.
                </div>
                """,
                unsafe_allow_html=True,
            )

    else:
        st.error("Unexpected response from the FastAPI backend.")

    # ========================================================
    # SECONDARY COLLECTION
    # ========================================================

    secondary_category = (
        "top_rated"
        if selected_category != "top_rated"
        else "popular"
    )

    secondary_label = (
        "Top Rated"
        if secondary_category == "top_rated"
        else "Popular Picks"
    )

    secondary_feed = get_home(secondary_category)

    if isinstance(secondary_feed, list):
        secondary_movies = [
            normalize_movie(item)
            for item in secondary_feed[:12]
            if isinstance(item, dict)
        ]

        if secondary_movies:
            st.markdown(
                f'<div class="section-title">'
                f'{safe_text(secondary_label)}'
                f'</div>',
                unsafe_allow_html=True,
            )

            st.markdown(
                '<div class="section-caption">'
                "A second collection for when you want something different."
                "</div>",
                unsafe_allow_html=True,
            )

            render_movie_grid(
                secondary_movies,
                "secondary",
                6,
            )

# ============================================================
# FOOTER
# ============================================================

st.markdown('<div class="thin-line"></div>', unsafe_allow_html=True)

st.markdown(
    """
    <div style="
        text-align:center;
        color:#555;
        font-size:10px;
        letter-spacing:.3px;
        padding:8px 0 0;
    ">
        CINEVAULT &nbsp; • &nbsp; FASTAPI + STREAMLIT
        &nbsp; • &nbsp; TMDB MOVIE DATA
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# END
# ============================================================
