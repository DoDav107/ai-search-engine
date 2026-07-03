"""Tests for the curated CONSUMER model catalogue behind the New Audit "AI model" dropdown.

Both dashboards read ONE shared source (geo_agent.build_catalog ← config/models.yaml), so
these assertions hold for BOTH surfaces. Fully offline (no provider calls). Runnable under
pytest OR directly:

    .venv/bin/python -m tests.test_model_catalog
"""

from __future__ import annotations

from src.agents.geo_agent import _load_models_config, build_catalog

# The dropdown provider set (mock stays backend-only via ui_selectable=False).
_CFG = {"engines": [{"provider": "mock", "model": "mock-default"}]}


def _openai_models() -> list[dict]:
    return build_catalog(_CFG)["providers"]["openai"]["models"]


def test_dropdown_shows_clean_consumer_labels_not_api_noise() -> None:
    cat = build_catalog(_CFG)
    labels = [m["label"] for m in cat["providers"]["openai"]["models"]]
    ids = [m["id"] for m in cat["providers"]["openai"]["models"]]
    # Consumer names are shown…
    assert "GPT-5.5" in labels
    # …and the raw /models API noise is NOT present (dated snapshots, codex, nano, embeddings).
    joined = " ".join(labels + ids).lower()
    for noise in ("codex", "nano", "embedding", "audio", "realtime", "2026-", "-preview"):
        assert noise not in joined, f"unexpected API noise in dropdown: {noise}"
    # A short curated list, not a 60+ dump.
    assert len(labels) <= 8


def test_default_is_flagship_and_first() -> None:
    cat = build_catalog(_CFG)
    assert cat["default_provider"] == "openai"
    assert cat["default_model"] == "gpt-5.5"  # api_id of the default:true entry
    # Ordered flagship-first so both forms pre-select it as models[0].
    assert _openai_models()[0]["id"] == "gpt-5.5"
    assert _openai_models()[0]["label"] == "GPT-5.5"


def test_label_maps_to_real_api_id_submitted_under_the_hood() -> None:
    by_label = {m["label"]: m["id"] for m in _openai_models()}
    # Selecting "GPT-5.5" submits api_id gpt-5.5 (label rendered, id submitted).
    assert by_label["GPT-5.5"] == "gpt-5.5"
    assert by_label["GPT-4o"] == "gpt-4o"


def test_non_grounding_model_is_clearly_marked() -> None:
    o3 = next(m for m in _openai_models() if m["id"] == "o3")
    assert o3["grounding"] == "no"
    assert "no GEO grounding" in o3["label"].lower() or "(no geo grounding)" in o3["label"].lower()
    # An ungrounded provider (deepseek) marks its models too.
    ds = build_catalog(_CFG)["providers"]["deepseek"]["models"][0]
    assert ds["grounding"] == "no" and "grounding" in ds["label"].lower()


def test_adding_a_model_to_config_appears_with_no_code_change(monkeypatch) -> None:
    # Simulate a provider launch: inject a new catalogue entry and rebuild — it just appears
    # (both forms read this same build_catalog output, so it shows on both surfaces).
    real = _load_models_config()
    real["providers"]["openai"]["models"].append(
        {"label": "GPT-6", "api_id": "gpt-6", "grounding": True})
    monkeypatch.setattr("src.agents.geo_agent._load_models_config", lambda: real)

    models = _openai_models()
    assert any(m["id"] == "gpt-6" and m["label"] == "GPT-6" for m in models)


def test_retired_api_id_produces_actionable_error_on_run() -> None:
    # The run-time safety net: a provider rejecting a retired id -> clear "update config"
    # message, never a generic error or silent 0%. Stubbed, no live call.
    import openai

    from src.clients.openai_client import _model_availability_error

    exc = openai.NotFoundError.__new__(openai.NotFoundError)  # avoid httpx plumbing
    Exception.__init__(exc, "The model `gpt-legacy` does not exist")
    err = _model_availability_error(exc, "gpt-legacy")
    assert err is not None
    msg = str(err).lower()
    assert "gpt-legacy" in msg and "config/models.yaml" in msg
    # A non-model error is left alone (returns None -> caller keeps generic handling).
    assert _model_availability_error(openai.OpenAIError("boom"), "gpt-5.5") is None


def test_both_surfaces_read_the_same_catalog_via_geo_options() -> None:
    # geo_options (Streamlit direct + Next.js /api/audit/options) wraps the SAME build_catalog.
    from src.reporting.geo_options import load_geo_options

    opts = load_geo_options()
    labels = [m["label"] for m in opts["providers"]["openai"]["models"]]
    assert "GPT-5.5" in labels
    assert opts["default_model"] == "gpt-5.5"
    # mock is present but not user-selectable.
    assert opts["providers"]["mock"]["ui_selectable"] is False


def _main() -> int:
    import types

    class _MP:  # tiny monkeypatch shim for direct (non-pytest) runs
        def __init__(self) -> None:
            self._undo: list = []

        def setattr(self, target: str, value) -> None:
            mod_name, attr = target.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(mod_name)
            self._undo.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, value)

        def undo(self) -> None:
            for mod, attr, old in reversed(self._undo):
                setattr(mod, attr, old)

    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and isinstance(o, types.FunctionType)]
    failures = 0
    for name, t in tests:
        mp = _MP()
        try:
            t(mp) if "monkeypatch" in t.__code__.co_varnames else t()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failures += 1; print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1; print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        finally:
            mp.undo()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
