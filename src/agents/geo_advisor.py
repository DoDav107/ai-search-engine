"""GEO advisory: turn measured per-query AI answers into grounded GEO recommendations.

This module only reads the GEO measurement results (it never re-measures). It analyses
the real AI answers and produces recommendations across four GEO levers, plus an overall
visibility assessment. It must not invent facts about the brand or its offerings.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .drafting_agent import _FACTOR_LABEL, parse_json_object
from ..engine.models import AdvisoryRecommendation, GeoReport, SiteReport

_ALLOWED_PRIORITY = {"High", "Medium", "Low"}

# The four GEO levers, in render order. Titles double as fallback recommendation titles.
_LEVERS = [
    "On-site content answering the target queries",
    "Third-party authority & citations",
    "Structured data / schema for entity clarity",
    "Brand consistency across the web",
]

# Per-lever draft templates used when the model returns no usable draft. These contain
# only structure + [bracketed placeholders] and {brand} — never fabricated specifics —
# so a missing draft degrades to a safe, clearly-structured template the client fills in.
_GEO_FALLBACK_DRAFTS: list[str] = [
    (  # Lever 1 — on-site content / FAQ
        "FAQ block to add to a relevant page — answer each target query in plain, "
        "self-contained language an AI engine can lift verbatim:\n\n"
        '### [Paste a target query as the heading, e.g. "What are the best running shoe brands?"]\n'
        "[1–2 factual sentences that name {brand} and state what it offers for this need. "
        "Use only real details from your site — no invented claims.]\n\n"
        "### [Next target query]\n"
        "[Concise, directly-stated answer the model can quote.]"
    ),
    (  # Lever 2 — third-party authority
        "On-page credibility passage (publish only real, verifiable sources — never fabricate coverage):\n\n"
        "## Why {brand}\n"
        "[1–2 factual sentences positioning {brand} for the target topics, grounded in your real offering.]\n\n"
        "As featured in: [Publication name + link], [Publication name + link]"
    ),
    (  # Lever 3 — structured data
        'JSON-LD — paste inside <script type="application/ld+json"> in the page <head>. '
        "Fill each question/answer from your real on-page content:\n"
        "{{\n"
        '  "@context": "https://schema.org",\n'
        '  "@type": "FAQPage",\n'
        '  "mainEntity": [\n'
        "    {{\n"
        '      "@type": "Question",\n'
        '      "name": "[target query]",\n'
        '      "acceptedAnswer": {{ "@type": "Answer", "text": "[concise factual answer that names {brand}]" }}\n'
        "    }}\n"
        "  ]\n"
        "}}"
    ),
    (  # Lever 4 — brand consistency
        "Standard brand boilerplate — use identical wording on your site, profiles, and "
        "directories so all sources agree:\n\n"
        "{brand} — [one-line category / positioning].\n"
        "[1–2 factual sentences describing what {brand} offers, grounded in your real content. "
        "Keep this wording identical everywhere.]"
    ),
]


def _geo_fallback_draft(index: int, brand: str) -> str:
    """Return the per-lever template draft, brand-filled. Clamps out-of-range indices."""
    i = index if 0 <= index < len(_GEO_FALLBACK_DRAFTS) else 0
    return _GEO_FALLBACK_DRAFTS[i].format(brand=brand or "the brand")


def _site_content_digest(
    page_content: dict[str, dict[str, Any]] | None,
    max_pages: int = 8,
    max_chars: int = 2600,
) -> str:
    """Condense crawled page content (titles, headings, text) into a grounding block.

    This is the ONLY source of truth GEO drafts may use — same crawled content the SEO
    drafts are grounded in. Capped so it fits the drafting token budget.
    """
    if not page_content:
        return (
            "(no crawled page content available — produce clearly-structured templates "
            "with [placeholders]; do not invent specifics)"
        )
    blocks: list[str] = []
    used = 0
    for url, content in list(page_content.items())[:max_pages]:
        title = (content.get("title") or "").strip()
        headings = content.get("headings") or []
        head_str = "; ".join(f"{tag.upper()}: {text}" for tag, text in headings[:6])
        text = (content.get("text") or "").strip()[:300]
        block = (
            f"PAGE: {url}\n"
            f"  Title: {title or '(none)'}\n"
            f"  Headings: {head_str or '(none)'}\n"
            f"  Text: {text or '(none)'}"
        )
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks) if blocks else "(no usable crawled page content)"


def _clamp_priority(value: Any) -> str:
    p = str(value or "").strip().capitalize()
    return p if p in _ALLOWED_PRIORITY else "Medium"


def _visibility(report: GeoReport) -> tuple[int, int, float]:
    # Only count measured queries — measurement errors are excluded, not treated as misses.
    measured = [r for r in report.results if not r.error]
    total = len(measured)
    mentioned = sum(1 for r in measured if r.brand_mentioned)
    pct = round(mentioned / total * 100, 1) if total else 0.0
    return mentioned, total, pct


def _build_prompt(report: GeoReport, visibility: float, content_digest: str) -> str:
    """Build a JSON-returning prompt that feeds the real answers + crawled content in.

    The AI answers ground the analysis (issue / why / recommendation); the crawled page
    content grounds the publishable ``draft`` for each recommendation.
    """
    brand = report.brand
    blocks: list[str] = []
    for i, r in enumerate(report.results, 1):
        answer = (r.answer or "").strip().replace("\n", " ")
        if len(answer) > 700:
            answer = answer[:700] + " …"
        blocks.append(
            f"Q{i}: {r.query}\n"
            f"  Brand '{brand}' mentioned: {'yes' if r.brand_mentioned else 'no'}\n"
            f"  AI answer: {answer if answer else '(no answer / error)'}"
        )
    data_block = "\n\n".join(blocks)

    levers = "\n".join(f"  {i + 1}. {lever}" for i, lever in enumerate(_LEVERS))

    return (
        "You are a Generative Engine Optimization (GEO) analyst. GEO is about getting a brand surfaced in "
        "AI-generated answers. Analyse the REAL AI answers below for the brand "
        f"'{brand}'. For each query note which brands/companies/competitors the AI named, and whether "
        f"'{brand}' appeared; where it is absent, infer what would help it appear.\n\n"
        f"Current measured visibility: {brand} appears in {visibility}% of the answers.\n\n"
        "Return a single JSON object (no markdown, no commentary) with these keys:\n"
        '  "assessment": 2-3 sentences on current AI visibility for the brand and what it means;\n'
        '  "recommendations": a list of exactly four objects, one per lever below, each with keys '
        '"title", "priority" (High|Medium|Low), "scope" (which queries it addresses), "issue" (grounded in '
        'the real answers), "why_it_matters" (the effect on being surfaced in AI-generated answers), '
        '"recommendation" (concrete and actionable), and '
        '"draft": a ready-to-publish, self-contained on-page passage or FAQ answer the brand could add to '
        "its site to improve being surfaced in AI answers for these queries. Write it in a plain, "
        "directly-stated, liftable style (the way AI engines quote verbatim). For the structured-data "
        "lever, the draft must be a JSON-LD block. Ground every draft ONLY in the REAL CRAWLED PAGE "
        "CONTENT below; do NOT invent products, locations, prices, numbers, or facts about the brand. If "
        "there is not enough real content to ground a specific claim, write a clearly-structured template "
        "with [bracketed placeholders] instead of inventing specifics.\n"
        "The four levers (produce one recommendation each, in this order):\n"
        f"{levers}\n\n"
        "Ground the analysis in the actual answers, and the drafts in the crawled page content. Return "
        "ONLY the JSON object. Every draft is for human review before publishing — never auto-applied.\n\n"
        "--- REAL AI ANSWERS (ground the analysis here) ---\n"
        f"{data_block}\n"
        "--- END AI ANSWERS ---\n\n"
        "--- REAL CRAWLED PAGE CONTENT (ground all drafts ONLY here) ---\n"
        f"{content_digest}\n"
        "--- END CRAWLED CONTENT ---"
    )


def _fallback_assessment(brand: str, mentioned: int, total: int, visibility: float) -> str:
    if total == 0:
        return f"No queries were measured, so {brand}'s AI visibility cannot be assessed yet."
    if mentioned == 0:
        return (
            f"{brand} was not mentioned in any of the {total} AI answers (0% visibility). The brand is "
            "effectively invisible to AI engines for these queries and is being omitted in favour of "
            "competitors the models already know."
        )
    return (
        f"{brand} appeared in {mentioned} of {total} AI answers ({visibility}% visibility). There is "
        "partial presence, but gaps remain where competitors are surfaced instead."
    )


def _fallback_recs(brand: str, visibility: float) -> list[AdvisoryRecommendation]:
    """Deterministic, grounded-in-visibility recommendations covering all four levers."""
    high = visibility < 50
    pr_primary = "High" if high else "Medium"
    return [
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[0], priority=pr_primary, scope="All target queries",
            issue=f"The AI answers to the target queries do not consistently surface {brand} ({visibility}% visibility).",
            why_it_matters="AI engines extract answers from clear, directly-stated on-page text. If your pages don't answer these queries in plain, self-contained language, the model has nothing to quote and omits the brand.",
            recommendation="Publish pages or FAQ sections that answer each target query directly: use the question as a heading followed by a concise, factual, self-contained answer the model can lift verbatim.",
            draft=_geo_fallback_draft(0, brand),
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[1], priority=pr_primary, scope="All target queries",
            issue=f"Competitors are cited in the answers while {brand} lacks the third-party signals AI models rely on.",
            why_it_matters="AI models weight brands that are corroborated across independent, authoritative sources. Without reviews, listicles, and press, the model has low confidence in mentioning the brand.",
            recommendation="Earn placements in reputable third-party roundups, review sites, and industry press for the target topics so models encounter the brand from trusted sources.",
            draft=_geo_fallback_draft(1, brand),
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[2], priority="Medium", scope="All target queries",
            issue="Entity information is not expressed in machine-readable structured data.",
            why_it_matters="Schema.org markup makes the brand an unambiguous entity, improving how engines associate it with the relevant topics and queries.",
            recommendation="Add Organization/Product/FAQPage JSON-LD that clearly states the entity name, category, and relationships, consistent with the on-page content.",
            draft=_geo_fallback_draft(2, brand),
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[3], priority="Low" if not high else "Medium", scope="All target queries",
            issue="Brand naming and descriptions may be inconsistent across the web, weakening entity recognition.",
            why_it_matters="Consistent name, description, and category across sources reinforce a single, confident entity the model is more likely to surface.",
            recommendation="Standardise the brand name, one-line description, and category across the site, profiles, and directories so all sources agree.",
            draft=_geo_fallback_draft(3, brand),
        ),
    ]


def _coerce(raw: Any, brand: str, visibility: float) -> list[AdvisoryRecommendation]:
    """Convert model recommendation objects into AdvisoryRecommendations; fall back if unusable."""
    recs: list[AdvisoryRecommendation] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            issue = str(item.get("issue") or "").strip()
            why = str(item.get("why_it_matters") or "").strip()
            fix = str(item.get("recommendation") or "").strip()
            if not (title and issue and fix):
                continue
            # Use the model's grounded draft; fall back to the per-lever template (by
            # position) so every GEO rec carries a non-empty, non-fabricated draft.
            draft = str(item.get("draft") or "").strip() or _geo_fallback_draft(i, brand)
            recs.append(
                AdvisoryRecommendation(
                    area="GEO",
                    title=title,
                    priority=_clamp_priority(item.get("priority")),
                    scope=str(item.get("scope") or "All target queries").strip(),
                    issue=issue,
                    why_it_matters=why or "Strengthens how AI engines surface the brand for these queries.",
                    recommendation=fix,
                    draft=draft,
                )
            )
    return recs if recs else _fallback_recs(brand, visibility)


def _seo_facts(site_report: SiteReport) -> dict[str, Any]:
    """Aggregate ONLY real crawl/factor figures for a grounded SEO assessment."""
    pages = [p for p in (site_report.pages or []) if p.factors]
    status_counts = Counter()
    fail_factors = Counter()
    warn_factors = Counter()
    for p in pages:
        for f in p.factors:
            status_counts[f.status] += 1
            if f.status == "fail":
                fail_factors[f.id] += 1
            elif f.status == "warn":
                warn_factors[f.id] += 1
    scores = [p.score for p in pages]
    def _label(fid: str) -> str:
        return _FACTOR_LABEL.get(fid, fid.replace("_", " "))
    return {
        "site_score": site_report.score,
        "pages_scored": len(pages),
        "passes": status_counts.get("pass", 0),
        "warns": status_counts.get("warn", 0),
        "fails": status_counts.get("fail", 0),
        "min_score": round(min(scores), 1) if scores else None,
        "max_score": round(max(scores), 1) if scores else None,
        "top_failing": [(_label(fid), n) for fid, n in fail_factors.most_common(5)],
        "top_warning": [(_label(fid), n) for fid, n in warn_factors.most_common(5)],
    }


def _seo_fallback_assessment(f: dict[str, Any]) -> str:
    """Deterministic SEO assessment from the real figures (used for mock / no-LLM runs)."""
    if not f["pages_scored"]:
        return "No pages could be crawled and scored, so an SEO assessment cannot be produced yet."
    parts = [
        f"Across {f['pages_scored']} crawled page(s) the site scores {f['site_score']:.1f}% on SEO "
        f"({f['passes']} factor checks passed, {f['warns']} warnings, {f['fails']} failures)."
    ]
    if f["min_score"] is not None and f["max_score"] is not None and f["max_score"] != f["min_score"]:
        parts.append(f"Per-page scores range from {f['min_score']:.1f}% to {f['max_score']:.1f}%.")
    weak = f["top_failing"] or f["top_warning"]
    if weak:
        named = ", ".join(f"{label} ({n})" for label, n in weak[:3])
        parts.append(f"The most common issues are: {named}.")
    else:
        parts.append("No failing or warning factors were detected on the scored pages.")
    return " ".join(parts)


def _build_seo_prompt(f: dict[str, Any]) -> str:
    failing = "; ".join(f"{label}: {n} page(s)" for label, n in f["top_failing"]) or "none"
    warning = "; ".join(f"{label}: {n} page(s)" for label, n in f["top_warning"]) or "none"
    return (
        "You are an SEO analyst. Write a 2–4 sentence assessment of this site's on-page SEO, "
        "for a client report. Use ONLY the figures provided below — do NOT invent metrics, page "
        "content, rankings, or traffic. If the data is thin, say less. Plain prose, no headings.\n\n"
        f"SEO site score: {f['site_score']:.1f}% (0–100)\n"
        f"Pages crawled and scored: {f['pages_scored']}\n"
        f"Factor checks — passed: {f['passes']}, warnings: {f['warns']}, failures: {f['fails']}\n"
        f"Per-page score range: {f['min_score']}–{f['max_score']}\n"
        f"Most common failing factors: {failing}\n"
        f"Most common warning factors: {warning}\n"
    )


def build_seo_assessment(
    site_report: SiteReport,
    config: dict[str, Any],
) -> str:
    """Narrative SEO assessment mirroring the GEO one — SAME provider/model path.

    Grounded strictly in crawl/factor figures (scores, pass/warn/fail counts, per-page
    score range, the specific failing factors). Makes no claim unsupported by the crawl.
    Falls back to a deterministic, figure-based summary for mock/no-LLM runs.
    """
    facts = _seo_facts(site_report)
    engine = str(config.get("engine", "mock")).lower()
    mode = str(config.get("openai", {}).get("mode", "live")).lower()

    if mode == "live" and engine != "mock" and facts["pages_scored"]:
        from src.clients import openai_client as _oc
        openai_cfg = config.get("openai", {})
        try:
            text = _oc.client.chat(
                _build_seo_prompt(facts),
                max_completion_tokens=int(openai_cfg.get("advisory_max_completion_tokens", 3500)),
                reasoning_effort=openai_cfg.get("reasoning_effort") or None,
                timeout=float(openai_cfg.get("advisory_timeout", 120)),
            )
            text = (text or "").strip()
            if text:
                return text
        except Exception:
            pass
    return _seo_fallback_assessment(facts)


def build_geo_recommendations(
    report: GeoReport,
    config: dict[str, Any],
    page_content: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, list[AdvisoryRecommendation]]:
    """Return (overall assessment, GEO recommendations) grounded in the real AI answers.

    ``page_content`` (URL -> extracted title/headings/text, the same crawled content used
    for SEO drafts) grounds each recommendation's publishable ``draft``. When omitted, the
    per-lever template drafts (placeholders only) are used.
    """
    brand = report.brand
    mentioned, total, visibility = _visibility(report)
    content_digest = _site_content_digest(page_content)

    engine = str(config.get("engine", "mock")).lower()
    mode = str(config.get("openai", {}).get("mode", "live")).lower()

    parsed: dict[str, Any] | None = None
    if mode == "live" and engine != "mock":
        from src.clients import openai_client as _oc
        openai_cfg = config.get("openai", {})
        # One large analytical call: assessment + four grounded drafts. It needs a big
        # token budget (the full JSON runs ~2.5k tokens — the 500–2000 defaults truncate
        # it into invalid JSON), low reasoning effort so a reasoning model doesn't burn
        # the budget, and a longer timeout than the 30s default (it takes ~30-45s).
        advisory_max_tokens = int(openai_cfg.get("advisory_max_completion_tokens", 3500))
        reasoning_effort = openai_cfg.get("reasoning_effort") or None
        advisory_timeout = float(openai_cfg.get("advisory_timeout", 120))
        try:
            parsed = parse_json_object(
                _oc.client.chat(
                    _build_prompt(report, visibility, content_digest),
                    max_completion_tokens=advisory_max_tokens,
                    reasoning_effort=reasoning_effort,
                    timeout=advisory_timeout,
                )
            )
        except Exception:
            parsed = None

    assessment = ""
    raw_recs: Any = None
    if isinstance(parsed, dict):
        assessment = str(parsed.get("assessment") or "").strip()
        raw_recs = parsed.get("recommendations")

    recs = _coerce(raw_recs, brand, visibility)
    if not assessment:
        assessment = _fallback_assessment(brand, mentioned, total, visibility)
    return assessment, recs
