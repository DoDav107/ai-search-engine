"""Tests that the OpenAI per-run call cap resets at the start of every audit run.

The client is a long-lived module singleton; without a per-run reset its call_count would
accumulate across successive in-process runs (repeated Streamlit New-Audit runs) and
falsely trip the cap. Fully offline. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_call_cap_reset
"""

from __future__ import annotations

import src.agents.geo_agent as G
import src.clients.openai_client as OC


def test_reset_call_count_zeroes() -> None:
    c = OC.client
    if hasattr(c, "call_count"):
        c.call_count = 42
        c.reset_call_count()
        assert c.call_count == 0
    else:  # _MissingOpenAIClient (no key) — reset is a safe no-op
        c.reset_call_count()


def test_run_geo_resets_shared_counter_at_start() -> None:
    if not hasattr(OC.client, "call_count"):
        return  # no key in this env; nothing to reset
    OC.client.call_count = 99  # simulate a leaked counter from a previous run
    G.run_geo({"brand": "X", "queries": ["q"], "competitor_extraction": {"enabled": False},
               "engine": "mock"})
    assert OC.client.call_count == 0


def test_successive_runs_do_not_accumulate() -> None:
    original_client = OC.client
    original_factory = G.create_engine_client

    class _FakeShared:
        def __init__(self) -> None:
            self.call_count = 0

        def reset_call_count(self) -> None:
            self.call_count = 0

        def chat(self, *a, **k):
            self.call_count += 1
            if self.call_count > 150:
                raise RuntimeError("OpenAI call cap reached")
            return ""

    class _StubEngine(G.EngineClient):
        provider = "openai"; model = "gpt-5.5"; api_key_source = "env"; web_grounded = True

        def query(self, p):  # noqa: D401
            return "Nike is great."

        def measure(self, p, locale=None):
            OC.client.chat(); OC.client.chat()  # ~2 browse calls per query
            return {"text": "Nike is a top brand. https://x.com", "web_search_used": True,
                    "sources": [{"url": "https://x.com", "title": ""}],
                    "finish_reason": "", "locale_method": "none"}

    OC.client = _FakeShared()
    G.create_engine_client = lambda *a, **k: _StubEngine()
    try:
        cfg = {"brand": "Nike", "queries": [f"q{i}" for i in range(7)],
               "competitor_extraction": {"enabled": False},
               "engines": [{"provider": "openai", "model": "gpt-5.5", "enabled": True}]}
        OC.client.call_count = 49  # leaked from a "previous" run
        for _ in range(3):
            r = G.run_geo(cfg)
            e = r.engine_scores[0]
            # Each run resets → exactly 7*2 = 14 calls (never 14/28/42), no cap trip.
            assert OC.client.call_count == 14, OC.client.call_count
            assert e["error"] is None and e["geo_score"] > 0
            assert all(not row.error for row in r.results)
    finally:
        OC.client = original_client
        G.create_engine_client = original_factory


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
