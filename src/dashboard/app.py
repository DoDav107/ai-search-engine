"""Streamlit dashboard for running and visualising SEO/GEO audit reports.

Rendering is read-only: it displays `data/reports/latest_report.json` and never
makes live API calls on page load. The sidebar's New Audit form is the explicit
entry point for running the pipeline.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Path anchoring — all paths derived from this file's location
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
REPORTS_DIR = REPO_ROOT / "data" / "reports"

# Ensure REPO_ROOT is importable so src.* imports resolve correctly
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Eloize SEO/GEO Dashboard",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Palette + constants
# ---------------------------------------------------------------------------
GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"
ACCENT = "#7c5cff"
INK = "#e8eaf2"

_STATUS_LABEL: dict[str, str] = {"pass": "✅ pass", "warn": "⚠️ warn", "fail": "❌ fail"}
_STATUS_COLOR: dict[str, str] = {"pass": GREEN, "warn": AMBER, "fail": RED}
_PRIORITY_RANK: dict[str, int] = {"High": 0, "Medium": 1, "Low": 2}
_PRIORITY_COLOR: dict[str, str] = {"High": RED, "Medium": AMBER, "Low": "#64748b"}
_FACTOR_LABEL: dict[str, str] = {
    "title": "Title",
    "meta_description": "Meta description",
    "h1": "H1 heading",
    "canonical": "Canonical",
    "image_alt": "Image alt text",
    "word_count": "Word count",
    "structured_data": "Structured data",
    "crawl_access": "Crawl access",
    "audit_coverage": "Audit coverage",
    "https_enabled": "HTTPS",
    "domain_brand_signal": "Brand/domain signal",
    "canonical_url_shape": "Canonical URL shape",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fix_mojibake(text: str) -> str:
    """Fix text where UTF-8 bytes were decoded as Latin-1 (e.g. â€" → —)."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return text


def _band(score: float) -> str:
    """Colour band for a 0–100 score."""
    if score >= 80:
        return GREEN
    if score >= 50:
        return AMBER
    return RED


def _rating_dot(score: float) -> str:
    if score >= 80:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


def _factor_label(fid: str) -> str:
    return _FACTOR_LABEL.get(fid, fid.replace("_", " ").title())


def _report_caption(path: Path) -> str:
    """Human-readable freshness caption from a report filename timestamp."""
    ts_raw = path.stem.rsplit("_", 1)[-1]
    try:
        dt = datetime.strptime(ts_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        ts_str = dt.strftime("%d %b %Y · %H:%M UTC")
    except ValueError:
        mtime = path.stat().st_mtime
        ts_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    return ts_str


@st.cache_data
def _load_json(path_str: str, _mtime: float) -> Any:
    """Parse JSON; cache key includes mtime so regenerated files invalidate it."""
    with open(path_str, encoding="utf-8") as fh:
        return json.load(fh)


def _prominence(r: dict) -> float | None:
    """Display-only prominence (0–100). Mirrors the report's measurement; no rescoring."""
    if not r.get("brand_mentioned") or r.get("first_position") is None:
        return None
    ans_len = len(r.get("answer") or "")
    if ans_len <= 0:
        return None
    pct = (1.0 - r["first_position"] / ans_len) * 100
    return round(max(0.0, min(pct, 100.0)), 1)


# ---------------------------------------------------------------------------
# Custom CSS — animated gradient, glassmorphism, fade-in
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        :root {
            --glass-bg: rgba(255, 255, 255, 0.06);
            --glass-border: rgba(255, 255, 255, 0.12);
            --ink: #e8eaf2;
            --muted: #9aa3b8;
            --accent: #7c5cff;
        }

        html, body, [class*="css"], .stApp, .stMarkdown, p, span, label, div {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }

        /* Animated gradient backdrop — slow + professional */
        .stApp {
            background: linear-gradient(-45deg, #0b1020, #131a32, #1a1340, #0f1b33, #0b1020);
            background-size: 400% 400%;
            animation: gradientShift 28s ease infinite;
            color: var(--ink);
        }
        @keyframes gradientShift {
            0%   { background-position: 0% 50%; }
            50%  { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* Soft floating aura overlay */
        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            background:
                radial-gradient(40rem 40rem at 12% 8%, rgba(124,92,255,0.18), transparent 60%),
                radial-gradient(36rem 36rem at 88% 18%, rgba(34,197,94,0.10), transparent 60%),
                radial-gradient(34rem 34rem at 70% 90%, rgba(56,189,248,0.10), transparent 60%);
            pointer-events: none;
            z-index: 0;
        }
        .main .block-container { position: relative; z-index: 1; padding-top: 2.2rem; max-width: 1500px; }

        /* Sidebar glass */
        section[data-testid="stSidebar"] {
            background: rgba(10, 14, 28, 0.7);
            backdrop-filter: blur(14px);
            border-right: 1px solid var(--glass-border);
        }

        /* Headings */
        h1, h2, h3, h4 { color: var(--ink) !important; letter-spacing: -0.01em; }
        h2 { font-weight: 700 !important; margin-top: 0.4rem !important; }

        /* Section + element entrance animations (staggered) */
        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(16px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .main .block-container > div { animation: fadeUp 0.6s ease both; }
        .main .block-container > div:nth-child(2)  { animation-delay: 0.05s; }
        .main .block-container > div:nth-child(3)  { animation-delay: 0.10s; }
        .main .block-container > div:nth-child(4)  { animation-delay: 0.15s; }
        .main .block-container > div:nth-child(5)  { animation-delay: 0.20s; }
        .main .block-container > div:nth-child(6)  { animation-delay: 0.25s; }
        .main .block-container > div:nth-child(7)  { animation-delay: 0.30s; }

        /* Hero */
        .hero {
            background: linear-gradient(120deg, rgba(124,92,255,0.20), rgba(56,189,248,0.10));
            border: 1px solid var(--glass-border);
            border-radius: 22px;
            padding: 26px 30px;
            backdrop-filter: blur(16px);
            box-shadow: 0 18px 50px rgba(0,0,0,0.35);
            margin-bottom: 6px;
        }
        .hero h1 { margin: 0; font-size: 2.05rem; font-weight: 800; }
        .hero .sub { color: var(--muted); margin-top: 6px; font-size: 0.95rem; }
        .pill {
            display:inline-block; padding: 3px 12px; border-radius: 999px;
            font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em;
            background: rgba(255,255,255,0.10); border: 1px solid var(--glass-border);
            color: var(--ink); margin-right: 6px;
        }

        /* Glass metric cards */
        .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; }
        .gcard {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 18px;
            padding: 20px 22px;
            backdrop-filter: blur(14px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.28);
            transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
        }
        .gcard:hover {
            transform: translateY(-6px);
            box-shadow: 0 22px 48px rgba(0,0,0,0.42);
            border-color: rgba(255,255,255,0.28);
        }
        .gcard .label { color: var(--muted); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
        .gcard .value { font-size: 2.1rem; font-weight: 800; margin-top: 4px; line-height: 1.1; }
        .gcard .foot  { color: var(--muted); font-size: 0.8rem; margin-top: 2px; }

        /* Recommendation cards */
        .rec {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-left-width: 5px;
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 12px;
            backdrop-filter: blur(10px);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .rec:hover { transform: translateY(-3px); box-shadow: 0 14px 34px rgba(0,0,0,0.32); }
        .rec .rtitle { font-weight: 700; font-size: 1.02rem; }
        .rec .rscope { color: var(--muted); font-size: 0.82rem; margin: 4px 0 10px; }
        .rec .field { margin: 7px 0; font-size: 0.9rem; line-height: 1.5; }
        .rec .field b { color: var(--ink); }
        .badge {
            display:inline-block; padding: 2px 11px; border-radius: 999px;
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; color: #0b1020;
        }

        /* Streamlit metric fallback styling */
        div[data-testid="stMetric"] {
            background: var(--glass-bg); border: 1px solid var(--glass-border);
            border-radius: 16px; padding: 14px 18px; backdrop-filter: blur(12px);
        }

        /* Expanders */
        details, div[data-testid="stExpander"] {
            /* Dark-tinted glass so header URLs/percentages stay readable over the
               bright parts of the animated gradient (not washed-out white glass). */
            background: rgba(13, 18, 32, 0.55);
            border: 1px solid var(--glass-border) !important;
            border-radius: 14px !important;
            backdrop-filter: blur(8px);
            margin-bottom: 8px;
        }
        [data-testid="stExpander"] summary {
            display: flex;
            align-items: center;
            gap: 0.55rem;            /* keeps marker and label from ever touching */
            padding: 11px 15px;
            font-size: 0.92rem;
            background: transparent !important;   /* override Streamlit's light open/hover fill */
            color: var(--ink);
        }
        [data-testid="stExpander"] summary:hover {
            background: rgba(255,255,255,0.06) !important;   /* subtle, stays dark + readable */
        }

        /* Font-independent icon markers --------------------------------------
           Streamlit draws expander chevrons (and the sidebar collapse control) as
           Material Symbols ligatures inside [data-testid="stIconMaterial"]. When
           that icon font is unavailable — or overridden by our Inter rule above —
           the ligature leaks as raw text ("keyboard_arrow_right") and overlaps the
           label. Hide the text and substitute a plain Unicode glyph that renders
           without any icon font (the way the 🔴🟡🟢 dots already do). */
        span[data-testid="stIconMaterial"] {
            font-size: 0 !important;        /* suppress the leaked ligature text */
            width: 1.15rem;                 /* rem, not em — em would collapse at font-size:0 */
            min-width: 1.15rem;
            height: 1.15rem;
            display: inline-flex !important;
            align-items: center;
            justify-content: center;
            color: var(--muted);
        }
        span[data-testid="stIconMaterial"]::after {
            content: "▸";
            font-size: 0.95rem;
            line-height: 1;
            font-family: 'Inter', -apple-system, sans-serif;
        }
        details[open] > summary span[data-testid="stIconMaterial"]::after,
        [data-testid="stExpander"][open] summary span[data-testid="stIconMaterial"]::after {
            content: "▾";                   /* open-state affordance */
        }
        section[data-testid="stSidebar"] span[data-testid="stIconMaterial"]::after {
            content: "«";                   /* sidebar collapse points left */
        }

        /* Readable expander headers — URLs and percentages */
        [data-testid="stExpander"] summary p { color: var(--ink) !important; margin: 0; }
        [data-testid="stExpander"] summary a {
            color: #cbd6ef !important; font-weight: 600; text-decoration: none;
        }
        [data-testid="stExpander"] summary a:hover {
            color: #ffffff !important; text-decoration: underline;
        }

        /* Factor-by-factor + recommendation field rows — clear, well-spaced text */
        .field { font-size: 0.9rem; line-height: 1.6; color: #dbe2f0; margin: 8px 0; }
        .field b { color: var(--ink); }

        /* Buttons */
        .stButton button, .stDownloadButton button {
            border-radius: 12px; border: 1px solid var(--glass-border);
            background: rgba(255,255,255,0.06); color: var(--ink); font-weight: 600;
            transition: all 0.2s ease;
        }
        .stButton button:hover, .stDownloadButton button:hover {
            border-color: var(--accent); background: rgba(124,92,255,0.18); transform: translateY(-2px);
        }
        .stDataFrame { border-radius: 12px; overflow: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge_html(text: str, color: str, dark_text: bool = True) -> str:
    fg = "#0b1020" if dark_text else "#ffffff"
    return f'<span class="badge" style="background:{color};color:{fg};">{escape(text)}</span>'


def _copy_button(text: str, key: str) -> None:
    """A small self-contained copy-to-clipboard button (no live API calls)."""
    payload = json.dumps(text)  # safe JS string literal
    components.html(
        f"""
        <button id="b_{key}" style="
            cursor:pointer;border-radius:10px;padding:6px 14px;font-weight:600;
            font-family:Inter,sans-serif;font-size:0.8rem;
            background:rgba(124,92,255,0.18);color:#e8eaf2;
            border:1px solid rgba(255,255,255,0.18);transition:all .2s;">
            📋 Copy draft
        </button>
        <script>
        const b = document.getElementById("b_{key}");
        b.addEventListener("click", async () => {{
            try {{
                await navigator.clipboard.writeText({payload});
                b.innerText = "✓ Copied!";
                b.style.background = "rgba(34,197,94,0.25)";
                setTimeout(() => {{ b.innerText = "📋 Copy draft"; b.style.background = "rgba(124,92,255,0.18)"; }}, 1600);
            }} catch (e) {{
                b.innerText = "⚠ Press Ctrl/Cmd+C";
            }}
        }});
        </script>
        """,
        height=44,
    )


def _gauge(title: str, value: float) -> go.Figure:
    color = _band(value)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": "%", "font": {"size": 34, "color": INK}},
            title={"text": title, "font": {"size": 15, "color": "#9aa3b8"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#5b6478", "tickfont": {"color": "#9aa3b8", "size": 10}},
                "bar": {"color": color, "thickness": 0.28},
                "bgcolor": "rgba(255,255,255,0.04)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 50], "color": "rgba(239,68,68,0.18)"},
                    {"range": [50, 80], "color": "rgba(245,158,11,0.18)"},
                    {"range": [80, 100], "color": "rgba(34,197,94,0.18)"},
                ],
                "threshold": {"line": {"color": color, "width": 3}, "thickness": 0.75, "value": value},
            },
        )
    )
    fig.update_layout(
        height=240,
        margin=dict(l=20, r=20, t=46, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": INK, "family": "Inter"},
    )
    return fig


def _render_draft(draft: str) -> None:
    if draft.strip().startswith("{"):
        st.code(draft, language="json")
    else:
        st.markdown(draft)


# ---------------------------------------------------------------------------
# Load report
# ---------------------------------------------------------------------------
inject_css()

# ---------------------------------------------------------------------------
# New Audit — trigger the pipeline in-process for a custom brand/domain/queries.
# Diagnose-and-recommend only (crawl + measure + draft); never publishes or edits
# the live site. The read-only "view last report" mode below is the default and
# works with no input.
# ---------------------------------------------------------------------------
MAX_QUERIES = 10

# Audit-level default region for locale-grounded web search. "global" = no grounding.
# Codes are ISO-3166 alpha-2; per-query overrides still come from config. Shared label
# wording with the Next.js form so both surfaces read identically.
LOCALE_OPTIONS: list[tuple[str, str]] = [
    ("global", "🌍 Global / no region"),
    ("AU", "🇦🇺 Australia"),
    ("US", "🇺🇸 United States"),
    ("GB", "🇬🇧 United Kingdom"),
    ("NZ", "🇳🇿 New Zealand"),
    ("CA", "🇨🇦 Canada"),
    ("IE", "🇮🇪 Ireland"),
    ("IN", "🇮🇳 India"),
    ("SG", "🇸🇬 Singapore"),
]


def _geo_options() -> dict[str, Any]:
    try:
        from src.reporting.geo_options import load_geo_options
        return load_geo_options(str(REPO_ROOT / "config" / "geo_config.yaml"))
    except Exception:
        return {
            "default_provider": "openai",
            "default_model": "gpt-5.5",
            "allow_env_key_write": False,
            "providers": {
                "openai": {
                    "label": "OpenAI",
                    "env_key_name": "OPENAI_API_KEY",
                    "ui_selectable": True,
                    "key_present": bool(os.environ.get("OPENAI_API_KEY")),
                    "models": [{"id": "gpt-5.5", "label": "gpt-5.5"}],
                },
                "mock": {
                    "label": "Mock / Demo",
                    "env_key_name": None,
                    "ui_selectable": False,
                    "key_present": True,
                    "models": [{"id": "mock-default", "label": "mock-default"}],
                },
            },
        }


@contextmanager
def _temporary_provider_key(provider: str, key: str | None):
    """Temporarily set the SELECTED provider's API-key env var (not just OpenAI's)."""
    from src.agents.geo_agent import PROVIDER_ENV_VAR

    env_var = PROVIDER_ENV_VAR.get((provider or "").strip().lower())
    if not env_var or not key:
        yield
        return
    previous = os.environ.get(env_var)
    os.environ[env_var] = key
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = previous
report_path = REPORTS_DIR / "latest_report.json"


def _normalize_audit_url(url: str) -> str:
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def _validate_audit(
    client: str, brand: str, url: str, queries_raw: str
) -> tuple[str, str, str, list[str], list[str]]:
    """Return (client, brand, normalized_url, queries, errors). Never raises."""
    from urllib.parse import urlparse

    errors: list[str] = []
    client = (client or "").strip()
    brand = (brand or "").strip()
    url = _normalize_audit_url(url)
    queries = [q.strip() for q in (queries_raw or "").splitlines() if q.strip()]
    if not client:
        errors.append("Client is required.")
    if not brand:
        errors.append("Brand / company name is required.")
    parsed = urlparse(url)
    if not (parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc):
        errors.append("Enter a valid website URL (e.g. https://example.com).")
    if not queries:
        errors.append("Add at least one target query (one per line).")
    if len(queries) > MAX_QUERIES:
        errors.append(f"Too many queries ({len(queries)}). The cap is {MAX_QUERIES} — remove some.")
    return client, brand, url, queries, errors


# Sidebar form — rendered first so it's available even before any report exists.
with st.sidebar:
    with st.expander("🚀 New Audit", expanded=not report_path.exists()):
        st.caption(
            "Run a fresh audit on your own brand and domain. Diagnose-and-recommend only — "
            "it never publishes or changes your site."
        )
        na_client = st.text_input("Client", key="na_client", placeholder="e.g. Acme Retail")
        na_brand = st.text_input("Brand / company name", key="na_brand", placeholder="e.g. Acme Running")
        na_url = st.text_input("Website URL", key="na_url", placeholder="https://example.com")
        na_queries = st.text_area(
            "Target queries (one per line)", key="na_queries", height=130,
            placeholder="What are the best running shoe brands?\nMost popular sneakers right now?",
        )
        _geo_opts = _geo_options()
        _providers: dict[str, Any] = _geo_opts.get("providers") or {}
        # Only UI-selectable providers appear (mock is backend-only — filtered, not hardcoded).
        _provider_ids = [pid for pid, cfg in _providers.items() if cfg.get("ui_selectable", True)]
        _default_provider = _geo_opts.get("default_provider") if _geo_opts.get("default_provider") in _provider_ids else (_provider_ids[0] if _provider_ids else "openai")
        _provider_labels = {pid: str(cfg.get("label") or pid) for pid, cfg in _providers.items()}
        na_provider = st.selectbox(
            "AI provider",
            _provider_ids,
            index=_provider_ids.index(_default_provider) if _default_provider in _provider_ids else 0,
            format_func=lambda pid: _provider_labels.get(pid, pid),
            key="na_geo_provider",
        )
        _models = list((_providers.get(na_provider) or {}).get("models") or [])
        _model_ids = [str(m.get("id")) for m in _models if m.get("id")]
        _model_labels = {str(m.get("id")): str(m.get("label") or m.get("id")) for m in _models if m.get("id")}
        _default_model = _geo_opts.get("default_model") if _geo_opts.get("default_model") in _model_ids else (_model_ids[0] if _model_ids else "")
        na_model = st.selectbox(
            "AI model",
            _model_ids,
            index=_model_ids.index(_default_model) if _default_model in _model_ids else 0,
            format_func=lambda mid: _model_labels.get(mid, mid),
            key=f"na_geo_model_{na_provider}",
        )
        # Audit-level default region (per-query overrides come from config).
        _locale_codes = [code for code, _ in LOCALE_OPTIONS]
        _locale_labels = {code: label for code, label in LOCALE_OPTIONS}
        na_locale = st.selectbox(
            "Default region",
            _locale_codes,
            index=0,
            format_func=lambda code: _locale_labels.get(code, code),
            key="na_geo_locale",
            help="Grounds the web search in a region so the competitive set is region-correct. "
            "Global applies no region. Individual queries can override this in config.",
        )
        na_api_key_mode = "env"
        na_temporary_key = ""
        na_save_key = False
        _sel_cfg = _providers.get(na_provider) or {}
        if na_provider != "mock":
            na_api_key_mode = st.radio(
                "API key mode",
                ["env", "temporary"],
                format_func=lambda v: "Use saved server key from .env" if v == "env" else "Provide temporary key for this audit",
                horizontal=False,
                key="na_api_key_mode",
            )
            if na_api_key_mode == "env" and not _sel_cfg.get("key_present", True):
                st.warning(
                    f"No {_sel_cfg.get('env_key_name') or 'API key'} configured on the server — "
                    "add it to your .env or choose “Provide temporary key for this audit”."
                )
            if na_api_key_mode == "temporary":
                na_temporary_key = st.text_input(
                    "Temporary API key",
                    type="password",
                    key="na_temporary_api_key",
                    placeholder=str(_sel_cfg.get("env_key_name") or "API key"),
                )
                # Opt-in "save to .env" — only when the server enables it. The label is
                # derived LIVE from the selected provider so the key always matches it.
                if bool(_geo_opts.get("allow_env_key_write")):
                    _prov_label = _sel_cfg.get("label") or na_provider
                    _env_var = _sel_cfg.get("env_key_name") or "API key"
                    na_save_key = st.checkbox(
                        f"Save this key to .env as the {_prov_label} server key ({_env_var}) — local only",
                        key="na_save_key",
                    )
            st.caption("Temporary keys are used only for this audit and are not saved to reports, config, logs, or git.")
        _q_count = len([q for q in (na_queries or "").splitlines() if q.strip()])
        st.caption(f"{_q_count}/{MAX_QUERIES} queries · each runs a live web-search measurement (paid).")
        na_confirm = st.checkbox(
            "I understand this crawls the site and makes live, paid AI calls.", key="na_confirm"
        )
        if st.button("Run Audit", type="primary", width="stretch", key="na_run"):
            _c, _b, _u, _qs, _errs = _validate_audit(na_client, na_brand, na_url, na_queries)
            if not na_provider:
                _errs.append("Choose an AI provider.")
            if not na_model:
                _errs.append("Choose an AI model.")
            if na_api_key_mode == "temporary" and na_provider != "mock" and not na_temporary_key.strip():
                _errs.append("Enter a temporary API key or choose the saved server key.")
            if not na_confirm:
                _errs.append("Tick the confirmation box before running.")
            # Opt-in save: persist the SELECTED-provider key to .env (server-side, gated +
            # provider-match validated). A refusal is surfaced but doesn't block the run;
            # the key is never stored in the report/config either way.
            if not _errs and na_api_key_mode == "temporary" and na_save_key and na_provider != "mock":
                from src.security.env_writer import save_provider_key_to_env
                _save_res = save_provider_key_to_env(na_provider, na_temporary_key.strip())
                if _save_res.get("ok"):
                    st.success(
                        f"Saved {_save_res['env_var']} for {_save_res['provider']} (…{_save_res['last4']})."
                    )
                else:
                    st.warning(f"Not saved: {_save_res.get('message') or 'key was rejected.'}")
            if _errs:
                for _e in _errs:
                    st.error(_e)
            else:
                _use_temp = na_api_key_mode == "temporary"
                st.session_state["pending_audit"] = {
                    "client": _c,
                    "brand": _b,
                    "url": _u,
                    "queries": _qs,
                    "geo_provider": na_provider,
                    "geo_model": na_model,
                    "geo_locale": na_locale,
                    "api_key_mode": "temporary" if _use_temp else "env",
                    "temporary_api_key": na_temporary_key.strip() if _use_temp else "",
                }
                st.rerun()


# Pending-audit executor — runs in the main area with live, streamed progress.
_pending = st.session_state.get("pending_audit")
if _pending:
    import time as _time

    st.markdown("## 🚀 Running New Audit")
    st.caption(
        f"{_pending.get('client') or _pending['brand']} · {_pending['brand']} — "
        f"{_pending['url']} · {len(_pending['queries'])} query(ies)"
    )
    _status = st.status("Starting…", expanded=True)
    _log = st.empty()
    _start = _time.time()
    _lines: list[str] = []

    def _audit_progress(ev: dict) -> None:
        elapsed = _time.time() - _start
        phase = ev.get("phase")
        if phase == "crawl":
            msg = "🕷️ Crawling site & scoring SEO…"
        elif phase == "crawl_done":
            msg = f"✅ SEO scored — {ev.get('pages', 0)} page(s)"
        elif phase == "geo_start":
            msg = f"🤖 GEO measurement ({ev.get('total', 0)} queries)…"
        elif phase == "geo":
            browsed = "🌐 browsed" if ev.get("web_search_used") else "⚠️ no browse"
            err = " · error" if ev.get("error") else ""
            msg = f"[GEO {ev.get('index')}/{ev.get('total')}] {str(ev.get('query', ''))[:60]} — {browsed}{err}"
        elif phase == "recommend":
            msg = "📝 Building recommendations & draft fixes…"
        elif phase == "saving":
            msg = "💾 Saving report (latest + history) and PDF…"
        elif phase == "done":
            msg = "🎉 Audit complete."
        else:
            msg = ev.get("message", "")
        _lines.append(f"`{elapsed:5.0f}s`  {msg}")
        _status.update(label=f"{msg}   ·   {elapsed:.0f}s elapsed")
        _log.markdown("\n\n".join(_lines[-14:]))

    try:
        from src.pipeline import build_audit_configs, run_pipeline

        _seo_cfg, _geo_cfg = build_audit_configs(
            client=_pending.get("client") or _pending["brand"],
            brand=_pending["brand"],
            base_url=_pending["url"],
            queries=_pending["queries"],
            geo_provider=_pending.get("geo_provider"),
            geo_model=_pending.get("geo_model"),
            geo_locale=_pending.get("geo_locale"),
            api_key_source="temporary" if _pending.get("api_key_mode") == "temporary" else "env",
        )
        if _pending.get("api_key_mode") == "temporary" and _pending.get("temporary_api_key"):
            _geo_cfg["_temporary_api_key"] = _pending.get("temporary_api_key")
        with _temporary_provider_key(_pending.get("geo_provider", ""), _pending.get("temporary_api_key")):
            run_pipeline(seo_config=_seo_cfg, geo_config=_geo_cfg, progress=_audit_progress)
        _status.update(label="Audit complete — loading report…", state="complete")
        st.session_state.pop("pending_audit", None)
        st.cache_data.clear()
        st.rerun()
    except Exception as _exc:  # keep the app usable; never hang
        _status.update(label="Audit failed", state="error")
        st.session_state.pop("pending_audit", None)
        st.error(f"Audit failed: {_exc}")
        st.info("Your previous report (if any) is shown below — adjust the inputs in the sidebar and retry.")


if not report_path.exists():
    st.info("No report yet — start one from the **🚀 New Audit** panel in the sidebar.")
    st.stop()

combined: dict = _load_json(str(report_path), report_path.stat().st_mtime) or {}
brand = (combined.get("brand") or combined.get("site_name") or "").strip()
generated = _report_caption(report_path)

unified = float(combined.get("unified_score") or 0.0)
seo_score = float(combined.get("seo_score") or 0.0)
geo_score = float(combined.get("geo_score") or 0.0)

seo = combined.get("seo_report") or {}
geo = combined.get("geo_report") or {}
pages = seo.get("pages") or []
geo_results = geo.get("results") or []
seo_recs = combined.get("seo_recommendations") or []
geo_recs = combined.get("geo_recommendations") or []

scored_pages = [p for p in pages if p.get("factors")]
skipped_pages = [p for p in pages if not p.get("factors")]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### ✦ {brand or 'Audit'} ")
    st.caption("SEO & GEO intelligence dashboard · use New Audit above to refresh this report")
    if st.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown("**Export**")

    # Full report JSON
    st.download_button(
        "⬇️ Full report (JSON)",
        data=json.dumps(combined, indent=2, ensure_ascii=False),
        file_name="audit_report.json",
        mime="application/json",
        width="stretch",
    )

    # Branded PDF — built by the pipeline; regenerate on demand from the saved JSON
    # (offline, no API calls). Shows a download once the PDF exists.
    pdf_path = REPORTS_DIR / "latest_report.pdf"
    pdf_name = f"{(brand or 'audit').lower().replace(' ', '_')}_audit_report.pdf"
    if pdf_path.exists():
        st.download_button(
            "⬇️ Download PDF",
            data=pdf_path.read_bytes(),
            file_name=pdf_name,
            mime="application/pdf",
            width="stretch",
        )
    elif st.button("📄 Generate PDF", width="stretch"):
        try:
            from src.reporting.pdf_report import build_pdf
            with st.spinner("Rendering branded PDF…"):
                build_pdf(report_path=report_path, output_path=pdf_path)
            st.rerun()
        except Exception as exc:
            st.error(f"PDF generation failed: {exc}")

    # Pages CSV
    if scored_pages:
        pages_csv = pd.DataFrame(
            [{"url": _fix_mojibake(p.get("url", "")), "score": p.get("score")} for p in scored_pages]
        ).to_csv(index=False)
        st.download_button(
            "⬇️ Pages (CSV)", data=pages_csv, file_name="pages.csv",
            mime="text/csv", width="stretch",
        )

    # Recommendations CSV
    all_recs = seo_recs + geo_recs
    if all_recs:
        recs_csv = pd.DataFrame(
            [
                {
                    "area": r.get("area", ""),
                    "priority": r.get("priority", ""),
                    "title": r.get("title", ""),
                    "scope": r.get("scope", ""),
                    "issue": r.get("issue", ""),
                    "why_it_matters": r.get("why_it_matters", ""),
                    "recommendation": r.get("recommendation", ""),
                }
                for r in all_recs
            ]
        ).to_csv(index=False)
        st.download_button(
            "⬇️ Recommendations (CSV)", data=recs_csv, file_name="recommendations.csv",
            mime="text/csv", width="stretch",
        )

    st.divider()
    st.caption("Read-only on page load. Use New Audit above when you want to run the pipeline.")


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="hero">
        <span class="pill">SEO</span><span class="pill">GEO</span><span class="pill">AI SEARCH AUDIT</span>
        <h1>{escape(brand) or 'SEO &amp; GEO Audit'}</h1>
        <div class="sub">Unified visibility across classic search and generative AI answers · generated {escape(generated)}</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Top Priority Actions
# ---------------------------------------------------------------------------
def _rec_sort_key(r: dict) -> tuple:
    return (_PRIORITY_RANK.get(r.get("priority", ""), 1),)


combined_recs = [{**r, "_area": r.get("area") or "SEO"} for r in seo_recs] + [
    {**r, "_area": r.get("area") or "GEO"} for r in geo_recs
]
top_actions = sorted(combined_recs, key=_rec_sort_key)[:5]

st.markdown("## 🎯 Top Priority Actions")
if top_actions:
    cards = []
    for r in top_actions:
        pr = r.get("priority", "—")
        color = _PRIORITY_COLOR.get(pr, "#64748b")
        cards.append(
            f"""
            <div class="rec" style="border-left-color:{color};">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                    <span class="rtitle">{escape(r.get('title', 'Untitled'))}</span>
                    <span>{_badge_html(pr.upper(), color)} {_badge_html(r.get('_area',''), '#475569', dark_text=False)}</span>
                </div>
                <div class="field">{escape((r.get('recommendation') or r.get('issue') or '')[:240])}</div>
            </div>
            """
        )
    st.markdown("\n".join(cards), unsafe_allow_html=True)
else:
    st.info("No recommendations available yet.")


# ---------------------------------------------------------------------------
# Overall scores — gauges + glass cards
# ---------------------------------------------------------------------------
st.markdown("## Overall Scores")
g1, g2, g3 = st.columns(3)
g1.plotly_chart(_gauge("Unified Score", unified), width="stretch", config={"displayModeBar": False})
g2.plotly_chart(_gauge("SEO Score", seo_score), width="stretch", config={"displayModeBar": False})
g3.plotly_chart(_gauge("GEO Score", geo_score), width="stretch", config={"displayModeBar": False})

# Quick-glance glass cards
measured = [r for r in geo_results if not r.get("error")]
errored = [r for r in geo_results if r.get("error")]
mentioned = sum(1 for r in measured if r.get("brand_mentioned"))
visibility_pct = round(mentioned / len(measured) * 100, 1) if measured else 0.0

st.markdown(
    f"""
    <div class="metric-grid">
        <div class="gcard">
            <div class="label">Pages Scored</div>
            <div class="value">{len(scored_pages)}</div>
            <div class="foot">{len(pages)} page(s) crawled</div>
        </div>
        <div class="gcard">
            <div class="label">Brand Visibility</div>
            <div class="value" style="color:{_band(visibility_pct)};">{visibility_pct}%</div>
            <div class="foot">{mentioned}/{len(measured)} AI answers mention {escape(brand) or 'brand'}</div>
        </div>
        <div class="gcard">
            <div class="label">Queries Measured</div>
            <div class="value">{len(measured)}</div>
            <div class="foot">{len(errored)} returned no answer (excluded)</div>
        </div>
        <div class="gcard">
            <div class="label">Open Recommendations</div>
            <div class="value">{len(seo_recs) + len(geo_recs)}</div>
            <div class="foot">{sum(1 for r in combined_recs if r.get('priority') == 'High')} high priority</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Trends over time — reads timestamped report history only (no API, no scoring)
# ---------------------------------------------------------------------------
def _visibility_from_payload(payload: dict) -> float | None:
    results = (payload.get("geo_report") or {}).get("results") or []
    measured = [r for r in results if not r.get("error")]
    if not measured:
        return None
    mentioned = sum(1 for r in measured if r.get("brand_mentioned"))
    return round(mentioned / len(measured) * 100, 1)


def _subject_sov(payload: dict) -> float | None:
    for s in (payload.get("geo_report") or {}).get("share_of_voice") or []:
        if s.get("is_subject"):
            return round((s.get("share") or 0.0) * 100, 1)
    return None


def _sov_map(payload: dict) -> dict[str, float]:
    return {
        (s.get("brand") or "").strip(): round((s.get("share") or 0.0) * 100, 1)
        for s in (payload.get("geo_report") or {}).get("share_of_voice") or []
    }


def _query_prominence(payload: dict, query: str) -> tuple[bool, float | None]:
    for r in (payload.get("geo_report") or {}).get("results") or []:
        if r.get("query") == query:
            if r.get("error"):
                return (False, None)
            mentioned = bool(r.get("brand_mentioned"))
            prom = None
            if mentioned and r.get("first_position") is not None:
                length = len(r.get("answer") or "")
                if length > 0:
                    prom = round(max(0.0, min((1.0 - r["first_position"] / length) * 100, 100.0)), 1)
            return (mentioned, prom)
    return (False, None)


def _trend_line(title: str, series: list[tuple], ylabel: str = "Score (%)") -> go.Figure:
    fig = go.Figure()
    for name, color, xs, ys in series:
        fig.add_scatter(
            x=xs, y=ys, mode="lines+markers", name=name, connectgaps=True,
            line={"color": color, "width": 3}, marker={"size": 7, "color": color},
        )
    fig.update_layout(
        height=320, title=title, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": INK, "family": "Inter"}, margin=dict(l=10, r=10, t=54, b=10),
        legend={"orientation": "h", "y": 1.16, "x": 0},
        yaxis={"range": [0, 100], "gridcolor": "rgba(255,255,255,0.08)", "title": ylabel},
        xaxis={"gridcolor": "rgba(255,255,255,0.06)"},
    )
    return fig


def _add_noise_bands(fig: go.Figure, xs: list, low_conf: list[bool]) -> None:
    """Shade each interval whose run is same-day/low-confidence (matches the Next.js band)."""
    for i in range(1, len(xs)):
        if low_conf[i]:
            fig.add_vrect(
                x0=xs[i - 1], x1=xs[i], fillcolor=AMBER, opacity=0.10,
                line_width=0, layer="below",
            )


def _render_trends(default_brand: str) -> None:
    from src.reporting import history as _hist
    from src.reporting.trends import low_confidence_flags, min_interval_hours

    st.markdown("## 📈 Trends over time")
    clients = _hist.list_clients()
    if not clients:
        st.info("No saved history yet — run an audit from the **🚀 New Audit** panel to start building trends.")
        return

    default_slug = _hist.slugify(default_brand) if default_brand else None
    idx = clients.index(default_slug) if default_slug in clients else 0
    pick_col, range_col = st.columns([1, 2])
    client = pick_col.selectbox("Client", clients, index=idx, key="trend_client")

    runs = [(ts, p) for ts, p in _hist.load_reports(client) if ts is not None]
    if len(runs) < 2:
        st.info(
            f"📊 Need at least 2 runs to show trends — **{client}** has {len(runs)}. "
            "Run another audit to compare over time."
        )
        return

    d_min, d_max = runs[0][0].date(), runs[-1][0].date()
    rng = range_col.date_input(
        "Date range", value=(d_min, d_max), min_value=d_min, max_value=d_max, key="trend_range"
    )
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        lo, hi = rng
        runs = [(ts, p) for ts, p in runs if lo <= ts.date() <= hi]
    if len(runs) < 2:
        st.info("Need at least 2 runs in the selected date range — widen the range.")
        return

    xs = [ts for ts, _ in runs]
    prev_p, last_p = runs[-2][1], runs[-1][1]
    # Noise guard: flag runs whose gap to the previous run is below the threshold (same-day
    # variance reads as a confident trend otherwise). Shared with the Next.js view.
    _threshold = min_interval_hours()
    low_conf = low_confidence_flags(xs, _threshold)
    _last_same_day = low_conf[-1]

    def _num(payload: dict, key: str) -> float | None:
        v = payload.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    if _last_same_day:
        st.caption(
            f"Change vs earlier today · {runs[-2][0].strftime('%d %b %Y %H:%M UTC')} "
            f"→ {runs[-1][0].strftime('%d %b %Y %H:%M UTC')} — "
            f"⚠️ runs < {_threshold:.0f}h apart; this may reflect run-to-run variance, not a daily trend."
        )
    else:
        st.caption(
            f"Change since previous run · {runs[-2][0].strftime('%d %b %Y %H:%M UTC')} "
            f"→ {runs[-1][0].strftime('%d %b %Y %H:%M UTC')}"
        )
    metrics = [
        ("Unified", _num(last_p, "unified_score"), _num(prev_p, "unified_score")),
        ("SEO", _num(last_p, "seo_score"), _num(prev_p, "seo_score")),
        ("GEO", _num(last_p, "geo_score"), _num(prev_p, "geo_score")),
        ("Brand visibility", _visibility_from_payload(last_p), _visibility_from_payload(prev_p)),
    ]
    cards = []
    for name, cur, prv in metrics:
        cur_s = f"{cur:.1f}%" if cur is not None else "—"
        if cur is not None and prv is not None:
            delta = round(cur - prv, 1)
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "▬")
            dcol = GREEN if delta > 0 else (RED if delta < 0 else "var(--muted)")
            _vs = "vs earlier today" if _last_same_day else "vs prev"
            delta_html = f"<span style='color:{dcol};font-weight:700'>{arrow} {abs(delta):.1f}</span> {_vs}"
        else:
            delta_html = "<span style='color:var(--muted)'>— no prior</span>"
        cards.append(
            f"<div class='gcard'><div class='label'>{escape(name)}</div>"
            f"<div class='value'>{cur_s}</div><div class='foot'>{delta_html}</div></div>"
        )
    st.markdown(f"<div class='metric-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)

    # Score + visibility trends
    _scores_fig = _trend_line("Scores & visibility over time", [
        ("Unified", ACCENT, xs, [_num(p, "unified_score") for _, p in runs]),
        ("SEO", "#38bdf8", xs, [_num(p, "seo_score") for _, p in runs]),
        ("GEO", GREEN, xs, [_num(p, "geo_score") for _, p in runs]),
        ("Brand visibility", AMBER, xs, [_visibility_from_payload(p) for _, p in runs]),
    ])
    _add_noise_bands(_scores_fig, xs, low_conf)
    st.plotly_chart(_scores_fig, width="stretch", config={"displayModeBar": False})
    if any(low_conf):
        st.caption(
            f"⚠️ Shaded bands mark runs < {_threshold:.0f}h apart (same-day) — treat those "
            "segments as low-confidence (run-to-run variance), not a real trend."
        )

    # Share-of-Voice trend: subject + top 3 competitors (ranked by the latest run)
    if any(_subject_sov(p) is not None for _, p in runs):
        last_sov = (last_p.get("geo_report") or {}).get("share_of_voice") or []
        subject_name = next((s.get("brand") for s in last_sov if s.get("is_subject")), default_brand or "You")
        top_comps = [
            s.get("brand") for s in sorted(last_sov, key=lambda s: -(s.get("share") or 0.0))
            if not s.get("is_subject")
        ][:3]
        sov_maps = [_sov_map(p) for _, p in runs]
        series = [(f"{subject_name} (you)", ACCENT, xs, [_subject_sov(p) for _, p in runs])]
        palette = ["#38bdf8", AMBER, RED]
        for i, comp in enumerate(top_comps):
            series.append((comp, palette[i % len(palette)], xs, [m.get(comp) for m in sov_maps]))
        _sov_fig = _trend_line("Share of Voice over time (you vs top competitors)", series, ylabel="Share of Voice (%)")
        _add_noise_bands(_sov_fig, xs, low_conf)
        st.plotly_chart(_sov_fig, width="stretch", config={"displayModeBar": False})
    else:
        st.caption("Share-of-Voice trend unavailable — this client's history predates SoV capture.")

    # Optional per-query drill-down
    all_queries: list[str] = []
    for _, p in runs:
        for r in (p.get("geo_report") or {}).get("results") or []:
            q = r.get("query")
            if q and q not in all_queries:
                all_queries.append(q)
    if all_queries:
        with st.expander("🔎 Per-query drill-down"):
            q = st.selectbox("Target query", all_queries, key="trend_query")
            proms, states = [], []
            for _, p in runs:
                mentioned, prom = _query_prominence(p, q)
                proms.append(prom)
                states.append("mentioned" if mentioned else "absent")
            figq = go.Figure()
            figq.add_scatter(
                x=xs, y=proms, mode="lines+markers", name="Prominence", connectgaps=True,
                line={"color": ACCENT, "width": 3},
                marker={"size": 10, "color": [GREEN if s == "mentioned" else RED for s in states]},
                text=states, hovertemplate="%{x|%d %b %Y}<br>%{text} · prominence %{y:.1f}%<extra></extra>",
            )
            figq.update_layout(
                height=300, title=f"“{q[:60]}” — prominence & mention across runs",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font={"color": INK, "family": "Inter"}, margin=dict(l=10, r=10, t=50, b=10),
                yaxis={"range": [0, 100], "gridcolor": "rgba(255,255,255,0.08)", "title": "Prominence (%)"},
                xaxis={"gridcolor": "rgba(255,255,255,0.06)"},
            )
            _add_noise_bands(figq, xs, low_conf)
            st.plotly_chart(figq, width="stretch", config={"displayModeBar": False})
            st.caption(
                "Green marker = brand mentioned that run; red = absent. Gaps mean the query "
                "wasn't in that run. Shaded bands = same-day / low-confidence runs."
            )


_render_trends(brand)


# ---------------------------------------------------------------------------
# SEO Breakdown
# ---------------------------------------------------------------------------
st.markdown("## 🔍 SEO Breakdown")

if scored_pages:
    # ---- Factor-level breakdown: pass/warn/fail counts per factor ----
    factor_ids: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for p in scored_pages:
        for f in p.get("factors", []):
            fid = f.get("id", "?")
            if fid not in counts:
                counts[fid] = {"pass": 0, "warn": 0, "fail": 0}
                factor_ids.append(fid)
            status = f.get("status", "")
            if status in counts[fid]:
                counts[fid][status] += 1

    if factor_ids:
        labels = [_factor_label(fid) for fid in factor_ids]
        fig = go.Figure()
        for status, color in (("pass", GREEN), ("warn", AMBER), ("fail", RED)):
            fig.add_bar(
                name=status.capitalize(),
                x=labels,
                y=[counts[fid][status] for fid in factor_ids],
                marker_color=color,
                hovertemplate="%{x}<br>" + status + ": %{y} page(s)<extra></extra>",
            )
        fig.update_layout(
            barmode="stack",
            height=360,
            title="On-page factors across pages (pass / warn / fail)",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": INK, "family": "Inter"},
            legend={"orientation": "h", "y": 1.12, "x": 0},
            margin=dict(l=10, r=10, t=70, b=10),
            yaxis={"gridcolor": "rgba(255,255,255,0.08)", "title": "Pages"},
            xaxis={"tickangle": -20},
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ---- Filter / sort controls + per-page table ----
    st.markdown("#### Per-page scores")
    fc1, fc2, fc3 = st.columns([2, 1, 1])
    query = fc1.text_input("Filter by URL", placeholder="e.g. /help", key="seo_url_filter")
    rating_filter = fc2.selectbox("Rating", ["All", "🟢 ≥80", "🟡 50–79", "🔴 <50"], key="seo_rating_filter")
    sort_by = fc3.selectbox("Sort by", ["Score ↓", "Score ↑", "URL A–Z"], key="seo_sort")

    rows = [
        {"url": _fix_mojibake(p.get("url", "")), "score": float(p.get("score") or 0.0)}
        for p in scored_pages
    ]
    if query:
        rows = [r for r in rows if query.lower() in r["url"].lower()]
    if rating_filter == "🟢 ≥80":
        rows = [r for r in rows if r["score"] >= 80]
    elif rating_filter == "🟡 50–79":
        rows = [r for r in rows if 50 <= r["score"] < 80]
    elif rating_filter == "🔴 <50":
        rows = [r for r in rows if r["score"] < 50]

    if sort_by == "Score ↓":
        rows.sort(key=lambda r: r["score"], reverse=True)
    elif sort_by == "Score ↑":
        rows.sort(key=lambda r: r["score"])
    else:
        rows.sort(key=lambda r: r["url"].lower())

    for r in rows:
        r["rating"] = _rating_dot(r["score"])

    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["rating", "url", "score"]],
            column_config={
                "rating": st.column_config.TextColumn("●", width="small"),
                "url": st.column_config.LinkColumn("Page URL"),
                "score": st.column_config.ProgressColumn(
                    "Score (%)", min_value=0, max_value=100, format="%.1f%%"
                ),
            },
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No pages match the current filters.")

    # ---- Per-page expander: factor-by-factor ----
    st.markdown("#### Factor-by-factor detail")
    for p in sorted(scored_pages, key=lambda p: float(p.get("score") or 0.0)):
        url = _fix_mojibake(p.get("url", ""))
        score = float(p.get("score") or 0.0)
        with st.expander(f"{_rating_dot(score)}  {url}  —  {score:.1f}%"):
            for f in p.get("factors", []):
                status = f.get("status", "")
                color = _STATUS_COLOR.get(status, "#64748b")
                st.markdown(
                    f"<div class='field'><b style='color:{color}'>"
                    f"{_STATUS_LABEL.get(status, status)}</b> · "
                    f"<b>{escape(_factor_label(f.get('id', '?')))}</b> — "
                    f"{escape(str(f.get('message', '')))}</div>",
                    unsafe_allow_html=True,
                )

    if skipped_pages:
        st.caption(f"{len(skipped_pages)} crawled page(s) were not scoreable.")
else:
    if skipped_pages:
        st.info(
            "The audit ran, but no scoreable SEO pages were returned for this site. "
            "Try a different domain path or run New Audit again later."
        )
    else:
        st.info("No SEO page data is stored in this report yet — run **New Audit** from the sidebar.")


# ---------------------------------------------------------------------------
# GEO Report
# ---------------------------------------------------------------------------
st.markdown("## 🤖 GEO Report")
audit_settings = combined.get("audit_settings") or {}
if audit_settings.get("geo_provider") or audit_settings.get("geo_model"):
    st.caption(
        "Measured using: "
        f"**{audit_settings.get('geo_provider', '')} / {audit_settings.get('geo_model', '')}** "
        f"(API key: {audit_settings.get('api_key_source', 'env')})"
    )

# AI engine / model breakdown — brand visibility differs across ChatGPT, Claude,
# Perplexity, etc. Each enabled engine is scored separately; overall = their average.
engine_scores = geo.get("engine_scores") or []
if engine_scores:
    st.markdown("#### AI Engine / Model GEO Breakdown")

    def _key_label(src: str) -> str:
        return {"env": "saved", "temporary": "temporary", "none": "none"}.get(src, src or "none")

    # Group rows by provider so multiple sub-models read together.
    _sorted = sorted(engine_scores, key=lambda e: (e.get("provider", ""), e.get("model", "")))
    breakdown_rows = [
        {
            "Provider": e.get("provider", ""),
            "Model": e.get("model", ""),
            "Grounding": "🌐 Live search" if e.get("web_grounded") else "⚠ Model knowledge",
            "Sources": int(e.get("sources_count") or 0),
            "GEO score": float(e.get("geo_score") or 0.0),
            "Visibility": round((e.get("visibility_rate") or 0.0) * 100, 1),
            "Queries run": int(e.get("queries_run") or 0),
            "API key": _key_label(e.get("api_key_source", "none")),
        }
        for e in _sorted
    ]
    st.dataframe(
        pd.DataFrame(breakdown_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "GEO score": st.column_config.NumberColumn("GEO score", format="%.1f%%"),
            "Visibility": st.column_config.NumberColumn("Visibility", format="%.1f%%"),
        },
    )
    grounded = [e for e in engine_scores if not e.get("error") and e.get("queries_run") and e.get("web_grounded")]
    ungrounded = [e for e in engine_scores if not e.get("error") and e.get("queries_run") and not e.get("web_grounded")]
    st.caption(
        f"Headline GEO score = average of {len(grounded)} live-grounded engine(s). "
        "🌐 = live web search · ⚠ = model knowledge only."
    )
    if ungrounded:
        names = ", ".join(f"{e.get('provider')}/{e.get('model')}" for e in ungrounded)
        st.caption(f"Excluded from the headline (ungrounded): {names}.")
    for e in (e for e in engine_scores if e.get("grounding_warning")):
        st.caption(f"⚠️ {e.get('provider')}/{e.get('model')}: {e.get('grounding_warning')}")
    for e in (e for e in engine_scores if e.get("error")):
        st.caption(f"⚠️ {e.get('provider')}/{e.get('model')} not run: {e.get('error')}")

# GEO Quality Signals — beyond "is the brand mentioned": HOW it's mentioned.
# Per engine, with EXPLICIT denominators so the numbers can't be misread:
#   • sentiment / recommendation / brand rank → over brand-mention answers ONLY
#     (N/A when the brand isn't mentioned — never a misleading number).
#   • citation coverage / competitor mentions → across ALL answers (so labelled).
# When the brand scores 0%, the section pivots to "who DID win these answers".
def _legacy_quality_block(rows: list[dict]) -> dict:
    """Build a quality block from old per-query rows (no stored `quality`).

    Competitor names weren't ranked in old reports, so top_competitors/leaders are
    empty — the rest (denominators, SoV, sentiment) renders identically.
    """
    n_all = len(rows)
    men = [r for r in rows if r.get("brand_mentioned")]
    sents = [float(r.get("sentiment_score") or 0.0) for r in men]
    recs = [float(r.get("recommendation_score") or 0.0) for r in men]
    ranks = [r.get("brand_rank_position") for r in men if r.get("brand_rank_position")]
    cites = sum(1 for r in rows if r.get("citations_present"))
    return {
        "answers_total": n_all,
        "brand_mentions": len(men),
        "sov": round(len(men) / n_all, 4) if n_all else 0.0,
        "sentiment": {
            "avg": round(sum(sents) / len(sents), 3) if sents else None,
            "positive": sum(1 for r in men if r.get("sentiment_label") == "positive"),
            "neutral": sum(1 for r in men if r.get("sentiment_label") == "neutral"),
            "negative": sum(1 for r in men if r.get("sentiment_label") == "negative"),
        },
        "recommendation": {"avg": round(sum(recs) / len(recs), 3) if recs else None},
        "avg_brand_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "citations_answers": cites,
        "citation_coverage": round(cites / n_all, 4) if n_all else 0.0,
        "competitor_total": sum(int(r.get("competitor_count") or 0) for r in rows),
        "top_competitors": [],
        "competitor_leaders": [],
    }


def _render_quality_block(q: dict, label: str | None = None) -> None:
    n_all = int(q.get("answers_total") or 0)
    n_men = int(q.get("brand_mentions") or 0)
    if label:
        st.markdown(f"**{label}**")
    st.caption(
        f"Share of Voice: **{(q.get('sov') or 0.0) * 100:.0f}%** — "
        f"brand mentioned in {n_men} of {n_all} answers."
    )

    sent = q.get("sentiment") or {}
    rec = q.get("recommendation") or {}
    avg_sent = sent.get("avg")
    avg_rec = rec.get("avg")
    avg_rank = q.get("avg_brand_rank")
    cite_cov = (q.get("citation_coverage") or 0.0) * 100

    qc = st.columns(5)
    if n_men:
        qc[0].metric("Avg sentiment", f"{avg_sent:+.2f}" if avg_sent is not None else "N/A")
        qc[1].metric("Avg recommendation", f"{avg_rec * 100:.0f}%" if avg_rec is not None else "N/A")
        qc[4].metric("Avg brand rank", f"#{avg_rank:.1f}" if avg_rank is not None else "N/A")
    else:
        qc[0].metric("Avg sentiment", "N/A", help="Brand not mentioned in any answer")
        qc[1].metric("Avg recommendation", "N/A", help="Brand not mentioned in any answer")
        qc[4].metric("Avg brand rank", "N/A", help="Brand not mentioned in any answer")
    # These two are ALWAYS across all answers — labelled so they aren't read as brand-specific.
    qc[2].metric("Citation coverage", f"{cite_cov:.0f}%", help=f"Across all {n_all} answers")
    qc[3].metric("Competitor mentions", int(q.get("competitor_total") or 0), help=f"Across all {n_all} answers")

    if n_men:
        st.caption(
            f"Sentiment of {n_men} brand mention(s): "
            f"🟢 {sent.get('positive', 0)} positive · ⚪ {sent.get('neutral', 0)} neutral · "
            f"🔴 {sent.get('negative', 0)} negative."
        )
    else:
        st.caption(f"🔴 **N/A — brand not mentioned** in any of the {n_all} answers for this engine.")

    # Ranked competitor breakdown (not just a total).
    top = q.get("top_competitors") or []
    if top:
        st.caption(f"Top competitors across all {n_all} answers (by # answers mentioning):")
        st.dataframe(
            pd.DataFrame([{"Competitor": c.get("name", ""), "Answers": int(c.get("count") or 0)} for c in top]),
            width="stretch", hide_index=True,
        )

    # Zero-visibility pivot: show what winning answers look like.
    leaders = q.get("competitor_leaders") or []
    if n_men == 0 and leaders:
        st.caption("Brand absent — here's **who won these answers and how strongly**:")
        st.dataframe(
            pd.DataFrame([
                {
                    "Competitor": d.get("name", ""),
                    "Mentions": int(d.get("mentions") or 0),
                    "Sentiment": d.get("sentiment_label", "—"),
                    "Recommendation": d.get("recommendation_strength", "—"),
                    "Best rank": f"#{d['rank']}" if d.get("rank") else "—",
                }
                for d in leaders
            ]),
            width="stretch", hide_index=True,
        )


_q_engines = [e for e in engine_scores if e.get("quality")]
_quality_rows = [r for r in measured if r.get("per_query_geo_score") is not None]
if _q_engines:
    st.markdown("#### GEO Quality Signals")
    st.caption(
        "Brand-mention metrics (sentiment · recommendation · rank) are over answers that "
        "**mention the brand**; citation coverage and competitor mentions are over **all answers**."
    )
    _multi = len(_q_engines) > 1
    for e in sorted(_q_engines, key=lambda x: (x.get("provider", ""), x.get("model", ""))):
        lbl = f"{e.get('provider', '')} / {e.get('model', '')}" if _multi else None
        _render_quality_block(e["quality"], lbl)
elif _quality_rows:  # backward compat: old report without a stored quality block
    st.markdown("#### GEO Quality Signals")
    _render_quality_block(_legacy_quality_block(_quality_rows))

if geo_results:
    gcol1, gcol2 = st.columns([1, 2])

    # Brand visibility donut
    with gcol1:
        donut = go.Figure(
            go.Pie(
                values=[mentioned, max(len(measured) - mentioned, 0)],
                labels=["Mentioned", "Absent"],
                hole=0.68,
                marker_colors=[_band(visibility_pct), "rgba(255,255,255,0.10)"],
                textinfo="none",
                sort=False,
            )
        )
        donut.update_layout(
            height=300,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=40, b=10),
            title="Brand visibility",
            font={"color": INK, "family": "Inter"},
            annotations=[
                dict(text=f"<b>{visibility_pct}%</b>", x=0.5, y=0.55, font_size=30, showarrow=False, font_color=INK),
                dict(text=f"{mentioned}/{len(measured)} answers", x=0.5, y=0.40, font_size=12, showarrow=False, font_color="#9aa3b8"),
            ],
        )
        st.plotly_chart(donut, width="stretch", config={"displayModeBar": False})

    # Prominence per query bar
    with gcol2:
        qnames, qvals, qcolors = [], [], []
        for r in measured:
            qnames.append((r.get("query") or "")[:48])
            if r.get("brand_mentioned"):
                p = _prominence(r)
                qvals.append(p if p is not None else 0.0)
                qcolors.append(_band(p if p is not None else 0.0))
            else:
                qvals.append(0.0)
                qcolors.append("rgba(255,255,255,0.10)")
        bar = go.Figure(
            go.Bar(
                x=qvals, y=qnames, orientation="h", marker_color=qcolors,
                hovertemplate="%{y}<br>Prominence: %{x:.1f}%<extra></extra>",
            )
        )
        bar.update_layout(
            height=300,
            title="Prominence per query",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": INK, "family": "Inter"},
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis={"range": [0, 100], "gridcolor": "rgba(255,255,255,0.08)", "title": "Prominence (%)"},
            yaxis={"autorange": "reversed"},
        )
        st.plotly_chart(bar, width="stretch", config={"displayModeBar": False})

    if errored:
        st.warning(
            "No answer returned (excluded from scoring): "
            + "; ".join(r.get("query", "") for r in errored)
        )

    # Share of Voice — ranked brands (subject + competitors) by presence across answers
    sov = geo.get("share_of_voice") or []
    sov_head = (geo.get("sov_headline") or "").strip()
    if sov:
        st.markdown("#### Share of Voice")
        if sov_head:
            st.markdown(
                f"<div class='rec' style='border-left-color:{ACCENT};'>🏆 <b>{escape(sov_head)}</b></div>",
                unsafe_allow_html=True,
            )
        TOPN = 15
        shown = list(sov[:TOPN])
        if not any(s.get("is_subject") for s in shown):
            subj = next((s for s in sov if s.get("is_subject")), None)
            if subj:
                shown.append(subj)
        names = [s.get("brand", "") for s in shown]
        shares = [round((s.get("share") or 0.0) * 100, 1) for s in shown]
        colors = [ACCENT if s.get("is_subject") else "#475569" for s in shown]
        sov_fig = go.Figure(
            go.Bar(
                x=shares, y=names, orientation="h", marker_color=colors,
                text=[f"{v:.0f}%" for v in shares], textposition="auto",
                hovertemplate="%{y}: %{x:.1f}% of answers<extra></extra>",
            )
        )
        sov_fig.update_layout(
            height=max(300, 26 * len(shown)),
            title="Brands ranked by Share of Voice (presence across AI answers)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font={"color": INK, "family": "Inter"},
            margin=dict(l=10, r=10, t=48, b=10),
            xaxis={"range": [0, 100], "gridcolor": "rgba(255,255,255,0.08)", "title": "Share of measured queries (%)"},
            yaxis={"autorange": "reversed"},
        )
        st.plotly_chart(sov_fig, width="stretch", config={"displayModeBar": False})
        st.caption(f"{escape((brand or 'Subject'))} highlighted. Share = queries where the brand appears ÷ measured queries.")

    # Per-query expander: answer excerpt + competitors
    st.markdown("#### Query-by-query detail")
    for r in measured:
        q = r.get("query", "")
        hit = bool(r.get("brand_mentioned"))
        icon = "✅" if hit else "❌"
        prom = _prominence(r)
        prom_txt = f" · prominence {prom:.1f}%" if prom is not None else ""
        pm = "/".join(p for p in [r.get("provider"), r.get("model")] if p)
        pm_label = f"  ·  `{pm}`" if pm else ""
        # Region badge: which locale grounded this query's search (missing → Global).
        _loc = str(r.get("locale_applied") or "global")
        loc_badge = "🌍 Global" if _loc == "global" else f"🌍 {_loc}"
        with st.expander(f"{icon}  {q} · {loc_badge}{prom_txt}{pm_label}"):
            mc = r.get("mention_count")
            fp = r.get("first_position")
            meta_bits = []
            if pm:
                meta_bits.append(f"Engine: **{pm}**")
            _method = str(r.get("locale_method") or "none")
            meta_bits.append(
                f"Region: **{'Global' if _loc == 'global' else _loc}**"
                + (f" ({_method})" if _method != "none" else "")
            )
            meta_bits.append(f"Brand mentioned: **{'yes' if hit else 'no'}**")
            if mc is not None:
                meta_bits.append(f"Mentions: **{mc}**")
            if fp is not None:
                meta_bits.append(f"First position: **{fp}**")
            st.markdown(" · ".join(meta_bits))

            # GEO quality signals (defaults keep older reports rendering cleanly).
            if r.get("per_query_geo_score") is not None or r.get("sentiment_label", "unknown") != "unknown":
                rank = r.get("brand_rank_position")
                pqs = r.get("per_query_geo_score")
                quality_bits = [
                    f"Sentiment: **{r.get('sentiment_label', 'unknown')}**",
                    f"Recommendation: **{r.get('recommendation_strength', 'unknown')}**",
                    f"Brand rank: **{('#' + str(rank)) if rank else 'N/A'}**",
                    f"Citations: **{'yes' if r.get('citations_present') else 'no'}**",
                    f"Quality score: **{pqs:.1f}%**" if pqs is not None else "Quality score: **N/A**",
                ]
                st.markdown(" · ".join(quality_bits))

            comps = r.get("competitors_found") or []
            if comps:
                chips = " ".join(
                    f"<span class='pill'>{escape(str(c))}</span>" for c in comps
                )
                st.markdown(f"**Competitor brands in answer:** {chips}", unsafe_allow_html=True)
            else:
                st.caption("No competitor brands detected in this answer.")

            answer = (r.get("answer") or "").strip()
            if answer:
                excerpt = answer[:900] + ("…" if len(answer) > 900 else "")
                st.markdown("**AI answer excerpt:**")
                st.markdown(
                    f"<div class='rec' style='border-left-color:{ACCENT};white-space:pre-wrap;'>"
                    f"{escape(excerpt)}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No answer text recorded.")
else:
    st.info("No GEO query results are stored in this report yet — run **New Audit** from the sidebar.")


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
def _render_recs(recs: list[dict], key_prefix: str) -> None:
    if not recs:
        st.info("No recommendations are stored in this report yet — run **New Audit** from the sidebar.")
        return

    fc1, fc2 = st.columns([1, 1])
    pr_filter = fc1.selectbox(
        "Priority", ["All", "High", "Medium", "Low"], key=f"{key_prefix}_rec_pri"
    )
    sort_mode = fc2.selectbox(
        "Sort", ["Priority (High→Low)", "Title A–Z"], key=f"{key_prefix}_rec_sort"
    )

    items = list(recs)
    if pr_filter != "All":
        items = [r for r in items if r.get("priority") == pr_filter]
    if sort_mode == "Priority (High→Low)":
        items.sort(key=lambda r: _PRIORITY_RANK.get(r.get("priority", ""), 1))
    else:
        items.sort(key=lambda r: (r.get("title") or "").lower())

    if not items:
        st.caption("No recommendations match the current filters.")
        return

    for i, r in enumerate(items):
        pr = r.get("priority", "—")
        color = _PRIORITY_COLOR.get(pr, "#64748b")
        draft = (r.get("draft") or "").strip()
        with st.container(border=True):
            h1, h2 = st.columns([0.82, 0.18], vertical_alignment="center")
            h1.markdown(f"#### {r.get('title', 'Untitled')}")
            h2.markdown(
                f"<div style='text-align:right'>{_badge_html(str(pr).upper(), color)}</div>",
                unsafe_allow_html=True,
            )
            if r.get("scope"):
                st.caption(str(r.get("scope")))
            st.markdown("**Issue**")
            st.write(r.get("issue") or "No issue text stored for this recommendation.")
            st.markdown("**Why it matters**")
            st.write(r.get("why_it_matters") or "No rationale stored for this recommendation.")
            st.markdown("**Recommendation**")
            st.write(r.get("recommendation") or "No recommendation text stored for this item.")
            if draft:
                with st.expander("Draft fix"):
                    _render_draft(draft)
                    _copy_button(draft, key=f"{key_prefix}_{i}")


st.markdown("## 🛠 SEO Recommendations")
_render_recs(seo_recs, "seo")

st.markdown("## 🛠 GEO Recommendations")
geo_assessment = (combined.get("geo_assessment") or "").strip()
if geo_assessment:
    st.markdown(
        f"<div class='rec' style='border-left-color:{ACCENT};'>{escape(geo_assessment)}</div>",
        unsafe_allow_html=True,
    )
_render_recs(geo_recs, "geo")
