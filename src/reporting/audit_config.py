"""Write per-job pipeline config files for dashboard-started audits."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

MAX_QUERIES = 10


def _normalize_url(value: str) -> str:
    value = (value or "").strip()
    if value and "://" not in value:
        value = "https://" + value
    return value


def _validate(params: dict[str, Any]) -> tuple[str, str, str, list[str], str | None, str | None, str | None, str, list[str]]:
    errors: list[str] = []
    client = str(params.get("client") or "").strip()
    brand = str(params.get("brand") or "").strip()
    domain = _normalize_url(str(params.get("domain") or params.get("url") or ""))
    queries = [str(q).strip() for q in (params.get("queries") or []) if str(q).strip()]
    geo_provider = str(params.get("geo_provider") or "").strip().lower() or None
    geo_model = str(params.get("geo_model") or "").strip() or None
    geo_locale = str(params.get("geo_locale") or "").strip() or None
    api_key_mode = str(params.get("api_key_mode") or "env").strip().lower()

    if not client:
        errors.append("client is required")
    if not brand:
        errors.append("brand is required")
    parsed = urlparse(domain)
    if not (parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc):
        errors.append("domain must be a valid http(s) URL")
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
