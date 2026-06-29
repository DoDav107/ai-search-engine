"""Branded PDF export of the saved SEO/GEO audit report.

Single source of truth for the client-ready PDF used by BOTH dashboards. Reads
``data/reports/latest_report.json`` (never makes live API calls) and renders a
branded, multi-section PDF via an HTML/CSS template → Chromium (Playwright) for
full CSS fidelity. Re-runnable standalone (``python -m src.reporting.pdf_report``)
and called by the pipeline after the report JSON is saved.
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "data" / "reports"
DEFAULT_REPORT = REPORTS_DIR / "latest_report.json"
DEFAULT_OUTPUT = REPORTS_DIR / "latest_report.pdf"
GEO_CONFIG = REPO_ROOT / "config" / "geo_config.yaml"

# ---------------------------------------------------------------------------
# Palette — mirrors the dashboards (accent + rating bands)
# ---------------------------------------------------------------------------
ACCENT = "#7c5cff"
GREEN = "#16a34a"
AMBER = "#d97706"
RED = "#dc2626"
INK = "#0f1424"
MUTED = "#5b6478"

_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
_PRIORITY_COLOR = {"High": RED, "Medium": AMBER, "Low": "#64748b"}
_STATUS_COLOR = {"pass": GREEN, "warn": AMBER, "fail": RED}
_FACTOR_LABEL = {
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
# Small display helpers (display-only — never change scoring/prominence math)
# ---------------------------------------------------------------------------
def _band(score: float) -> tuple[str, str]:
    """Return (color, label) for a 0–100 score — same thresholds as the dashboards."""
    if score >= 80:
        return GREEN, "Strong"
    if score >= 50:
        return AMBER, "Needs work"
    return RED, "Critical"


def _factor_label(fid: str) -> str:
    return _FACTOR_LABEL.get(fid, fid.replace("_", " ").title())


def _prominence(r: dict) -> float | None:
    """Display-only prominence (0–100). Mirrors the dashboards; no rescoring."""
    if not r.get("brand_mentioned") or r.get("first_position") is None:
        return None
    ans_len = len(r.get("answer") or "")
    if ans_len <= 0:
        return None
    pct = (1.0 - r["first_position"] / ans_len) * 100
    return round(max(0.0, min(pct, 100.0)), 1)


def _fix_mojibake(text: str) -> str:
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return text


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


def _e(text: Any) -> str:
    return escape(str(text if text is not None else ""))


def _generated_caption(report_path: Path) -> str:
    mtime = report_path.stat().st_mtime if report_path.exists() else datetime.now().timestamp()
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%d %b %Y · %H:%M UTC")


# ---------------------------------------------------------------------------
# HTML fragments
# ---------------------------------------------------------------------------
def _score_ring(label: str, value: float) -> str:
    color, band = _band(value)
    deg = max(0.0, min(value, 100.0)) * 3.6
    return f"""
    <div class="ring-card">
        <div class="ring" style="background: conic-gradient({color} {deg}deg, rgba(255,255,255,0.14) {deg}deg);">
            <div class="ring-hole"><span class="ring-val">{value:.1f}<small>%</small></span></div>
        </div>
        <div class="ring-label">{_e(label)}</div>
        <div class="ring-band" style="color:{color};">{band}</div>
    </div>"""


def _priority_badge(priority: str) -> str:
    color = _PRIORITY_COLOR.get(priority, "#64748b")
    return f'<span class="badge" style="background:{color};">{_e(priority or "—").upper()}</span>'


def _rec_card(rec: dict) -> str:
    priority = rec.get("priority", "")
    color = _PRIORITY_COLOR.get(priority, "#64748b")
    draft = (rec.get("draft") or "").strip()
    draft_html = (
        f'<div class="draft-label">Draft fix</div><pre class="draft">{_e(draft)}</pre>'
        if draft else ""
    )
    return f"""
    <div class="rec" style="border-left-color:{color};">
        <div class="rec-head">
            <span class="rec-title">{_e(rec.get('title', 'Untitled'))}</span>
            {_priority_badge(priority)}
        </div>
        <div class="rec-scope">{_e(rec.get('scope', ''))}</div>
        <div class="field"><b>Issue:</b> {_e(rec.get('issue', ''))}</div>
        <div class="field"><b>Why it matters:</b> {_e(rec.get('why_it_matters', ''))}</div>
        <div class="field"><b>Recommendation:</b> {_e(rec.get('recommendation', ''))}</div>
        {draft_html}
    </div>"""


def _svg_trend_chart(
    labels: list[str],
    series: list[tuple[str, str, list[float | None]]],
    low_conf: list[bool],
    width: int = 760,
    height: int = 300,
) -> str:
    """Inline SVG line chart (Chromium renders it crisply — no charting lib/raster step).

    Mirrors the dashboards: 0–100 axis, gridlines, per-metric polylines + markers, and
    shaded same-day/low-confidence noise bands. Gaps (None) break the line (connectgaps).
    """
    left, right, top, bottom = 44, 16, 16, 36
    pw, ph = width - left - right, height - top - bottom
    n = len(labels)

    def px(i: int) -> float:
        return left + (pw * i / (n - 1) if n > 1 else pw / 2)

    def py(v: float) -> float:
        return top + (1 - max(0.0, min(v, 100.0)) / 100.0) * ph

    parts: list[str] = [f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">']
    # Gridlines + y labels.
    for gv in (0, 25, 50, 75, 100):
        gy = py(gv)
        parts.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="#ececf4" stroke-width="1"/>')
        parts.append(f'<text x="{left - 6}" y="{gy + 3:.1f}" text-anchor="end" font-size="9" fill="#5b6478">{gv}</text>')
    # Noise bands over same-day / low-confidence intervals.
    for i in range(1, n):
        if low_conf[i]:
            x0, x1 = px(i - 1), px(i)
            parts.append(f'<rect x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{ph}" fill="{AMBER}" opacity="0.12"/>')
    # X labels (thinned so they don't overlap).
    step = max(1, -(-n // 8))  # ceil(n/8)
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text x="{px(i):.1f}" y="{height - 14}" text-anchor="middle" font-size="8" fill="#5b6478">{_e(lab)}</text>')
    # Series polylines + markers (skip None so gaps break cleanly).
    for _name, color, values in series:
        pts = [(px(i), py(v)) for i, v in enumerate(values) if isinstance(v, (int, float))]
        if len(pts) >= 2:
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            parts.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _trend_card(label: str, cur: Any, prev: Any, last_low: bool) -> str:
    cur_txt = f"{cur:.1f}%" if isinstance(cur, (int, float)) else "—"
    if isinstance(cur, (int, float)) and isinstance(prev, (int, float)):
        delta = round(cur - prev, 1)
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "▬")
        color = GREEN if delta > 0 else (RED if delta < 0 else MUTED)
        vs = "vs earlier today" if last_low else "vs prev"
        foot = f'<span style="color:{color};font-weight:700">{arrow} {abs(delta):.1f}</span> {vs}'
    else:
        foot = '<span class="muted">— no prior</span>'
    return (
        f'<div class="tcard"><div class="tlabel">{_e(label)}</div>'
        f'<div class="tval">{cur_txt}</div><div class="tfoot">{foot}</div></div>'
    )


def _trend_section(trends: dict | None) -> str:
    """Trends-over-time PDF section. Returns "" when there aren't ≥2 runs (omits cleanly)."""
    if not trends or not trends.get("enough_data"):
        return ""
    runs = trends.get("runs") or []
    if len(runs) < 2:
        return ""
    last, prev = runs[-1], runs[-2]
    last_low = bool(last.get("low_confidence"))

    def _lab(iso: str) -> str:
        try:
            d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            return d.strftime("%d/%m %H:%M")
        except (ValueError, TypeError):
            return str(iso)

    labels = [_lab(r.get("timestamp", "")) for r in runs]
    low = [bool(r.get("low_confidence")) for r in runs]
    series = [
        ("Unified", ACCENT, [r.get("unified") for r in runs]),
        ("SEO", "#2563eb", [r.get("seo") for r in runs]),
        ("GEO", GREEN, [r.get("geo") for r in runs]),
        ("Brand visibility", AMBER, [r.get("brand_visibility") for r in runs]),
    ]
    chart = _svg_trend_chart(labels, series, low)
    cards = "".join(
        _trend_card(name, last.get(key), prev.get(key), last_low)
        for name, key in (("Unified", "unified"), ("SEO", "seo"), ("GEO", "geo"),
                          ("Brand visibility", "brand_visibility"))
    )
    legend = "".join(
        f'<span class="tlg"><span class="tdot" style="background:{color}"></span>{_e(name)}</span>'
        for name, color, _ in series
    )
    threshold = trends.get("min_interval_hours") or 24
    period = f'{_lab(prev.get("timestamp", ""))} → {_lab(last.get("timestamp", ""))}'
    if last_low:
        change_note = (
            f'<div class="noise-note">⚠️ Latest two runs are &lt; {threshold:.0f}h apart (same-day). '
            'Deltas below may reflect run-to-run variance, not a real trend.</div>'
        )
    else:
        change_note = ""
    band_note = (
        f'<div class="muted small">Shaded bands mark runs &lt; {threshold:.0f}h apart (same-day) — '
        'treat those segments as low-confidence, not a trend.</div>'
        if any(low) else ""
    )
    return f"""
    <section class="page">
        <h2>Trends Over Time</h2>
        <div class="muted small">Change since previous run · {_e(period)} · {len(runs)} runs</div>
        {change_note}
        <div class="trend-cards">{cards}</div>
        <h3>Scores &amp; visibility over time</h3>
        <div class="chart">{chart}</div>
        <div class="trend-legend">{legend}</div>
        {band_note}
    </section>"""


