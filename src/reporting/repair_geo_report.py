"""Repair saved GEO reports after brand-matching logic changes.

This is offline post-processing only: it reuses captured AI answers and does not
make web or model calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.agents.geo_agent import (
    _norm_key,
    build_competitors_summary,
    build_share_of_voice,
    detect_brand_mentions,
    normalize_competitor_names,
    score_geo,
    sov_headline,
)
from src.engine.models import GeoQueryResult, GeoReport
from src.pipeline import _normalize_weights, load_pipeline_config


def _aliases(payload: dict[str, Any], brand: str) -> list[str]:
    geo = payload.get("geo_report") or {}
    aliases = geo.get("brand_aliases") or payload.get("brand_aliases") or []
    values = [brand, *aliases]
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = _norm_key(text)
        if text and key and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned or [brand]


def repair_payload(payload: dict[str, Any]) -> dict[str, Any]:
    geo = payload.get("geo_report") or {}
    brand = str(geo.get("brand") or payload.get("brand") or "").strip()
    if not brand or not geo.get("results"):
        return payload

    aliases = _aliases(payload, brand)
    alias_keys = {_norm_key(alias) for alias in aliases if _norm_key(alias)}
    results: list[GeoQueryResult] = []

    for raw in geo.get("results") or []:
        result = GeoQueryResult(
            query=raw.get("query", ""),
            engine=raw.get("engine", geo.get("engine", "live")),
            answer=raw.get("answer") or "",
            error=raw.get("error"),
            web_search_used=bool(raw.get("web_search_used")),
            sources=raw.get("sources") or [],
        )
        result.competitors_found = list(raw.get("competitors_found") or [])
        detect_brand_mentions(result, brand, [], aliases=aliases)

        filtered: list[str] = []
        seen_competitors: set[str] = set()
        for name in result.competitors_found:
            key = _norm_key(name)
            if not key or key in alias_keys or key in seen_competitors:
                continue
            seen_competitors.add(key)
            filtered.append(name)
        result.competitors_found = filtered
        results.append(result)

    normalize_competitor_names(results)
    report = GeoReport(brand=brand, engine=geo.get("engine", "live"), results=results)
    report.competitors_summary = build_competitors_summary(results)
    report.share_of_voice = build_share_of_voice(results, brand, aliases)
    report.sov_headline = sov_headline(report.share_of_voice, brand)
    score_geo(report)

    geo["results"] = [result.__dict__ for result in report.results]
    geo["geo_score"] = report.geo_score
    geo["competitors_summary"] = report.competitors_summary
    geo["share_of_voice"] = report.share_of_voice
    geo["sov_headline"] = report.sov_headline
    geo["brand_aliases"] = aliases
    payload["geo_report"] = geo
    payload["geo_score"] = report.geo_score

    try:
        seo_weight, geo_weight = _normalize_weights(load_pipeline_config())
        seo_score = float(payload.get("seo_score") or 0.0)
        payload["unified_score"] = round(seo_weight * seo_score + geo_weight * report.geo_score, 1)
    except Exception:
        pass

    measured = [result for result in report.results if not result.error]
    mentioned = sum(1 for result in measured if result.brand_mentioned)
    visibility = round(mentioned / len(measured) * 100, 1) if measured else 0.0
    payload["geo_assessment"] = (
        f"{brand} is mentioned in {mentioned}/{len(measured)} measured AI answers "
        f"({visibility}% visibility) after normalizing brand variants such as accented, "
        f"spaced, unspaced, and all-caps forms. The GEO score is {report.geo_score}%."
    )
    return payload


def repair_file(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    repaired = repair_payload(payload)
    after = json.dumps(repaired, sort_keys=True, ensure_ascii=False)
    if after == before:
        return False
    path.write_text(json.dumps(repaired, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.paths:
        changed = repair_file(path)
        print(f"{path}: {'repaired' if changed else 'unchanged'}")


if __name__ == "__main__":
    main()
