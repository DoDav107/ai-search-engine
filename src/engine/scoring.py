"""Score SEO factors and aggregate page/site reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .crawler import crawl, load_config
from .extractors import extract_page
from .models import PageReport, SiteReport

_STATUS_POINTS = {
    "pass": 1.0,
    "warn": 0.5,
    "fail": 0.0,
}


def load_weights(path: str = "config/scoring_weights.yaml") -> dict[str, float]:
    """Load scoring weights from a YAML file."""
    weights_path = Path(path)
    with weights_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream) or {}
    return {str(key): float(value) for key, value in loaded.items()}


def score_page(report: PageReport, weights: dict[str, float]) -> float:
    """Score a page report based on factor statuses and configured weights."""
    weighted_score = 0.0
    total_weight = 0.0

    for factor in report.factors:
        points = _STATUS_POINTS.get(factor.status, 0.0)
        weight = weights.get(factor.id, 1.0)
        weighted_score += points * weight
        total_weight += weight

    if total_weight <= 0:
        report.score = 0.0
        return 0.0

    score = round((weighted_score / total_weight) * 100, 1)
    report.score = score
    return score


def score_site(reports: list[PageReport]) -> float:
    """Compute the overall site score from successful page reports."""
    scored_pages = [report for report in reports if report.factors]
    if not scored_pages:
        return 0.0
    total = sum(report.score for report in scored_pages)
    return round(total / len(scored_pages), 1)


def _save_report(site_report: SiteReport) -> Path:
    """Save the site report as a timestamped JSON file in data/reports/."""
    report_dir = Path("data/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"site_report_{timestamp}.json"
    with report_path.open("w", encoding="utf-8") as stream:
        json.dump(asdict(site_report), stream, indent=2)
    return report_path


def main() -> None:
    config = load_config()
    weights = load_weights()
    pages = crawl(config)
    reports = [extract_page(page, config) for page in pages]

    for report in reports:
        score_page(report, weights)

    site_name = config.get("site", {}).get("name", "Unknown Site")
    site_score = score_site(reports)
    site_report = SiteReport(site_name=site_name, pages=reports, score=site_score)
    report_path = _save_report(site_report)

    print(f"Saved site report: {report_path}")
    print("\nPage scores:")
    successful = 0
    skipped = 0
    for report in reports:
        if report.factors:
            print(f"- {report.url}: {report.score}")
            successful += 1
        else:
            error_note = next((page.error for page in pages if page.url == report.url), "fetch failed or no factors")
            print(f"- {report.url}: skipped ({error_note})")
            skipped += 1

    print(f"\nSuccessful pages scored: {successful}")
    print(f"Skipped pages: {skipped}")
    print(f"Overall site score: {site_score}")


if __name__ == "__main__":
    main()