# ---------------------------------------------------------------------------
def _key_label(src: str) -> str:
    """API-key mode label — mirrors the dashboards."""
    return {"env": "saved", "temporary": "temporary", "none": "none"}.get(src, src or "none")


def _engine_breakdown_html(engine_scores: list[dict]) -> str:
    """AI Engine / Model GEO Breakdown table + headline note (parity with both dashboards).

    Returns "" when there are no engine scores (older reports omit cleanly).
    """
    if not engine_scores:
        return ""
    rows = []
    for e in sorted(engine_scores, key=lambda x: (x.get("provider", ""), x.get("model", ""))):
        grounding = "🌐 Live search" if e.get("web_grounded") else "⚠ Model knowledge"
        rows.append(
            f"""<tr>
                <td>{_e(e.get('provider', ''))}</td>
                <td>{_e(e.get('model', ''))}</td>
                <td>{grounding}</td>
                <td class="num">{int(e.get('sources_count') or 0)}</td>
                <td class="num">{float(e.get('geo_score') or 0.0):.1f}%</td>
                <td class="num">{round((e.get('visibility_rate') or 0.0) * 100, 1):.1f}%</td>
                <td class="num">{int(e.get('queries_run') or 0)}</td>
                <td class="ctr">{_e(_key_label(e.get('api_key_source', 'none')))}</td>
            </tr>"""
        )
    grounded = [e for e in engine_scores if not e.get("error") and e.get("queries_run") and e.get("web_grounded")]
    ungrounded = [e for e in engine_scores if not e.get("error") and e.get("queries_run") and not e.get("web_grounded")]
    notes = [
        f'Headline GEO score = average of {len(grounded)} live-grounded engine(s). '
        '🌐 = live web search · ⚠ = model knowledge only.'
    ]
    if ungrounded:
        names = ", ".join(f"{e.get('provider')}/{e.get('model')}" for e in ungrounded)
        notes.append(f"Excluded from the headline (ungrounded): {names}.")
    for e in (e for e in engine_scores if e.get("grounding_warning")):
        notes.append(f"⚠️ {e.get('provider')}/{e.get('model')}: {e.get('grounding_warning')}")
    for e in (e for e in engine_scores if e.get("error")):
        notes.append(f"⚠️ {e.get('provider')}/{e.get('model')} not run: {e.get('error')}")
    note_html = "".join(f'<div class="muted small">{_e(n)}</div>' for n in notes)
    return f"""<h3>AI Engine / Model GEO Breakdown</h3>
        <table>
            <thead><tr>
                <th>Provider</th><th>Model</th><th>Grounding</th><th class="num">Sources</th>
                <th class="num">GEO score</th><th class="num">Visibility</th>
                <th class="num">Queries</th><th class="ctr">API key</th>
            </tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>{note_html}"""


