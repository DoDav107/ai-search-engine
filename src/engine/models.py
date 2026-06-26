"""Data models for factor results, page reports, and site reports."""

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class FactorResult:
    id: str
    status: str
    value: Any
    message: str


@dataclass
class PageReport:
    url: str
    factors: List[FactorResult]
    score: float
    error: str | None = None


@dataclass
class SiteReport:
    site_name: str
    pages: List[PageReport]
    score: float


@dataclass
class CrawledPage:
    url: str
    status_code: int | None
    html: str | None
    error: str | None = None


@dataclass
class GeoQueryResult:
    query: str
    engine: str
    answer: str
    error: str | None = None
    brand_mentioned: bool = False
    mention_count: int = 0
    first_position: int | None = None
    competitors_found: List[str] = field(default_factory=list)
    # True only if the measurement call actually browsed (web_search tool call or
    # citations). Distinguishes a real "browsed, brand absent" from a no-browse/error.
    web_search_used: bool = False
    # url_citation annotations returned by the measurement call: [{"url","title"}].
    sources: List[dict] = field(default_factory=list)
    # Whether this engine ran with live web-search grounding active.
    web_grounded: bool = False
    # Number of live citations/source links returned for this query.
    sources_count: int = 0
    # Which AI engine/model produced this answer (e.g. "openai" / "gpt-5.5").
    # Visibility differs across ChatGPT, Claude, Perplexity, etc.
    provider: str = ""
    model: str = ""
    api_key_source: str = "none"
    # Prominence (0..1) of the brand's first mention in the answer; None if absent/error.
    prominence_score: float | None = None
    # Locale grounding actually applied to this query's web search. ``locale_applied`` is
    # an ISO country code (e.g. "AU") or "global" (no region grounding). ``locale_method``
    # records HOW it was applied: native search param, query-text suffix, or none.
    locale_applied: str = "global"
    locale_method: str = "none"  # native_param | query_suffix | none

    # ----- GEO quality signals (rule-based; see geo_agent.analyze_quality_signals) -----
    # Sentiment of the brand mention.
    sentiment_label: str = "unknown"          # positive | neutral | negative | unknown
    sentiment_score: float = 0.0              # -1.0 .. 1.0
    # How strongly the answer recommends the brand.
    recommendation_strength: str = "unknown"  # strong | moderate | weak | none | unknown
    recommendation_score: float = 0.0         # 0.0 .. 1.0
    # Estimated rank of the brand among listed options (1-based); None if not inferable.
    brand_rank_position: int | None = None
    # Competitors surfaced alongside the brand (mirrors competitors_found).
    competitor_count: int = 0
    competitor_names_mentioned: List[str] = field(default_factory=list)
    # Citations / source links detected in the answer (or returned via `sources`).
    citation_count: int = 0
    citations_present: bool = False
    # Whether the answer is accurate about the brand (placeholder; not LLM-evaluated yet).
    answer_accuracy_label: str = "unknown"    # accurate | partially_accurate | inaccurate | unknown
    answer_accuracy_notes: str | None = None
    # Richer per-query GEO score (0..100) combining the signals above; None if errored.
    per_query_geo_score: float | None = None


@dataclass
class GeoReport:
    brand: str
    engine: str
    results: List["GeoQueryResult"]
    geo_score: float = 0.0
    # Ranked aggregate of rival brands surfaced across queries:
    # [{"name": "Adidas", "query_count": 6}, ...] sorted by query_count desc.
    competitors_summary: List[dict] = field(default_factory=list)
    # Share of Voice by presence — subject + competitors ranked by the share of
    # measured queries each appears in:
    # [{"brand": "Nike", "is_subject": true, "queries_present": 8, "share": 1.0}, ...]
    share_of_voice: List[dict] = field(default_factory=list)
    # Punchy headline, e.g. "Nike ranks 1st of 12 brands by Share of Voice".
    sov_headline: str = ""
    # Per engine/model GEO breakdown — brand visibility differs across AI engines:
    # [{"provider": "openai", "model": "gpt-5.5", "geo_score": 61.2,
    #   "visibility_rate": 0.83, "queries_run": 8, "brand_mentions": 7,
    #   "avg_prominence": 0.74, "error": null}, ...]. overall geo_score is the
    # average of the per-engine scores.
    engine_scores: List[dict] = field(default_factory=list)


@dataclass
class CombinedReport:
    site_name: str
    seo_score: float
    geo_score: float
    unified_score: float
    seo_report: SiteReport
    geo_report: GeoReport
    brand: str = ""
    client: str = ""
    seo_recommendations: List["AdvisoryRecommendation"] = field(default_factory=list)
    geo_recommendations: List["AdvisoryRecommendation"] = field(default_factory=list)
    geo_assessment: str = ""
    audit_settings: dict = field(default_factory=dict)


@dataclass
class Recommendation:
    factor: str
    severity: str
    message: str
    affected_urls: List[str]
    scope: str
    priority: float


@dataclass
class DraftedFix:
    """A review-ready draft fix for a recommendation — never auto-applied."""
    recommendation: Recommendation
    draft: str
    status: str = "pending_review"


@dataclass
class AdvisoryRecommendation:
    """A professional advisory recommendation for the SEO or GEO section."""
    area: str            # "SEO" | "GEO"
    title: str
    priority: str        # "High" | "Medium" | "Low"
    scope: str
    issue: str
    why_it_matters: str
    recommendation: str
    draft: str = ""      # SEO only — ready-to-apply content
