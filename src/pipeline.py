"""Pipeline orchestration for combining SEO and GEO engine outputs."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.agents.geo_agent import load_geo_config, run_geo
from src.engine.models import CombinedReport, GeoReport, SiteReport
from src.engine import scoring


def load_pipeline_config(path: str = "config/pipeline_config.yaml") -> dict[str, float]:
    """Load pipeline weights from a YAML file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream) or {}
    return {"seo_weight": float(loaded.get("seo_weight", 0.5)), "geo_weight": float(loaded.get("geo_weight", 0.5))}


def _normalize_weights(weights: dict[str, float]) -> tuple[float, float]:
    seo_weight = weights.get("seo_weight", 0.5)
    geo_weight = weights.get("geo_weight", 0.5)
    total = seo_weight + geo_weight
    if total <= 0:
        return 0.5, 0.5
    return seo_weight / total, geo_weight / total


def _save_combined_report(combined_report: CombinedReport) -> Path:
    report_dir = Path("data/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"combined_report_{timestamp}.json"
    with report_path.open("w", encoding="utf-8") as stream:
        json.dump(asdict(combined_report), stream, indent=2)
    return report_path


def run_pipeline() -> CombinedReport:
    """Run the SEO and GEO engines and combine their scores."""
    pipeline_config = load_pipeline_config()
    seo_config = scoring.load_config()
    weights = scoring.load_weights()

    pages = scoring.crawl(seo_config)
    reports = [scoring.extract_page(page, seo_config) for page in pages]
    for report in reports:
        scoring.score_page(report, weights)

    site_name = seo_config.get("site", {}).get("name", "Unknown Site")
    seo_score = scoring.score_site(reports)
    seo_report = SiteReport(site_name=site_name, pages=reports, score=seo_score)

    geo_config = load_geo_config()
    geo_report = run_geo(geo_config)

    seo_weight, geo_weight = _normalize_weights(pipeline_config)
    unified_score = round(seo_weight * seo_score + geo_weight * geo_report.geo_score, 1)

    combined_report = CombinedReport(
        site_name=site_name,
        seo_score=seo_score,
        geo_score=geo_report.geo_score,
        unified_score=unified_score,
        seo_report=seo_report,
        geo_report=geo_report,
    )
    _save_combined_report(combined_report)
    return combined_report


def main() -> None:
    combined_report = run_pipeline()
    print(f"SEO score: {combined_report.seo_score}%")
    print(f"GEO score: {combined_report.geo_score}%")
    print(f"Unified score: {combined_report.unified_score}%")


if __name__ == "__main__":
    main()