def _qcard(label: str, value: str, foot: str = "") -> str:
    foot_html = f'<div class="tfoot">{_e(foot)}</div>' if foot else ""
    return f'<div class="tcard"><div class="tlabel">{_e(label)}</div><div class="tval">{_e(value)}</div>{foot_html}</div>'


def _quality_signals_html(engine_scores: list[dict]) -> str:
    """GEO Quality Signals metric grid + sentiment split, per engine (parity w/ dashboards).

    Brand-mention metrics (sentiment / recommendation / rank) are over brand-mention
    answers only → "N/A" when the brand isn't mentioned. Citation coverage and competitor
    mentions are across all answers. Renders only blocks the report actually carries.
    """
    blocks = [(e, e.get("quality")) for e in engine_scores if e.get("quality")]
    if not blocks:
        return ""
    multi = len(blocks) > 1
    out = ["<h3>GEO Quality Signals</h3>"]
    for e, q in sorted(blocks, key=lambda b: (b[0].get("provider", ""), b[0].get("model", ""))):
        n_all = int(q.get("answers_total") or 0)
        n_men = int(q.get("brand_mentions") or 0)
        sent = q.get("sentiment") or {}
        rec = q.get("recommendation") or {}
        avg_sent = sent.get("avg")
        avg_rec = rec.get("avg")
        avg_rank = q.get("avg_brand_rank")
        cite_cov = (q.get("citation_coverage") or 0.0) * 100

        if multi:
            out.append(f'<div class="muted small" style="margin-top:6px"><b>{_e(e.get("provider"))}/{_e(e.get("model"))}</b></div>')
        out.append(
            f'<div class="muted small">Share of Voice: <b>{(q.get("sov") or 0.0) * 100:.0f}%</b> — '
            f'brand mentioned in {n_men} of {n_all} answers.</div>'
        )
        cards = [
            _qcard("Avg sentiment", f"{avg_sent:+.2f}" if (n_men and avg_sent is not None) else "N/A", "of brand mentions"),
            _qcard("Avg recommendation", f"{avg_rec * 100:.0f}%" if (n_men and avg_rec is not None) else "N/A", "of brand mentions"),
            _qcard("Citation coverage", f"{cite_cov:.0f}%", f"across all {n_all} answers"),
            _qcard("Competitor mentions", str(int(q.get("competitor_total") or 0)), f"across all {n_all} answers"),
            _qcard("Avg brand rank", f"#{avg_rank:.1f}" if (n_men and avg_rank is not None) else "N/A", "of brand mentions"),
        ]
        out.append(f'<div class="trend-cards qsig">{"".join(cards)}</div>')
        if n_men:
            out.append(
                f'<div class="muted small">Sentiment of {n_men} brand mention(s): '
                f'🟢 {int(sent.get("positive", 0))} positive · ⚪ {int(sent.get("neutral", 0))} neutral · '
                f'🔴 {int(sent.get("negative", 0))} negative.</div>'
            )
        else:
            out.append(f'<div class="muted small">N/A — brand not mentioned in any of the {n_all} answers.</div>')
    return "".join(out)


