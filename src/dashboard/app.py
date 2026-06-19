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
# This dashboard is strictly read-only: it renders the report produced by
# `python -m src.pipeline` and never runs drafting or makes live API calls.
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
# Report discovery — single source of truth produced by the pipeline
# ---------------------------------------------------------------------------
report_path = REPORTS_DIR / "latest_report.json"

if not report_path.exists():
    st.info("No report yet — run `python -m src.pipeline` to generate one.")
    st.stop()

combined: dict = _load_json(str(report_path), report_path.stat().st_mtime)


# ---------------------------------------------------------------------------
# Page title and report freshness caption
# ---------------------------------------------------------------------------
st.title("Eloize — SEO & GEO Audit")
st.caption(_report_caption(report_path))


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

recommendations = combined.get("recommendations", [])
if recommendations:
    for item in recommendations:
        rec = item.get("recommendation", {})
        sev = rec.get("severity", "")
        with st.expander(f"{rec.get('factor', '')} — {sev}"):
            st.badge(sev.upper(), color=_SEVERITY_COLOR.get(sev, "gray"))
            status = item.get("status", "pending_review")
            st.badge(status.replace("_", " ").title(), color="orange")
            st.markdown(f"**Scope:** {rec.get('scope', '')} — {len(rec.get('affected_urls', []))} page(s)")
            st.markdown(f"**Issue:** {rec.get('message', '')}")
            st.markdown("**Draft fix:**")
            _render_draft(item.get("draft", ""))
else:
    st.info("No recommendations in the report — run `python -m src.pipeline`.")
