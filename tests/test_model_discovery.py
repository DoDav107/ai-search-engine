"""Tests for live model discovery + config fallback in the New Audit "AI model" dropdown.

The provider list-models endpoint is STUBBED (no network), so these run fully offline:

    .venv/bin/python -m tests.test_model_discovery

Covers: hard filtering (chat only, junk excluded, newest first); a brand-new chat model
appearing automatically as "(unverified for GEO)"; silent fallback to the config catalogue
on error/timeout with a note; live_fetch:false pinning (no live call); the disk cache (no
re-fetch within TTL); and the runtime pass-through of an explicit/manual model id.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import src.agents.model_discovery as MD
from src.agents.geo_agent import build_catalog
from src.pipeline import _select_geo_engine

try:
    import pytest

    @pytest.fixture(autouse=True)
    def _restore_globals():
        yield
        _restore()
except ImportError:  # pytest not present when run via __main__
    pass

# A realistic mixed /models payload: chat families + junk that MUST be filtered out.
_MIXED = [
    {"id": "gpt-4o", "created": 1000},
    {"id": "gpt-5.5", "created": 3000},
    {"id": "gpt-6-turbo", "created": 4000},              # brand-new chat model (not curated)
    {"id": "text-embedding-3-large", "created": 2500},   # embeddings -> excluded
    {"id": "gpt-4o-audio-preview", "created": 2600},      # audio -> excluded
    {"id": "whisper-1", "created": 2700},                 # speech -> excluded
    {"id": "dall-e-3", "created": 2800},                  # image -> excluded
    {"id": "omni-moderation-latest", "created": 2900},    # moderation -> excluded
    {"id": "gpt-4o-realtime-preview", "created": 2950},   # realtime -> excluded
    {"id": "ft:gpt-4o:acme:custom", "created": 3500},     # fine-tune -> excluded
    {"id": "gpt-3.5-turbo-instruct", "created": 500},     # legacy completions -> excluded
]

_OPENAI_ALLOW = ["^gpt-", "^o[0-9]", "^chatgpt-"]
_OPENAI_DENY = MD._DEFAULT_DENY


_ORIG_CACHE_DIR = MD.CACHE_DIR
_ORIG_OPENAI_FETCHER = MD._FETCHERS.get("openai")


def _tmp_cache(monkeypatch_dir: Path) -> None:
    MD.CACHE_DIR = monkeypatch_dir  # redirect disk cache so tests never touch real files


def _restore() -> None:
    """Undo global mutations so test order can't leak state under pytest."""
    MD.CACHE_DIR = _ORIG_CACHE_DIR
    if _ORIG_OPENAI_FETCHER is not None:
        MD._FETCHERS["openai"] = _ORIG_OPENAI_FETCHER
    os.environ.pop("OPENAI_API_KEY", None)


def test_filter_keeps_chat_only_newest_first() -> None:
    with tempfile.TemporaryDirectory() as d:
        _tmp_cache(Path(d))
        ids = MD.discover_models(
            "openai", api_key="k", allow=_OPENAI_ALLOW, deny=_OPENAI_DENY,
            ttl_seconds=3600, fetcher=lambda _k: list(_MIXED),
        )
    # Only chat gpt-* survive, ordered by `created` desc.
    assert ids == ["gpt-6-turbo", "gpt-5.5", "gpt-4o"], ids
    for junk in ("text-embedding-3-large", "whisper-1", "dall-e-3", "ft:gpt-4o:acme:custom",
                 "gpt-4o-audio-preview", "gpt-3.5-turbo-instruct", "omni-moderation-latest"):
        assert junk not in ids


