"""Write per-job pipeline config files for dashboard-started audits."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from src.engine.url_utils import normalise_site_url

MAX_QUERIES = 10


def _validate(params: dict[str, Any]) -> tuple[str, str, str, list[str], str | None, str | None, str | None, str, list[str]]:
    errors: list[str] = []
    client = str(params.get("client") or "").strip()
    brand = str(params.get("brand") or "").strip()
    # Shared normaliser (same as Streamlit + the crawl entry) — clean URL, strip tracking.
    raw_domain = str(params.get("domain") or params.get("url") or "")
    try:
        domain = normalise_site_url(raw_domain)
    except ValueError as exc:
        domain = raw_domain.strip()
        errors.append(str(exc))
    queries = [str(q).strip() for q in (params.get("queries") or []) if str(q).strip()]
    geo_provider = str(params.get("geo_provider") or "").strip().lower() or None
    geo_model = str(params.get("geo_model") or "").strip() or None
    # Guard the model id shape (covers the advanced "manual model id" entry) before a run.
    # The provider still validates it authoritatively at run time; this just rejects
    # obviously malformed input early with a clear message.
    if geo_model and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}", geo_model):
        errors.append("geo_model has an invalid format")
    geo_locale = str(params.get("geo_locale") or "").strip() or None
    api_key_mode = str(params.get("api_key_mode") or "env").strip().lower()

    if not client:
        errors.append("client is required")
    if not brand:
        errors.append("brand is required")
    if not queries:
        errors.append("at least one query is required")
    if len(queries) > MAX_QUERIES:
        errors.append(f"too many queries ({len(queries)}); max is {MAX_QUERIES}")
    if api_key_mode not in {"env", "temporary"}:
        errors.append("api_key_mode must be 'env' or 'temporary'")

    return client, brand, domain, queries, geo_provider, geo_model, geo_locale, api_key_mode, errors


def write_audit_configs(params: dict[str, Any], crawl_out: Path, geo_out: Path) -> None:
    """Build dashboard audit configs using the same override path as Streamlit."""
    client, brand, domain, queries, geo_provider, geo_model, geo_locale, api_key_mode, errors = _validate(params)
    if errors:
        raise ValueError("; ".join(errors))

    from src.pipeline import build_audit_configs

    seo_config, geo_config = build_audit_configs(
        client=client,
        brand=brand,
        base_url=domain,
        queries=queries,
        geo_provider=geo_provider,
        geo_model=geo_model,
        geo_locale=geo_locale,
        api_key_source="temporary" if api_key_mode == "temporary" else "env",
    )
    crawl_out.parent.mkdir(parents=True, exist_ok=True)
    geo_out.parent.mkdir(parents=True, exist_ok=True)
    crawl_out.write_text(yaml.safe_dump(seo_config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    geo_out.write_text(yaml.safe_dump(geo_config, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crawl-out", required=True)
    parser.add_argument("--geo-out", required=True)
    args = parser.parse_args()

    try:
        params = json.loads(sys.stdin.read() or "{}")
        write_audit_configs(params, Path(args.crawl_out), Path(args.geo_out))
    except Exception as exc:  # noqa: BLE001 - surface concise setup failures to Next.js
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
