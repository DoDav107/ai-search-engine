"""Streamlit dashboard for visualising SEO/GEO audit reports. Read-only."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

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
st.set_page_config(page_title="Eloize SEO/GEO Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Project imports — after sys.path is set
# ---------------------------------------------------------------------------
from src.engine.models import Recommendation  # noqa: E402
from src.agents.drafting_agent import draft_fixes  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_STATUS_EMOJI: dict[str, str] = {
    "pass": "✅ pass",
    "warn": "⚠️ warn",
    "fail": "❌ fail",
}
_SEVERITY_COLOR: dict[str, str] = {"fail": "red", "warn": "orange"}


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------

def _latest(pattern: str) -> Path | None:
    """Return the newest file matching pattern in REPORTS_DIR, or None."""
    files = list(REPORTS_DIR.glob(pattern))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _fix_mojibake(text: str) -> str:
    """Fix text where UTF-8 bytes were decoded as Latin-1 (e.g. â€" → —).

    Re-encodes as Latin-1 bytes then decodes as UTF-8. Returns original on any failure.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _score_rating(score: float) -> str:
    """Return a colour-coded circle for the score band (🟢 ≥80, 🟡 50–79, 🔴 <50)."""
    if score >= 80:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


def _report_caption(path: Path) -> str:
    """Format a human-readable caption from a report filename timestamp."""
    ts_raw = path.stem.rsplit("_", 1)[-1]  # e.g. "20260611T124143Z"
    try:
        dt = datetime.strptime(ts_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        ts_str = dt.strftime("%d %b %Y %H:%M UTC")
    except ValueError:
        mtime = path.stat().st_mtime
        ts_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return f"Showing: `{path.name}` — generated {ts_str}"


@st.cache_data
def _load_json(path_str: str, _mtime: float) -> Any:
    """Parse JSON from path_str; cache key includes mtime so regenerated files invalidate it."""
    with open(path_str, encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def _draft_fixes_cached(path_str: str, _mtime: float) -> list[dict]:
    """Load recommendations and generate draft fixes via MockEngineClient (no API calls)."""
    with open(path_str, encoding="utf-8") as fh:
        recs_data = json.load(fh)

    recommendations = [
        Recommendation(
            factor=r["factor"],
            severity=r["severity"],
            message=r["message"],
            affected_urls=r["affected_urls"],
            scope=r["scope"],
            priority=r["priority"],
        )
        for r in recs_data
    ]
    fixes = draft_fixes(recommendations, {"engine": "mock"})
    return [
        {
            "factor": df.recommendation.factor,
            "severity": df.recommendation.severity,
            "message": df.recommendation.message,
            "affected_urls": df.recommendation.affected_urls,
            "scope": df.recommendation.scope,
            "draft": df.draft,
            "status": df.status,
        }
        for df in fixes
    ]


def _render_draft(draft: str) -> None:
    """Render JSON-LD with st.code; everything else (lists, plain text) with st.markdown."""
    if draft.strip().startswith("{"):
        st.code(draft, language="json")
    else:
        st.markdown(draft)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Eloize Dashboard")
    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Reads `data/reports/` — run `python -m src.pipeline` to update.")


# ---------------------------------------------------------------------------
# Report discovery
# ---------------------------------------------------------------------------
combined_path = _latest("combined_report_*.json")
recs_path = _latest("recommendations_*.json")

if combined_path is None and recs_path is None:
    st.warning(
        "No reports found in `data/reports/`. Generate them by running:\n\n"
        "```\npython -m src.pipeline\npython -m src.engine.recommendations\n```"
    )
    st.stop()

combined: dict | None = (
    _load_json(str(combined_path), combined_path.stat().st_mtime) if combined_path else None
)


# ---------------------------------------------------------------------------
# Page title and report freshness caption
# ---------------------------------------------------------------------------
st.title("Eloize — SEO & GEO Audit")
if combined_path:
    st.caption(_report_caption(combined_path))


# ---------------------------------------------------------------------------
# 1. Unified score
# ---------------------------------------------------------------------------
st.header("Overall Scores")

if combined:
    c1, c2, c3 = st.columns(3)
    c1.metric("Unified Score", f"{combined['unified_score']}%", border=True)
    c2.metric("SEO Score", f"{combined['seo_score']}%", border=True)
    c3.metric("GEO Score", f"{combined['geo_score']}%", border=True)
else:
    st.info("No combined report found — run `python -m src.pipeline`.")


# ---------------------------------------------------------------------------
# 2. SEO breakdown
# ---------------------------------------------------------------------------
st.header("SEO Breakdown")

if combined and "seo_report" in combined:
    seo = combined["seo_report"]
    pages = seo.get("pages", [])

    # Pages with factor results were successfully crawled and scored
    scored_pages = [p for p in pages if p.get("factors")]
    skipped_pages = [p for p in pages if not p.get("factors")]

    page_rows = [
        {
            "url": _fix_mojibake(p["url"]),
            "score": p["score"],
            "rating": _score_rating(p["score"]),
        }
        for p in scored_pages
    ]
    if page_rows:
        st.dataframe(
            pd.DataFrame(page_rows),
            column_config={
                "url": st.column_config.LinkColumn("Page URL"),
                "score": st.column_config.ProgressColumn(
                    "Score (%)", min_value=0, max_value=100, format="%.1f%%"
                ),
                "rating": st.column_config.TextColumn("Rating"),
            },
            width="stretch",
            hide_index=True,
        )

    if skipped_pages:
        urls_str = "; ".join(_fix_mojibake(p["url"]) for p in skipped_pages)
        st.caption(f"{len(skipped_pages)} page(s) not scored (no factor data): {urls_str}")

    factor_rows = [
        {
            "url": _fix_mojibake(page["url"]),
            "factor": factor["id"],
            "status": _STATUS_EMOJI.get(factor["status"], factor["status"]),
            "message": factor["message"],
        }
        for page in scored_pages
        for factor in page.get("factors", [])
    ]
    if factor_rows:
        st.subheader("Factor Detail")
        st.dataframe(pd.DataFrame(factor_rows), width="stretch", hide_index=True)
else:
    st.info("No SEO data available — run `python -m src.pipeline`.")


# ---------------------------------------------------------------------------
# 3. GEO report
# ---------------------------------------------------------------------------
st.header("GEO Report")

if combined and "geo_report" in combined:
    geo = combined["geo_report"]
    results = geo.get("results", [])

    mentioned = sum(1 for r in results if r.get("brand_mentioned"))
    visibility_pct = round(mentioned / len(results) * 100, 1) if results else 0.0
    g1, g2 = st.columns(2)
    g1.metric("Brand Visibility", f"{visibility_pct}%", border=True)
    g2.metric("GEO Score", f"{geo.get('geo_score', 0.0)}%", border=True)

    def _prominence(r: dict) -> float | None:
        if not r.get("brand_mentioned") or r.get("first_position") is None:
            return None
        ans_len = len(r.get("answer") or "")
        return round((1.0 - r["first_position"] / ans_len) * 100, 1) if ans_len > 0 else None

    query_rows = [
        {
            "query": r["query"],
            "brand_mentioned": bool(r.get("brand_mentioned")),
            "prominence": _prominence(r),
        }
        for r in results
    ]
    if query_rows:
        st.dataframe(
            pd.DataFrame(query_rows),
            column_config={
                "query": st.column_config.TextColumn("Query"),
                "brand_mentioned": st.column_config.CheckboxColumn("Brand Mentioned"),
                "prominence": st.column_config.ProgressColumn(
                    "Prominence (%)", min_value=0, max_value=100
                ),
            },
            width="stretch",
            hide_index=True,
        )
else:
    st.info("No GEO data available — run `python -m src.pipeline`.")


# ---------------------------------------------------------------------------
# 4. Recommendations with draft fixes
# ---------------------------------------------------------------------------
st.header("Recommendations")

if recs_path:
    drafted = _draft_fixes_cached(str(recs_path), recs_path.stat().st_mtime)
    for item in drafted:
        sev = item["severity"]
        with st.expander(f"{item['factor']} — {sev}"):
            st.badge(sev.upper(), color=_SEVERITY_COLOR.get(sev, "gray"))
            st.badge("Pending review", color="orange")
            st.markdown(f"**Scope:** {item['scope']} — {len(item['affected_urls'])} page(s)")
            st.markdown(f"**Issue:** {item['message']}")
            st.markdown("**Draft fix:**")
            _render_draft(item["draft"])
else:
    st.info("No recommendations found — run `python -m src.engine.recommendations`.")