# Full HTML document
# ---------------------------------------------------------------------------
def render_html(report: dict, generated: str, logo_data_uri: str | None = None,
                trends: dict | None = None) -> str:
    brand = (report.get("brand") or report.get("site_name") or "").strip() or "Audit"
    unified = float(report.get("unified_score") or 0.0)
    seo_score = float(report.get("seo_score") or 0.0)
    geo_score = float(report.get("geo_score") or 0.0)

    seo = report.get("seo_report") or {}
    geo = report.get("geo_report") or {}
    pages = seo.get("pages") or []
    scored_pages = [p for p in pages if p.get("factors")]
    geo_results = geo.get("results") or []
    engine_scores = geo.get("engine_scores") or []
    seo_recs = report.get("seo_recommendations") or []
    geo_recs = report.get("geo_recommendations") or []

    # ---- Cover ----
    logo_html = f'<img class="logo" src="{logo_data_uri}" alt="logo">' if logo_data_uri else ""
    cover = f"""
    <section class="cover">
        {logo_html}
        <div class="cover-brand">{_e(brand)}</div>
        <div class="cover-title">SEO &amp; GEO Audit</div>
        <div class="cover-date">Generated {_e(generated)}</div>
        <div class="rings">
            {_score_ring("Unified Score", unified)}
            {_score_ring("SEO Score", seo_score)}
            {_score_ring("GEO Score", geo_score)}
        </div>
        <div class="cover-foot">Confidential — prepared for {_e(brand)}. Generated from the saved audit report.</div>
    </section>"""

    # ---- SEO section ----
    factor_counts: dict[str, dict[str, int]] = {}
    order: list[str] = []
    for p in scored_pages:
        for f in p.get("factors", []):
            fid = f.get("id", "?")
            if fid not in factor_counts:
                factor_counts[fid] = {"pass": 0, "warn": 0, "fail": 0}
                order.append(fid)
            st = f.get("status", "")
            if st in factor_counts[fid]:
                factor_counts[fid][st] += 1

    factor_rows = "".join(
        f"""<tr>
            <td>{_e(_factor_label(fid))}</td>
            <td class="num" style="color:{GREEN}">{factor_counts[fid]['pass']}</td>
            <td class="num" style="color:{AMBER}">{factor_counts[fid]['warn']}</td>
            <td class="num" style="color:{RED}">{factor_counts[fid]['fail']}</td>
        </tr>"""
        for fid in order
    )

    def _page_row(p: dict) -> str:
        score = float(p.get("score") or 0.0)
        color, _ = _band(score)
        url = _fix_mojibake(p.get("url", ""))
        return f"""<tr>
            <td class="url">{_e(url)}</td>
            <td class="num"><span class="dot" style="background:{color}"></span>{score:.1f}%</td>
        </tr>"""

    page_rows = "".join(
        _page_row(p) for p in sorted(scored_pages, key=lambda p: float(p.get("score") or 0.0))
    )
    seo_color, seo_band = _band(seo_score)
    seo_section = f"""
    <section class="page">
        <h2>SEO Breakdown</h2>
        <div class="stat-row">
            <div class="stat"><div class="stat-val" style="color:{seo_color}">{seo_score:.1f}%</div><div class="stat-lbl">Site score · {seo_band}</div></div>
            <div class="stat"><div class="stat-val">{len(scored_pages)}</div><div class="stat-lbl">Pages crawled &amp; scored</div></div>
        </div>
        <h3>Issues by on-page factor</h3>
        <table>
            <thead><tr><th>Factor</th><th class="num">Pass</th><th class="num">Warn</th><th class="num">Fail</th></tr></thead>
            <tbody>{factor_rows or '<tr><td colspan="4" class="muted">No factor data.</td></tr>'}</tbody>
        </table>
        <h3>Per-page scores</h3>
        <table>
            <thead><tr><th>Page URL</th><th class="num">Score</th></tr></thead>
            <tbody>{page_rows or '<tr><td colspan="2" class="muted">No scored pages.</td></tr>'}</tbody>
        </table>
    </section>"""

    # ---- GEO section ----
    measured = [r for r in geo_results if not r.get("error")]
    mentioned = sum(1 for r in measured if r.get("brand_mentioned"))
    visibility = round(mentioned / len(measured) * 100, 1) if measured else 0.0
    vis_color, _ = _band(visibility)

    def _geo_row(r: dict) -> str:
        prom = _prominence(r)
        prom_txt = f"{prom:.1f}%" if prom is not None else "—"
        hit = bool(r.get("brand_mentioned"))
        hit_html = f'<span style="color:{GREEN}">Yes</span>' if hit else f'<span style="color:{MUTED}">No</span>'
        browsed = "✓" if r.get("web_search_used") else "—"
        # Locale grounding applied to this query's search (missing → Global; backward compat).
        loc = str(r.get("locale_applied") or "global")
        loc_txt = "Global" if loc == "global" else _e(loc)
        return f"""<tr>
            <td>{_e(r.get('query', ''))}</td>
            <td class="ctr">{loc_txt}</td>
            <td class="ctr">{hit_html}</td>
            <td class="num">{prom_txt}</td>
            <td class="ctr">{browsed}</td>
        </tr>"""

    geo_rows = "".join(_geo_row(r) for r in measured)
    errored = [r for r in geo_results if r.get("error")]
    errored_note = (
        f'<div class="muted small">{len(errored)} query(ies) returned no answer (excluded from scoring).</div>'
        if errored else ""
    )

    # Competitors surfaced (ranked)
    comp_summary = geo.get("competitors_summary") or []
    comp_html = ""
    if comp_summary:
        chips = "".join(
            f'<span class="chip">{_e(c.get("name"))} <b>×{int(c.get("query_count", 0))}</b></span>'
            for c in comp_summary[:24]
        )
        comp_html = f'<h3>Competitors surfaced</h3><div class="chips">{chips}</div>'

    # Cited sources (aggregated unique)
    seen: set[str] = set()
    sources: list[dict] = []
    for r in geo_results:
        for s in r.get("sources") or []:
            u = s.get("url")
            if u and u not in seen:
                seen.add(u)
                sources.append(s)
    sources_html = ""
    if sources:
        items = "".join(
            f'<li><span class="src-title">{_e(s.get("title") or _domain(s.get("url","")))}</span>'
            f'<span class="src-url">{_e(_domain(s.get("url", "")))}</span></li>'
            for s in sources[:30]
        )
        sources_html = f'<h3>Cited sources ({len(sources)})</h3><ul class="sources">{items}</ul>'

    assessment = (report.get("geo_assessment") or "").strip()
    assessment_html = f'<div class="callout">{_e(assessment)}</div>' if assessment else ""

    # Share of Voice — ranked brands (subject + competitors) by presence
    sov = geo.get("share_of_voice") or []
    sov_head = (geo.get("sov_headline") or "").strip()
    sov_html = ""
    if sov:
        shown = sov[:15]
        if not any(s.get("is_subject") for s in shown):
            subj = next((s for s in sov if s.get("is_subject")), None)
            if subj:
                shown = shown + [subj]
        rows = []
        for s in shown:
            pct = round((s.get("share") or 0.0) * 100, 1)
            cls = " subject" if s.get("is_subject") else ""
            star = " ★" if s.get("is_subject") else ""
            rows.append(
                f'<div class="sov-row"><div class="sov-name{cls}">{_e(s.get("brand"))}{star}</div>'
                f'<div class="sov-track"><div class="sov-fill{cls}" style="width:{pct}%"></div></div>'
                f'<div class="sov-pct">{pct:.0f}%</div></div>'
            )
        head_html = f'<div class="sov-headline">🏆 {_e(sov_head)}</div>' if sov_head else ""
        sov_html = (
            f'<h3>Share of Voice</h3>{head_html}'
            f'<div class="muted small">Share of measured queries where each brand appears — '
            f'{_e(brand)} highlighted.</div>{"".join(rows)}'
        )

    # AI Engine / Model breakdown + GEO Quality Signals (parity with both dashboards).
    engine_breakdown_html = _engine_breakdown_html(engine_scores)
    quality_signals_html = _quality_signals_html(engine_scores)

    geo_section = f"""
    <section class="page">
        <h2>GEO Report</h2>
        <div class="stat-row">
            <div class="stat"><div class="stat-val" style="color:{vis_color}">{visibility:.1f}%</div><div class="stat-lbl">Brand visibility · {mentioned}/{len(measured)} answers</div></div>
            <div class="stat"><div class="stat-val">{geo_score:.1f}%</div><div class="stat-lbl">GEO score</div></div>
        </div>
        {assessment_html}
        {engine_breakdown_html}
        {quality_signals_html}
        {sov_html}
        <h3>Per-query results</h3>
        <table>
            <thead><tr><th>Query</th><th class="ctr">Region</th><th class="ctr">Mentioned</th><th class="num">Prominence</th><th class="ctr">Browsed</th></tr></thead>
            <tbody>{geo_rows or '<tr><td colspan="5" class="muted">No measured queries.</td></tr>'}</tbody>
        </table>
        {errored_note}
        {comp_html}
        {sources_html}
    </section>"""

    # ---- Recommendations ----
    combined = [{**r, "_area": r.get("area") or "SEO"} for r in seo_recs] + \
               [{**r, "_area": r.get("area") or "GEO"} for r in geo_recs]
    top = sorted(combined, key=lambda r: _PRIORITY_RANK.get(r.get("priority", ""), 1))[:5]
    top_rows = "".join(
        f"""<tr>
            <td>{_priority_badge(r.get('priority', ''))}</td>
            <td><span class="area-tag">{_e(r.get('_area'))}</span></td>
            <td>{_e(r.get('title', ''))}</td>
        </tr>"""
        for r in top
    )
    top_section = f"""
    <section class="page">
        <h2>Top Priority Actions</h2>
        <table class="top">
            <thead><tr><th>Priority</th><th>Area</th><th>Action</th></tr></thead>
            <tbody>{top_rows or '<tr><td colspan="3" class="muted">No recommendations.</td></tr>'}</tbody>
        </table>
    </section>"""

    seo_recs_sorted = sorted(seo_recs, key=lambda r: _PRIORITY_RANK.get(r.get("priority", ""), 1))
    geo_recs_sorted = sorted(geo_recs, key=lambda r: _PRIORITY_RANK.get(r.get("priority", ""), 1))
    seo_recs_html = "".join(_rec_card(r) for r in seo_recs_sorted) or '<div class="muted">No SEO recommendations.</div>'
    geo_recs_html = "".join(_rec_card(r) for r in geo_recs_sorted) or '<div class="muted">No GEO recommendations.</div>'
    recs_section = f"""
    <section class="page">
        <h2>SEO Recommendations</h2>
        {seo_recs_html}
    </section>
    <section class="page">
        <h2>GEO Recommendations</h2>
        {geo_recs_html}
    </section>"""

    # ---- Trends over time (only when ≥2 historical runs exist; omitted cleanly else) ----
    trends_section = _trend_section(trends)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><style>
{_CSS}
</style></head>
<body>
{cover}
{top_section}
{trends_section}
{seo_section}
{geo_section}
{recs_section}
</body></html>"""


_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    font-family: -apple-system, "Segoe UI", Roboto, "Inter", Helvetica, Arial, sans-serif;
    color: #0f1424; font-size: 11px; line-height: 1.5; -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h2 { font-size: 19px; margin: 0 0 12px; color: #16182a; letter-spacing: -0.01em; border-bottom: 2px solid #ece9ff; padding-bottom: 6px; }
h3 { font-size: 13px; margin: 18px 0 7px; color: #2a2f45; }
.muted { color: #5b6478; }
.small { font-size: 10px; }

/* Page flow */
.page { padding: 38px 42px; page-break-before: always; }

/* Cover */
.cover {
    height: 100vh; padding: 70px 56px; color: #eef0fb;
    background: linear-gradient(150deg, #0b1020 0%, #1a1340 55%, #0f1b33 100%);
    display: flex; flex-direction: column;
}
.logo { max-height: 54px; max-width: 220px; margin-bottom: 26px; }
.cover-brand { font-size: 46px; font-weight: 800; letter-spacing: -0.02em; }
.cover-title { font-size: 22px; font-weight: 600; color: #b7a9ff; margin-top: 6px; }
.cover-date { font-size: 13px; color: #9aa3b8; margin-top: 10px; }
.rings { display: flex; gap: 30px; margin-top: auto; margin-bottom: auto; }
.ring-card { text-align: center; }
.ring {
    width: 150px; height: 150px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
}
.ring-hole {
    width: 116px; height: 116px; border-radius: 50%; background: #131a32;
    display: flex; align-items: center; justify-content: center;
}
.ring-val { font-size: 30px; font-weight: 800; color: #ffffff; }
.ring-val small { font-size: 15px; font-weight: 600; }
.ring-label { margin-top: 12px; font-size: 13px; font-weight: 600; color: #cfd4e6; }
.ring-band { font-size: 12px; font-weight: 700; margin-top: 2px; }
.cover-foot { font-size: 10px; color: #6b7494; margin-top: 26px; }

/* Stats */
.stat-row { display: flex; gap: 18px; margin: 6px 0 4px; }
.stat { flex: 1; border: 1px solid #e7e8f0; border-radius: 12px; padding: 14px 16px; background: #fafaff; }
.stat-val { font-size: 26px; font-weight: 800; color: #16182a; }
.stat-lbl { font-size: 10.5px; color: #5b6478; margin-top: 2px; }

/* Tables */
table { width: 100%; border-collapse: collapse; margin-top: 4px; }
th, td { text-align: left; padding: 7px 9px; border-bottom: 1px solid #ececf4; vertical-align: top; }
th { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7494; background: #f6f6fc; }
td.num, th.num { text-align: right; white-space: nowrap; }
td.ctr, th.ctr { text-align: center; }
td.url { word-break: break-all; color: #3949ab; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
table.top td { vertical-align: middle; }

/* Badges, chips, tags */
.badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 9px; font-weight: 700; color: #fff; letter-spacing: 0.04em; }
.area-tag { display: inline-block; padding: 1px 8px; border-radius: 6px; font-size: 9px; font-weight: 700; background: #eceaff; color: #5b4bd6; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid #e1e3ef; border-radius: 999px; padding: 3px 10px; font-size: 10px; background: #fafaff; }
.chip b { color: #5b4bd6; }

/* Callout */
.callout { border-left: 4px solid #7c5cff; background: #f6f4ff; padding: 10px 14px; border-radius: 0 10px 10px 0; margin: 10px 0; font-size: 11px; }

/* Share of Voice */
.sov-headline { font-weight: 700; font-size: 13px; margin: 6px 0 2px; color: #16182a; }
.sov-row { display: grid; grid-template-columns: 130px 1fr 38px; align-items: center; gap: 10px; margin: 5px 0; break-inside: avoid; }
.sov-name { font-size: 10.5px; color: #2a2f45; }
.sov-name.subject { font-weight: 700; color: #16182a; }
.sov-track { height: 9px; background: #ececf4; border-radius: 999px; overflow: hidden; }
.sov-fill { height: 100%; border-radius: 999px; background: #9aa3c0; }
.sov-fill.subject { background: #7c5cff; }
.sov-pct { font-size: 10px; text-align: right; color: #5b6478; }

/* Recommendations */
.rec { border: 1px solid #e7e8f0; border-left-width: 5px; border-radius: 10px; padding: 12px 15px; margin-bottom: 11px; background: #fff; page-break-inside: avoid; }
.rec-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.rec-title { font-weight: 700; font-size: 12.5px; }
.rec-scope { color: #6b7494; font-size: 10px; margin: 3px 0 8px; }
.field { margin: 5px 0; font-size: 11px; }
.field b { color: #16182a; }
.draft-label { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7494; margin-top: 9px; }
.draft {
    margin: 4px 0 0; padding: 10px 12px; background: #0f1424; color: #e8eaf2; border-radius: 8px;
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 9.5px; line-height: 1.5;
    white-space: pre-wrap; word-break: break-word;
}

/* Trends over time */
.trend-cards { display: flex; gap: 12px; margin: 10px 0 4px; }
.tcard { flex: 1; border: 1px solid #e7e8f0; border-radius: 12px; padding: 12px 14px; background: #fafaff; }
.tlabel { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7494; }
.tval { font-size: 23px; font-weight: 800; color: #16182a; margin-top: 2px; }
.tfoot { font-size: 10px; color: #5b6478; margin-top: 3px; }
/* GEO Quality Signals: 5 compact metric cards across (reuses trend-card styling). */
.trend-cards.qsig { gap: 8px; margin: 6px 0; break-inside: avoid; }
.qsig .tcard { padding: 9px 11px; }
.qsig .tval { font-size: 18px; }
.qsig .tfoot { font-size: 8.5px; }
.chart { border: 1px solid #e7e8f0; border-radius: 12px; padding: 12px; background: #fff; margin-top: 4px; }
.trend-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 8px; }
.tlg { display: flex; align-items: center; gap: 6px; font-size: 10px; color: #5b6478; }
.tdot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.noise-note { border-left: 4px solid #d97706; background: #fff7ed; padding: 8px 12px; border-radius: 0 8px 8px 0; margin: 8px 0; font-size: 10.5px; color: #7c4a09; }

/* Sources */
.sources { list-style: none; padding: 0; margin: 4px 0 0; columns: 2; column-gap: 22px; }
.sources li { margin-bottom: 6px; break-inside: avoid; font-size: 10px; }
.src-title { display: block; color: #16182a; }
.src-url { display: block; color: #6b7494; font-size: 9px; }
"""


