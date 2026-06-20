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


@dataclass
class GeoReport:
    brand: str
    engine: str
    results: List["GeoQueryResult"]
    geo_score: float = 0.0


@dataclass
class CombinedReport:
    site_name: str
    seo_score: float
    geo_score: float
    unified_score: float
    seo_report: SiteReport
    geo_report: GeoReport
    brand: str = ""
    recommendations: List["DraftedFix"] = field(default_factory=list)


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
