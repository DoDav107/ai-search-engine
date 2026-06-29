"""Tests for the gated server-side env-key writer (src.security.env_writer).

Offline: the cheap auth ping is skipped via ``verify=False`` so no network is hit; the
provider-match PREFIX guard is still exercised (it runs before the ping). Runnable under
pytest OR directly:

    .venv/bin/python -m tests.test_env_writer
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.security import env_writer as ew


def _setup(tmp_env: Path, *, allow: bool, hosted: bool = False) -> None:
    ew.ENV_PATH = tmp_env
    ew.GITIGNORE_PATH = tmp_env.parent / ".gitignore"
    if allow:
        os.environ["ALLOW_ENV_KEY_WRITE"] = "true"
    else:
        os.environ.pop("ALLOW_ENV_KEY_WRITE", None)
    if hosted:
        os.environ["HOSTED"] = "true"
    else:
        os.environ.pop("HOSTED", None)


def _fresh_env(content: str = "") -> Path:
    d = Path(tempfile.mkdtemp())
    env = d / ".env"
    env.write_text(content, encoding="utf-8")
    return env


def test_disabled_by_default() -> None:
    env = _fresh_env("OPENAI_API_KEY=sk-original\n")
    _setup(env, allow=False)
    res = ew.save_provider_key_to_env("openai", "sk-newkey1234567890", verify=False)
    assert res["ok"] is False and res.get("disabled") is True
    assert env.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-original\n"  # untouched


def test_disabled_when_hosted() -> None:
    env = _fresh_env()
    _setup(env, allow=True, hosted=True)
    res = ew.save_provider_key_to_env("openai", "sk-newkey1234567890", verify=False)
    assert res["ok"] is False and res.get("disabled") is True


def test_unsupported_provider_refused() -> None:
    env = _fresh_env()
    _setup(env, allow=True)
    res = ew.save_provider_key_to_env("mock", "whatever123", verify=False)
    assert res["ok"] is False and "not a runnable provider" in res["message"]
    res2 = ew.save_provider_key_to_env("bogus", "whatever123", verify=False)
    assert res2["ok"] is False and "not a runnable provider" in res2["message"]


def test_provider_mismatch_rejected() -> None:
    env = _fresh_env("OPENAI_API_KEY=sk-keep\n")
    _setup(env, allow=True)
    # A Claude key submitted while provider=openai must be rejected — nothing written.
    res = ew.save_provider_key_to_env("openai", "sk-ant-abc12345", verify=False)
    assert res["ok"] is False and "anthropic" in res["message"]
    assert env.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-keep\n"
    # Google key shape under provider=openai also rejected.
    assert ew.save_provider_key_to_env("openai", "AIzaSyABC12345", verify=False)["ok"] is False


def test_alias_canonicalised_and_written() -> None:
    env = _fresh_env("# comment\nOPENAI_API_KEY=sk-keep\nOTHER=v\n")
    _setup(env, allow=True)
    secret = "AIzaSyFAKEkey1234567890"
    res = ew.save_provider_key_to_env("gemini", secret, verify=False)  # alias → google
    assert res == {"ok": True, "provider": "google", "env_var": "GOOGLE_API_KEY", "last4": secret[-4:]}
    body = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-keep" in body and "OTHER=v" in body and "# comment" in body  # preserved
    assert f"GOOGLE_API_KEY={secret}" in body
    # Result must NOT contain the full key.
    assert secret not in repr(res)


def test_updates_existing_line_and_perms_600() -> None:
    env = _fresh_env("OPENAI_API_KEY=sk-old\n")
    _setup(env, allow=True)
    res = ew.save_provider_key_to_env("openai", "sk-brandnewkey123", verify=False)
    assert res["ok"] is True and res["env_var"] == "OPENAI_API_KEY"
    body = env.read_text(encoding="utf-8")
    assert "sk-old" not in body and "sk-brandnewkey123" in body
    assert body.count("OPENAI_API_KEY=") == 1  # replaced, not duplicated
    assert (os.stat(env).st_mode & 0o777) == 0o600  # chmod 600


def test_ensure_env_gitignored_appends_when_missing() -> None:
    env = _fresh_env()
    _setup(env, allow=True)
    gi = env.parent / ".gitignore"
    gi.write_text("node_modules/\n", encoding="utf-8")  # no .env line
    ew.save_provider_key_to_env("openai", "sk-newkey1234567890", verify=False)
    assert ".env" in gi.read_text(encoding="utf-8")


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
