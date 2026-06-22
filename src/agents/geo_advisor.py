"""GEO advisory: turn measured per-query AI answers into grounded GEO recommendations.

This module only reads the GEO measurement results (it never re-measures). It analyses
the real AI answers and produces recommendations across four GEO levers, plus an overall
visibility assessment. It must not invent facts about the brand or its offerings.
"""

from __future__ import annotations

from typing import Any

from .drafting_agent import parse_json_object
from ..engine.models import AdvisoryRecommendation, GeoReport

_ALLOWED_PRIORITY = {"High", "Medium", "Low"}

# The four GEO levers, in render order. Titles double as fallback recommendation titles.
_LEVERS = [
    "On-site content answering the target queries",
    "Third-party authority & citations",
    "Structured data / schema for entity clarity",
    "Brand consistency across the web",
]


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


def _build_prompt(report: GeoReport, visibility: float) -> str:
    """Build a JSON-returning prompt that feeds the real answers in for analysis."""
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
        'the real answers), "why_it_matters" (the effect on being surfaced in AI-generated answers), and '
        '"recommendation" (concrete and actionable).\n'
        "The four levers (produce one recommendation each, in this order):\n"
        f"{levers}\n\n"
        "Ground everything in the actual answers shown. Do NOT invent facts about the brand's products, "
        "locations, pricing, or offerings. Return ONLY the JSON object.\n\n"
        "--- REAL AI ANSWERS (the only source of truth) ---\n"
        f"{data_block}\n"
        "--- END AI ANSWERS ---"
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
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[1], priority=pr_primary, scope="All target queries",
            issue=f"Competitors are cited in the answers while {brand} lacks the third-party signals AI models rely on.",
            why_it_matters="AI models weight brands that are corroborated across independent, authoritative sources. Without reviews, listicles, and press, the model has low confidence in mentioning the brand.",
            recommendation="Earn placements in reputable third-party roundups, review sites, and industry press for the target topics so models encounter the brand from trusted sources.",
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[2], priority="Medium", scope="All target queries",
            issue="Entity information is not expressed in machine-readable structured data.",
            why_it_matters="Schema.org markup makes the brand an unambiguous entity, improving how engines associate it with the relevant topics and queries.",
            recommendation="Add Organization/Product/FAQPage JSON-LD that clearly states the entity name, category, and relationships, consistent with the on-page content.",
        ),
        AdvisoryRecommendation(
            area="GEO", title=_LEVERS[3], priority="Low" if not high else "Medium", scope="All target queries",
            issue="Brand naming and descriptions may be inconsistent across the web, weakening entity recognition.",
            why_it_matters="Consistent name, description, and category across sources reinforce a single, confident entity the model is more likely to surface.",
            recommendation="Standardise the brand name, one-line description, and category across the site, profiles, and directories so all sources agree.",
        ),
    ]


def _coerce(raw: Any, brand: str, visibility: float) -> list[AdvisoryRecommendation]:
    """Convert model recommendation objects into AdvisoryRecommendations; fall back if unusable."""
    recs: list[AdvisoryRecommendation] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            issue = str(item.get("issue") or "").strip()
            why = str(item.get("why_it_matters") or "").strip()
            fix = str(item.get("recommendation") or "").strip()
            if not (title and issue and fix):
                continue
            recs.append(
                AdvisoryRecommendation(
                    area="GEO",
                    title=title,
                    priority=_clamp_priority(item.get("priority")),
                    scope=str(item.get("scope") or "All target queries").strip(),
                    issue=issue,
                    why_it_matters=why or "Strengthens how AI engines surface the brand for these queries.",
                    recommendation=fix,
                    draft="",
                )
            )
    return recs if recs else _fallback_recs(brand, visibility)


def build_geo_recommendations(
    report: GeoReport, config: dict[str, Any]
) -> tuple[str, list[AdvisoryRecommendation]]:
    """Return (overall assessment, GEO recommendations) grounded in the real AI answers."""
    brand = report.brand
    mentioned, total, visibility = _visibility(report)

    engine = str(config.get("engine", "mock")).lower()
    mode = str(config.get("openai", {}).get("mode", "live")).lower()

    parsed: dict[str, Any] | None = None
    if mode == "live" and engine != "mock":
        from src.clients import openai_client as _oc
        if _oc._MAX_TOKENS < 1200:
            _oc._MAX_TOKENS = 1200
        try:
            parsed = parse_json_object(_oc.client.chat(_build_prompt(report, visibility)))
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
