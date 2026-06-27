"""Opt-in, server-side writer that saves a provider API key into the repo `.env`.

LOCAL / TRUSTED USE ONLY. This persists a secret to the server's .env, so it is gated
behind the ``ALLOW_ENV_KEY_WRITE`` env flag (default OFF) and MUST remain disabled on any
public or multi-user deployment (see README — ties to the hosting decision).

Guardrails:
  * Server-side only — the Next.js route spawns this module; the key arrives on STDIN
    (never argv, so it can't leak via the process list) and is NEVER echoed back in any
    return value or printed output.
  * Gated by ALLOW_ENV_KEY_WRITE (default false). When off, ``save_provider_key`` refuses.
  * Validates the provider (must be a known engine env var) and the key FORMAT before
    writing.
  * Updates ONLY that provider's line in .env (atomic write) — never clobbers other keys.

CLI (used by the Next.js /api/audit/save-key route):
    echo -n "<key>" | python -m src.reporting.env_key --provider openai
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"
_FLAG = "ALLOW_ENV_KEY_WRITE"
_TRUTHY = {"1", "true", "yes", "on"}
# Conservative key format: typical API-key characters, no whitespace/quotes/newlines.
_KEY_RE = re.compile(r"[A-Za-z0-9_.\-]{8,512}")


def allow_env_key_write() -> bool:
    """Whether the opt-in env-write feature is enabled (default OFF). Reads the repo .env."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def _provider_env_var(provider: str) -> str | None:
    from src.agents.geo_agent import PROVIDER_ENV_VAR

    return PROVIDER_ENV_VAR.get((provider or "").strip().lower())


def _valid_key(key: str) -> bool:
    return bool(_KEY_RE.fullmatch(key or ""))


def _write_env_var(name: str, value: str) -> None:
    """Replace (or append) only ``name``'s line in .env, preserving everything else."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
    new_line = f"{name}={value}"
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    # Atomic write: temp file in the same dir, then replace.
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, ENV_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_provider_key(provider: str, key: str) -> dict:
    """Persist ``key`` as the provider's env var in .env. Returns a key-free status dict.

    Never raises for the expected refusal cases; the returned dict NEVER contains the key.
    """
    if not allow_env_key_write():
        return {"ok": False, "message": (
            "Saving keys to the server is disabled. Set ALLOW_ENV_KEY_WRITE=true in the "
            "server .env to enable this for local/trusted use only."
        )}
    env_var = _provider_env_var(provider)
    if not env_var:
        return {"ok": False, "message": f"Unknown provider: {provider!r}."}
    key = (key or "").strip()
    if not _valid_key(key):
        return {"ok": False, "message": (
            "Key format looks invalid — expected 8–512 characters of letters, digits, "
            "'-', '_' or '.' with no spaces or quotes."
        )}
    try:
        _write_env_var(env_var, key)
    except OSError as exc:
        return {"ok": False, "message": f"Could not write .env: {exc}"}
    return {"ok": True, "env_var": env_var, "message": (
        f"Saved {env_var} to the server .env. A server/pipeline restart may be required "
        "for it to take effect (env is loaded at process start)."
    )}


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a provider API key to .env (gated).")
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    # Key on STDIN only — never argv (avoids exposure via the process list).
    key = sys.stdin.read().strip()
    result = save_provider_key(args.provider, key)
    print(json.dumps(result))  # result never includes the key


if __name__ == "__main__":
    main()
