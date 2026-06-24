"""Pipeline orchestration for combining SEO and GEO engine outputs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from src.agents.geo_agent import load_geo_config, run_geo
from src.agents.geo_advisor import build_geo_recommendations
from src.agents.drafting_agent import build_seo_recommendations, extract_page_content
from src.engine.models import CombinedReport, GeoReport, SiteReport
from src.engine.recommendations import build_recommendations, _load_recommendation_weights
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
    """Save latest_report.json (the "most recent" pointer) plus an immutable,
    client-scoped, timestamped history copy so past runs are never overwritten.

    asdict() recurses through the nested dataclasses (SiteReport, GeoReport, and the
    DraftedFix recommendations), so the whole payload is JSON-serializable.
    """
    report_dir = Path("data/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(combined_report)

    latest_path = report_dir / "latest_report.json"
    with latest_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)

    # Timestamped, client-scoped history copy (data/reports/history/<client>/<ts>.json).
    # The client name comes from config via the report — never hardcoded.
    client = combined_report.brand or combined_report.site_name or "unknown"
    try:
        from src.reporting.history import save_report_history
        hist_path = save_report_history(payload, client)
        print(f"📁 Saved history copy: {hist_path}")
    except Exception as exc:  # noqa: BLE001 — history must not break the run
        print(f"⚠️  History copy skipped: {exc}")

    # Render the branded PDF from the just-saved JSON (purely offline). Best-effort:
    # a PDF/render failure must never break the pipeline or the JSON report.
    try:
        from src.reporting.pdf_report import build_pdf
        build_pdf(report_path=latest_path, output_path=report_dir / "latest_report.pdf")
    except Exception as exc:  # noqa: BLE001 — PDF is a nice-to-have, not critical
        print(f"⚠️  PDF export skipped: {exc}")

    return latest_path


def build_audit_configs(
    brand: str, base_url: str, queries: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (seo_config, geo_config) for an ad-hoc audit from form inputs.

    Loads the YAML defaults and overrides ONLY the client-specific fields (site name,
    base URL, brand, queries). All operational settings — crawl limits, factors,
    openai/web_search/timeouts/caps, reasoning effort — are inherited from config, so
    nothing client-specific is hardcoded. brand_aliases default to just the brand.
    """
    seo_config = scoring.load_config()
    site = {**seo_config.get("site", {}), "name": brand, "base_url": base_url, "seed_urls": ["/"]}
    seo_config = {**seo_config, "site": site}

    geo_config = load_geo_config()
    geo_config = {**geo_config, "brand": brand, "queries": list(queries), "brand_aliases": [brand]}
    return seo_config, geo_config


def run_pipeline(
    seo_config: dict[str, Any] | None = None,
    geo_config: dict[str, Any] | None = None,
    pipeline_config: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> CombinedReport:
    """Run the SEO and GEO engines and combine their scores.

    Each config defaults to the YAML files (the standard CLI behaviour). Callers (e.g.
    the dashboard's "New Audit" flow) may pass pre-built configs instead — built by
    overriding the loaded YAML, so all operational settings (crawl limits, factors,
    openai/web_search/timeouts/caps) are inherited, not hardcoded. ``progress`` is an
    optional callback receiving phase/step dicts for live UI updates.
    """
    def _emit(event: dict) -> None:
        if progress is not None:
            try:
                progress(event)
            except Exception:  # a UI callback must never break the run
                pass

    pipeline_config = pipeline_config if pipeline_config is not None else load_pipeline_config()
    seo_config = seo_config if seo_config is not None else scoring.load_config()
    weights = weights if weights is not None else scoring.load_weights()

    _emit({"phase": "crawl", "message": "Crawling site and scoring SEO factors…"})
    pages = scoring.crawl(seo_config)
    # Keep each page's crawled content so draft fixes can be grounded in it.
    page_content = {page.url: extract_page_content(page.html) for page in pages}
    reports = [scoring.extract_page(page, seo_config) for page in pages]
    for report in reports:
        scoring.score_page(report, weights)

    site_name = seo_config.get("site", {}).get("name", "Unknown Site")
    seo_score = scoring.score_site(reports)
    seo_report = SiteReport(site_name=site_name, pages=reports, score=seo_score)
    _emit({"phase": "crawl_done", "message": f"Scored {len(reports)} page(s).", "pages": len(reports)})

    geo_config = geo_config if geo_config is not None else load_geo_config()
    _emit({"phase": "geo_start", "message": "Measuring GEO brand visibility…",
           "total": len(geo_config.get("queries", []))})
    geo_report = run_geo(geo_config, progress=progress)

    # Rich advisory recommendations — the pipeline is the single source of truth;
    # the dashboard only reads the saved report.
    _emit({"phase": "recommend", "message": "Building recommendations and draft fixes…"})
    advisory_config = {
        "engine": geo_config.get("engine", "mock"),
        "openai": geo_config.get("openai", {}),
    }
    recommendations = build_recommendations(seo_report, _load_recommendation_weights())
    seo_recommendations = build_seo_recommendations(
        recommendations, advisory_config, page_content=page_content
    )
    geo_assessment, geo_recommendations = build_geo_recommendations(
        geo_report, advisory_config, page_content=page_content
    )

    seo_weight, geo_weight = _normalize_weights(pipeline_config)
    unified_score = round(seo_weight * seo_score + geo_weight * geo_report.geo_score, 1)

    combined_report = CombinedReport(
        site_name=site_name,
        seo_score=seo_score,
        geo_score=geo_report.geo_score,
        unified_score=unified_score,
        seo_report=seo_report,
        geo_report=geo_report,
        brand=geo_config.get("brand", ""),
        seo_recommendations=seo_recommendations,
        geo_recommendations=geo_recommendations,
        geo_assessment=geo_assessment,
    )
    _emit({"phase": "saving", "message": "Saving report (latest + history) and PDF…"})
    _save_combined_report(combined_report)
    _emit({"phase": "done", "message": "Audit complete.",
           "unified_score": unified_score, "seo_score": seo_score, "geo_score": geo_report.geo_score})
    return combined_report


def main() -> None:
    combined_report = run_pipeline()
    print(f"SEO score: {combined_report.seo_score}%")
    print(f"GEO score: {combined_report.geo_score}%")
    print(f"Unified score: {combined_report.unified_score}%")


if __name__ == "__main__":
    main()
