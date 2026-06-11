"""Data models for factor results, page reports, and site reports."""

from dataclasses import dataclass
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