# ---------------------------------------------------------------------------
# PDF rendering (Playwright / Chromium — full CSS fidelity, offline)
# ---------------------------------------------------------------------------
def _logo_data_uri(logo_path: Path | None) -> str | None:
    if not logo_path:
        return None
    p = Path(logo_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.exists():
        return None
    mime = "image/png"
    suffix = p.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suffix == ".svg":
        mime = "image/svg+xml"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _load_logo_from_config() -> Path | None:
    """Optional logo path from geo_config.yaml `report.logo` (config-driven, optional)."""
    try:
        import yaml
        with GEO_CONFIG.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        logo = (cfg.get("report") or {}).get("logo")
        return Path(logo) if logo else None
    except Exception:
        return None


def build_pdf(
    report_path: Path | str = DEFAULT_REPORT,
    output_path: Path | str = DEFAULT_OUTPUT,
    logo_path: Path | str | None = None,
) -> Path:
    """Render the saved report JSON to a branded PDF. Returns the output path.

    Purely offline: reads the JSON and renders HTML→PDF via Chromium. No API calls.
    """
    report_path = Path(report_path)
    output_path = Path(output_path)
    with report_path.open("r", encoding="utf-8") as fh:
        report = json.load(fh)

    if logo_path is None:
        logo_path = _load_logo_from_config()

    # Trends-over-time from the SAME saved report history the dashboards read (reused via
    # src.reporting.trends — no rescoring, no API). None/insufficient history → section omitted.
    trends = None
    client = (report.get("client") or report.get("brand") or "").strip()
    if client:
        try:
            from src.reporting.trends import series_for_client
            trends = series_for_client(client)
        except Exception:  # history is a nice-to-have — never block the PDF
            trends = None

    html = render_html(report, _generated_caption(report_path), _logo_data_uri(logo_path), trends=trends)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
    return output_path


def main() -> None:
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REPORT
    if not report_path.exists():
        print(f"No report at {report_path} — run `python -m src.pipeline` first.")
        sys.exit(1)
    out = build_pdf(report_path=report_path)
    size_kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
