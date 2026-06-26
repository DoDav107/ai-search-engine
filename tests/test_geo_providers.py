"""Tests for multi-provider GEO engines + mandatory web-search grounding.

Offline: clients are only CONSTRUCTED (no .measure() calls), so no network/keys are
hit beyond a dummy env var. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_geo_providers
"""

from __future__ import annotations

import os

from src.agents.geo_agent import (
    SUPPORTS_WEB_SEARCH,
    OpenAIEngineClient,
    create_engine_client,
    overall_grounded_score,
    run_geo,
)

_NEW_PROVIDERS = {
    "google": ("GOOGLE_API_KEY", "gemini-3-pro"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek-chat"),
    "xai": ("XAI_API_KEY", "grok-4"),
    "anthropic": ("ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
    "perplexity": ("PERPLEXITY_API_KEY", "sonar"),
}


def test_new_providers_instantiate_via_factory() -> None:
    for provider, (env, model) in _NEW_PROVIDERS.items():
        os.environ[env] = "test-key"
        try:
            client = create_engine_client(provider, model)
            assert client.provider == provider
            assert client.model == model
            # Grounding must match the capability map (mandatory where supported).
            assert client.web_grounded == SUPPORTS_WEB_SEARCH[provider]
        finally:
            os.environ.pop(env, None)


def test_enabled_but_missing_key_raises_naming_env_var() -> None:
    for provider, (env, model) in _NEW_PROVIDERS.items():
        os.environ.pop(env, None)
        try:
            create_engine_client(provider, model)
            raise AssertionError(f"{provider} should have raised for a missing key")
        except RuntimeError as exc:
            assert env in str(exc), f"{provider} error should name {env}"


def test_search_capable_without_grounding_raises() -> None:
    # OpenAI supports web search → constructing with web_search disabled must fail loudly.
    try:
        OpenAIEngineClient(model="gpt-4o", web_search_cfg={"enabled": False})
        raise AssertionError("OpenAI without grounding should have raised")
    except RuntimeError as exc:
        assert "grounding is mandatory" in str(exc)


def test_disabled_engines_are_skipped() -> None:
    cfg = {
        "brand": "Eloize",
        "queries": ["How can I automate repetitive tasks in my startup?"],
        "competitor_extraction": {"enabled": False},
        "engines": [
            {"provider": "mock", "model": "mock-default", "enabled": True},
            {"provider": "google", "model": "gemini-3-pro", "enabled": False},
            {"provider": "xai", "model": "grok-4", "enabled": False},
        ],
    }
    report = run_geo(cfg)
    providers = {e["provider"] for e in report.engine_scores}
    assert providers == {"mock"}  # disabled google/xai never ran


def test_ungrounded_excluded_from_headline_average() -> None:
    engine_scores = [
        {"provider": "openai", "model": "gpt-4o", "geo_score": 80.0, "queries_run": 4, "web_grounded": True, "error": None},
        {"provider": "perplexity", "model": "sonar", "geo_score": 60.0, "queries_run": 4, "web_grounded": True, "error": None},
        {"provider": "deepseek", "model": "deepseek-chat", "geo_score": 10.0, "queries_run": 4, "web_grounded": False, "error": None},
    ]
    # (80 + 60) / 2 = 70.0 — DeepSeek (ungrounded) excluded.
    assert overall_grounded_score(engine_scores) == 70.0


def test_mock_only_run_has_grounding_fields_and_zero_headline() -> None:
    cfg = {
        "brand": "Eloize",
        "queries": ["How can I automate repetitive tasks in my startup?"],
        "competitor_extraction": {"enabled": False},
        "engines": [{"provider": "mock", "model": "mock-default", "enabled": True}],
    }
    report = run_geo(cfg)
    row = report.engine_scores[0]
    assert row["web_grounded"] is False and "sources_count" in row
    assert all(hasattr(r, "web_grounded") and hasattr(r, "sources_count") for r in report.results)
    # Mock is ungrounded → excluded from the grounded headline → 0.0.
    assert report.geo_score == 0.0


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