def test_new_chat_model_appears_marked_unverified() -> None:
    with tempfile.TemporaryDirectory() as d:
        _tmp_cache(Path(d))
        MD._FETCHERS["openai"] = lambda _k: list(_MIXED)
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            catalog = build_catalog({"engines": [{"provider": "openai", "model": "gpt-5.5"}]},
                                    discover=True)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
    models = {m["id"]: m for m in catalog["providers"]["openai"]["models"]}
    assert catalog["providers"]["openai"]["source"] == "live"
    # Brand-new model auto-appears and is flagged unverified for GEO.
    assert "gpt-6-turbo" in models
    assert models["gpt-6-turbo"]["grounding"] == "unverified"
    assert "(unverified for GEO)" in models["gpt-6-turbo"]["label"]
    # A model in grounding_verified is clean (no scary suffix).
    assert models["gpt-5.5"]["grounding"] == "verified"
    assert "(unverified for GEO)" not in models["gpt-5.5"]["label"]


def test_live_failure_falls_back_to_config_with_note() -> None:
    def _boom(_k):
        raise TimeoutError("list-models timed out")

    with tempfile.TemporaryDirectory() as d:
        _tmp_cache(Path(d))
        MD._FETCHERS["openai"] = _boom
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            catalog = build_catalog({"engines": [{"provider": "openai", "model": "gpt-5.5"}]},
                                    discover=True)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
    prov = catalog["providers"]["openai"]
    assert prov["source"] == "config"
    assert prov["note"] and "live fetch unavailable" in prov["note"]
    # Falls back to the curated config/models.yaml list — form still works.
    assert [m["id"] for m in prov["models"]] == ["gpt-5.5", "gpt-5.2", "gpt-4o"]


def test_live_fetch_false_makes_no_live_call() -> None:
    calls = {"n": 0}

    def _spy(_k):
        calls["n"] += 1
        return list(_MIXED)

    # anthropic is live_fetch:false in config/models.yaml -> curated only, no fetch.
    ids, source, note = MD.resolve_models(
        "anthropic", {"live_fetch": False, "models": ["claude-opus-4-8", "claude-sonnet-4-6"]},
        discover=True, fallback_ids=[], ttl_seconds=3600, api_key="k", fetcher=_spy,
    )
    assert calls["n"] == 0
    assert source == "config" and note is None
    assert ids == ["claude-opus-4-8", "claude-sonnet-4-6"]


def test_disk_cache_prevents_refetch_within_ttl() -> None:
    calls = {"n": 0}

    def _counting(_k):
        calls["n"] += 1
        return list(_MIXED)

    with tempfile.TemporaryDirectory() as d:
        _tmp_cache(Path(d))
        for _ in range(3):  # simulate 3 form opens / page renders within the TTL
            MD.discover_models("openai", api_key="k", allow=_OPENAI_ALLOW, deny=_OPENAI_DENY,
                               ttl_seconds=3600, fetcher=_counting)
    assert calls["n"] == 1, f"expected one live fetch, got {calls['n']}"


def test_discover_false_never_fetches() -> None:
    calls = {"n": 0}
    MD._FETCHERS["openai"] = lambda _k: (calls.__setitem__("n", calls["n"] + 1) or list(_MIXED))
    os.environ["OPENAI_API_KEY"] = "test-key"
    try:
        catalog = build_catalog({"engines": [{"provider": "openai", "model": "gpt-5.5"}]},
                                discover=False)
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
    assert calls["n"] == 0  # runtime/CLI path is offline
    assert catalog["providers"]["openai"]["source"] == "config"


def test_explicit_model_passes_through_for_run() -> None:
    # A bogus/manual id is trusted verbatim so the provider can reject it at run time
    # (clear engine error), instead of being silently swapped for another model.
    config = {"engines": [{"provider": "openai", "model": "gpt-5.5"}],
              "geo": {"default_provider": "openai", "default_model": "gpt-5.5"}}
    provider, model = _select_geo_engine(config, "openai", "totally-bogus-model-xyz")
    assert (provider, model) == ("openai", "totally-bogus-model-xyz")
    # Empty model -> falls back to a real default.
    provider, model = _select_geo_engine(config, "openai", "")
    assert provider == "openai" and model


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failures = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failures += 1; print(f"FAIL  {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1; print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
        finally:
            _restore()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
