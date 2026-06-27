"""Tests for the opt-in server-side env-key writer guardrails (src.reporting.env_key).

Fully offline. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_env_key
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.reporting import env_key


def _with_env(tmp_env: Path, *, allow: bool):
    """Point the writer at a temp .env and set the gate flag in the process env."""
    env_key.ENV_PATH = tmp_env
    if allow:
        os.environ["ALLOW_ENV_KEY_WRITE"] = "true"
    else:
        os.environ.pop("ALLOW_ENV_KEY_WRITE", None)


def test_refused_when_flag_off() -> None:
    d = Path(tempfile.mkdtemp()); env = d / ".env"
    env.write_text("OPENAI_API_KEY=sk-original\n", encoding="utf-8")
    _with_env(env, allow=False)
    res = env_key.save_provider_key("openai", "sk-newkey1234567890")
    assert res["ok"] is False and "disabled" in res["message"].lower()
    # File untouched.
    assert env.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-original\n"


def test_unknown_provider_rejected() -> None:
    d = Path(tempfile.mkdtemp()); env = d / ".env"; env.write_text("", encoding="utf-8")
    _with_env(env, allow=True)
    res = env_key.save_provider_key("bogus", "sk-newkey1234567890")
    assert res["ok"] is False and "unknown provider" in res["message"].lower()


def test_invalid_key_format_rejected() -> None:
    d = Path(tempfile.mkdtemp()); env = d / ".env"; env.write_text("", encoding="utf-8")
    _with_env(env, allow=True)
    for bad in ("short", "has space inside", "with\nnewline", "x" * 600, 'quote"d'):
        res = env_key.save_provider_key("openai", bad)
        assert res["ok"] is False, f"should reject {bad!r}"


def test_writes_only_target_line_and_never_returns_key() -> None:
    d = Path(tempfile.mkdtemp()); env = d / ".env"
    env.write_text("# comment\nOPENAI_API_KEY=sk-keepme\nOTHER=value\n", encoding="utf-8")
    _with_env(env, allow=True)
    secret = "sk-ant-FAKEtestkey1234567890"
    res = env_key.save_provider_key("anthropic", secret)
    assert res["ok"] is True and res["env_var"] == "ANTHROPIC_API_KEY"
    # The result NEVER contains the key.
    assert secret not in repr(res)
    body = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-keepme" in body  # untouched
    assert "OTHER=value" in body               # untouched
    assert "# comment" in body                 # untouched
    assert f"ANTHROPIC_API_KEY={secret}" in body  # added once
    assert body.count("ANTHROPIC_API_KEY=") == 1


def test_updates_existing_line_in_place() -> None:
    d = Path(tempfile.mkdtemp()); env = d / ".env"
    env.write_text("OPENAI_API_KEY=sk-old\n", encoding="utf-8")
    _with_env(env, allow=True)
    res = env_key.save_provider_key("openai", "sk-brandnewkey123456")
    assert res["ok"] is True
    body = env.read_text(encoding="utf-8")
    assert "sk-old" not in body and "sk-brandnewkey123456" in body
    assert body.count("OPENAI_API_KEY=") == 1  # replaced, not duplicated


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
