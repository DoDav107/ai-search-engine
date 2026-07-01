"""Tests for the 'engine returned no usable answer' path (not a real 0%).

Fully offline: stub EngineClients simulate empty/failed live calls. Runnable under pytest
OR directly:

    .venv/bin/python -m tests.test_geo_empty_answer
"""

from __future__ import annotations

import src.agents.geo_agent as G
from src.agents.geo_agent import EngineClient, run_geo

_CFG = {
    "brand": "Nike",
    "queries": ["best running shoes?", "best sneakers?"],
    "competitor_extraction": {"enabled": False},
    "engines": [{"provider": "openai", "model": "gpt-5.5", "enabled": True}],
}


class _StubEmpty(EngineClient):
    provider = "openai"; model = "gpt-5.5"; api_key_source = "env"; web_grounded = True

    def query(self, p): return ""

    def measure(self, p, locale=None):
        # Succeeds (no exception) but returns empty text with a truncation reason.
        return {"text": "", "web_search_used": False, "sources": [],
                "finish_reason": "incomplete, reason=max_output_tokens, output_tokens=2000",
                "locale_method": "none"}


class _StubBadKey(EngineClient):
    provider = "openai"; model = "gpt-5.5"; api_key_source = "env"; web_grounded = True

    def query(self, p): return ""

    def measure(self, p, locale=None):
        raise RuntimeError("OpenAI authentication failed — check OPENAI_API_KEY")


def _run_with(stub_cls, monkeypatch_target=G):
    original = G.create_engine_client
    G.create_engine_client = lambda *a, **k: stub_cls()
    try:
        return run_geo(_CFG)
    finally:
        G.create_engine_client = original


def test_empty_answers_flag_engine_error_not_fake_zero() -> None:
    r = _run_with(_StubEmpty)
    e = r.engine_scores[0]
    # Every query errored → engine is flagged as failed (not a silent 0%).
    assert e["error"] and "no usable answer" in e["error"]
    # The actionable finish reason is carried through (raise the token budget).
    assert "max_output_tokens" in e["error"]
    # No misleading quality block ("0 of 0") for a fully-failed engine.
    assert e["quality"] is None
    # Per-query rows carry the real reason, not a generic "empty completion".
    assert all(row.error and "max_output_tokens" in row.error for row in r.results)


def test_bad_key_shows_engine_error() -> None:
    r = _run_with(_StubBadKey)
    e = r.engine_scores[0]
    assert e["error"] and "no usable answer" in e["error"]
    assert "authentication failed" in e["error"]
    assert e["quality"] is None


def test_successful_answers_keep_quality_and_no_error() -> None:
    class _StubGood(EngineClient):
        provider = "openai"; model = "gpt-5.5"; api_key_source = "env"; web_grounded = True
        def query(self, p): return "Nike and Adidas are top brands."
        def measure(self, p, locale=None):
            return {"text": "Nike and Adidas are top running shoe brands. https://x.com",
                    "web_search_used": True, "sources": [{"url": "https://x.com", "title": ""}],
                    "finish_reason": "", "locale_method": "none"}

    r = _run_with(_StubGood)
    e = r.engine_scores[0]
    assert e["error"] is None
    assert e["quality"] is not None and e["quality"]["answers_total"] == 2  # real answers


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failures += 1; print(f"FAIL  {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1; print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
