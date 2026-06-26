"""Tests for model-specific (per engine/model) GEO measurement.

All offline: only the mock engine runs and competitor extraction is disabled, so no
API keys or network calls are needed. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_geo_engines
"""

from __future__ import annotations

import os

from src.agents.geo_agent import _resolve_engines, overall_grounded_score, run_geo

_QUERIES = [
    "How can I automate repetitive tasks in my startup?",
    "What AI tools help small business founders manage growth?",
    "A query that mentions no brand at all?",
]


def _base(**overrides):
    cfg = {"brand": "Eloize", "queries": _QUERIES, "competitor_extraction": {"enabled": False}}
    cfg.update(overrides)
    return cfg


def test_mock_engine_still_runs() -> None:
    report = run_geo(_base(engine="mock"))
    assert len(report.results) == len(_QUERIES)
    assert all(r.provider == "mock" and r.model == "mock-default" for r in report.results)
    assert report.engine_scores[0]["geo_score"] > 0  # mock produced a per-engine score
    # mock is ungrounded → excluded from the grounded headline average.
    assert report.geo_score == overall_grounded_score(report.engine_scores)


def test_legacy_single_engine_unchanged() -> None:
    # Legacy config (no `engines` list) yields exactly one engine.
    report = run_geo(_base(engine="mock"))
    assert len(report.engine_scores) == 1
    assert report.engine_scores[0]["provider"] == "mock"
    # Overall is the grounded-only average (mock is ungrounded → headline excludes it).
    assert report.geo_score == overall_grounded_score(report.engine_scores)


def test_disabled_engines_are_skipped() -> None:
    cfg = _base(engines=[
        {"provider": "mock", "model": "mock-default", "enabled": True},
        {"provider": "anthropic", "model": "claude-sonnet-4", "enabled": False},
        {"provider": "perplexity", "model": "sonar", "enabled": False},
    ])
    assert _resolve_engines(cfg) == [{"provider": "mock", "model": "mock-default"}]
    report = run_geo(cfg)
    providers = {e["provider"] for e in report.engine_scores}
    assert providers == {"mock"}


def test_multiple_enabled_engines_run() -> None:
    cfg = _base(engines=[
        {"provider": "mock", "model": "mock-default", "enabled": True},
        {"provider": "mock", "model": "mock-alt", "enabled": True},
    ])
    report = run_geo(cfg)
    assert len(report.engine_scores) == 2
    assert {e["model"] for e in report.engine_scores} == {"mock-default", "mock-alt"}
    # Every query ran once per engine.
    assert len(report.results) == 2 * len(_QUERIES)
    assert {(r.provider, r.model) for r in report.results} == {
        ("mock", "mock-default"), ("mock", "mock-alt")
    }


def test_per_engine_scores_and_overall_is_average() -> None:
    cfg = _base(engines=[
        {"provider": "mock", "model": "mock-default", "enabled": True},
        {"provider": "mock", "model": "mock-alt", "enabled": True},
    ])
    report = run_geo(cfg)
    ran = [e["geo_score"] for e in report.engine_scores if e.get("error") is None and e["queries_run"]]
    assert len(ran) == 2, "both enabled mock engines should produce a score"
    # Overall is the grounded-only average (both mock engines ungrounded → 0.0).
    assert report.geo_score == overall_grounded_score(report.engine_scores)
    # Each engine entry carries the documented breakdown fields incl. grounding.
    for e in report.engine_scores:
        for key in ("provider", "model", "geo_score", "visibility_rate", "queries_run",
                    "brand_mentions", "avg_prominence", "web_grounded", "sources_count"):
            assert key in e


def test_enabled_engine_without_key_errors_without_crashing() -> None:
    # All providers are implemented now; an enabled provider with NO API key must fail
    # loudly (naming its env var) without crashing the rest of the run.
    os.environ.pop("PERPLEXITY_API_KEY", None)
    cfg = _base(engines=[
        {"provider": "mock", "model": "mock-default", "enabled": True},
        {"provider": "perplexity", "model": "sonar", "enabled": True},
    ])
    report = run_geo(cfg)  # must not raise
    perplexity = next(e for e in report.engine_scores if e["provider"] == "perplexity")
    assert perplexity["error"] and "PERPLEXITY_API_KEY" in perplexity["error"]
    # The mock engine still ran; overall excludes the failed (and ungrounded) engines.
    mock = next(e for e in report.engine_scores if e["provider"] == "mock")
    assert mock["queries_run"] == len(_QUERIES)
    assert report.geo_score == overall_grounded_score(report.engine_scores)


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
