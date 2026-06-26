"""Headless audit runner for the Next.js background-job runner.

Reads ``{"brand","url","queries":[...]}`` as JSON on stdin, runs the SAME pipeline
the Streamlit "New Audit" flow uses (``build_audit_configs`` + ``run_pipeline``), and
streams progress as one JSON object per line on stdout, e.g.:

    {"phase": "geo", "index": 3, "total": 8, "query": "...", "web_search_used": true}
    {"phase": "done", "unified_score": 84.3, ...}

Run unbuffered (``python -u -m src.reporting.run_audit_cli``) so the parent process
sees progress live. Exits non-zero on error (after emitting a ``phase: error`` line).
Diagnose-and-recommend only — it never publishes or changes the live site.
"""

from __future__ import annotations

import json
import sys

MAX_QUERIES = 10


def _emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def main() -> None:
    try:
        params = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        _emit({"phase": "error", "message": f"Invalid JSON input: {exc}"})
        sys.exit(1)

    brand = str(params.get("brand") or "").strip()
    url = str(params.get("url") or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    queries = [str(q).strip() for q in (params.get("queries") or []) if str(q).strip()]
    queries = queries[:MAX_QUERIES]  # enforce the cap server-side too

    if not brand or not url or not queries:
        _emit({"phase": "error", "message": "brand, url and at least one query are required"})
        sys.exit(1)

    try:
        from src.pipeline import build_audit_configs, run_pipeline

        seo_config, geo_config = build_audit_configs(brand, url, queries)
        _emit({"phase": "start", "brand": brand, "url": url, "total": len(queries)})
        run_pipeline(seo_config=seo_config, geo_config=geo_config, progress=_emit)
        # run_pipeline emits its own {"phase": "done", ...}
    except Exception as exc:  # noqa: BLE001 — surface any failure as a structured event
        _emit({"phase": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
