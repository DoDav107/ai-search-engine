"""Build deterministic SEO recommendation lists from analysis reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .models import Recommendation, SiteReport
from . import scoring


_SEVERITY_WEIGHT = {
    "fail": 2.0,
    "warn": 1.0,
}


def _sitewide_message(factor: str, count: int) -> str:
    templates = {
        "title": "Title tags need attention on {count} pages — standardise title length site-wide for better search listing performance.",
        "meta_description": "Meta descriptions need improvement on {count} pages — create descriptive summaries site-wide for stronger SERP snippets.",
        "h1": "Heading structure is inconsistent on {count} pages — use a single H1 per page site-wide for clearer page hierarchy.",
        "canonical": "Canonical tags are missing or incorrect on {count} pages — add canonical URLs site-wide to avoid duplicate content issues.",
        "image_alt": "Image alt coverage is low on {count} pages — improve ALT text site-wide for SEO and accessibility.",
        "word_count": "Content is too short on {count} pages — add more useful copy site-wide to avoid thin content penalties.",
        "structured_data": "Structured data is absent on {count} pages — add JSON-LD markup site-wide to improve search engine understanding.",
    }
    return templates.get(factor, "Issue found on {count} pages — address this SEO factor site-wide.").format(count=count)


def build_recommendations(site_report: SiteReport, weights: dict[str, float]) -> list[Recommendation]:
    """Build a sorted list of recommendations from a site report."""
    factor_groups: dict[str, dict[str, Any]] = {}

    for page in site_report.pages:
        for factor in page.factors:
            if factor.status not in {"warn", "fail"}:
                continue

            group = factor_groups.setdefault(factor.id, {
                "severity": "warn",
                "affected_urls": [],
                "messages": [],
            })
            if factor.status == "fail":
                group["severity"] = "fail"
            if page.url not in group["affected_urls"]:
                group["affected_urls"].append(page.url)
            group["messages"].append(factor.message)

    recommendations: list[Recommendation] = []
    for factor_id, group in factor_groups.items():
        affected_urls = group["affected_urls"]
        severity = group["severity"]
        scope = "site-wide" if len(affected_urls) > 1 else "page"
        if scope == "site-wide":
            message = _sitewide_message(factor_id, len(affected_urls))
        else:
            message = group["messages"][0] if group["messages"] else _sitewide_message(factor_id, 1)

        priority = _SEVERITY_WEIGHT.get(severity, 1.0) * float(weights.get(factor_id, 1.0))
        recommendations.append(Recommendation(
            factor=factor_id,
            severity=severity,
            message=message,
            affected_urls=affected_urls,
            scope=scope,
            priority=priority,
        ))

    recommendations.sort(key=lambda rec: (-rec.priority, -len(rec.affected_urls), rec.factor))
    return recommendations


def _save_recommendations(recommendations: list[Recommendation]) -> Path:
    report_dir = Path("data/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"recommendations_{timestamp}.json"
    with report_path.open("w", encoding="utf-8") as stream:
        json.dump([asdict(rec) for rec in recommendations], stream, indent=2)
    return report_path


def _load_recommendation_weights(path: str = "config/scoring_weights.yaml") -> dict[str, float]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream) or {}
    return {str(key): float(value) for key, value in loaded.items()}


def _build_site_report() -> SiteReport:
    seo_config = scoring.load_config()
    weights = scoring.load_weights()
    pages = scoring.crawl(seo_config)
    reports = [scoring.extract_page(page, seo_config) for page in pages]
    for report in reports:
        scoring.score_page(report, weights)
    site_score = scoring.score_site(reports)
    return SiteReport(site_name=seo_config.get("site", {}).get("name", "Unknown Site"), pages=reports, score=site_score)


def main() -> None:
    site_report = _build_site_report()
    weights = _load_recommendation_weights()
    recommendations = build_recommendations(site_report, weights)
    report_path = _save_recommendations(recommendations)

    print(f"Saved recommendations: {report_path}\n")
    print("Recommendations:")
    for rec in recommendations:
        print(f"- [{rec.priority:.1f}] {rec.factor} ({rec.severity}, {rec.scope}, {len(rec.affected_urls)} page(s))")
        print(f"  {rec.message}\n")


if __name__ == "__main__":
    main()
