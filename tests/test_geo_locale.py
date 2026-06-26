"""Tests for per-query locale grounding (resolution, normalization, suffix fallback).

Fully offline (no API). Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_geo_locale
"""

from __future__ import annotations

from src.agents.geo_agent import (
    _localized_question,
    _normalize_locale,
    audit_default_locale,
    normalize_queries,
    run_geo,
)


def test_normalize_locale_forms() -> None:
    assert _normalize_locale("AU") == {"country": "AU", "region": "Australia"}
    assert _normalize_locale("au") == {"country": "AU", "region": "Australia"}
    # Unknown code still grounds (region falls back to the code itself).
    assert _normalize_locale("XX") == {"country": "XX", "region": "XX"}
    # Explicit global / empty / None → no grounding.
    assert _normalize_locale("global") is None
    assert _normalize_locale("") is None
    assert _normalize_locale(None) is None
    # Dict form, region auto-filled from the code.
    assert _normalize_locale({"country": "GB"}) == {"country": "GB", "region": "the United Kingdom"}
    assert _normalize_locale({"country": "AU", "region": "Sydney"}) == {"country": "AU", "region": "Sydney"}


def test_audit_default_locale_sources() -> None:
    assert audit_default_locale({"geo": {"locale": {"country": "AU"}}}) == {"country": "AU", "region": "Australia"}
    assert audit_default_locale({"locale": "US"}) == {"country": "US", "region": "the United States"}
    assert audit_default_locale({}) is None
    assert audit_default_locale({"geo": {}}) is None


def test_query_resolution_precedence() -> None:
    audit = {"country": "AU", "region": "Australia"}
    resolved = normalize_queries(
        [
            "plain inherits default",                                # → AU
            {"text": "explicit US", "locale": "US"},                 # → US (override)
            {"text": "explicit global", "locale": "global"},         # → None (global)
            {"text": "no locale key inherits", "model": "x"},        # → AU (no override key)
        ],
        audit,
    )
    assert resolved[0]["locale"] == audit
    assert resolved[1]["locale"] == {"country": "US", "region": "the United States"}
    assert resolved[2]["locale"] is None
    assert resolved[3]["locale"] == audit


def test_no_audit_default_means_global() -> None:
    resolved = normalize_queries(["a", {"text": "b", "locale": "NZ"}], None)
    assert resolved[0]["locale"] is None  # plain string, no default → global
    assert resolved[1]["locale"] == {"country": "NZ", "region": "New Zealand"}


def test_localized_question_suffix() -> None:
    assert _localized_question("best chicken near me", {"country": "AU", "region": "Australia"}) == \
        "best chicken near me in Australia"
    # Global (None) leaves the question untouched.
    assert _localized_question("most popular sneakers", None) == "most popular sneakers"


def test_empty_and_blank_queries_dropped() -> None:
    resolved = normalize_queries(["ok", "", {"text": "  "}, {"text": "good"}], None)
    assert [r["text"] for r in resolved] == ["ok", "good"]


def test_run_geo_records_locale_per_query() -> None:
    cfg = {
        "brand": "Nandos",
        "queries": [
            "best chicken near me",                                  # inherits AU default
            {"text": "most popular sneakers", "locale": "global"},   # explicit global
        ],
        "competitor_extraction": {"enabled": False},
        "engine": "mock",
        "geo": {"locale": {"country": "AU", "region": "Australia"}},
    }
    report = run_geo(cfg)
    by_query = {r.query: (r.locale_applied, r.locale_method) for r in report.results}
    assert by_query["best chicken near me"] == ("AU", "none")          # mock doesn't browse
    assert by_query["most popular sneakers"] == ("global", "none")


def test_backward_compat_no_locale_is_global() -> None:
    # Legacy config (no geo.locale, plain-string queries) → every query is global.
    cfg = {
        "brand": "Eloize",
        "queries": ["How can I automate tasks?", "A query with no brand?"],
        "competitor_extraction": {"enabled": False},
        "engine": "mock",
    }
    report = run_geo(cfg)
    assert all(r.locale_applied == "global" and r.locale_method == "none" for r in report.results)


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
