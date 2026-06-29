"""Single source of truth for persisting a provider API key into the repo `.env`.

LOCAL / TRUSTED, SINGLE-USER DEV ONLY. This writes a secret to disk, so it is hard-gated:
enabled only when ``ALLOW_ENV_KEY_WRITE`` is truthy AND ``HOSTED`` is NOT truthy. Both the
Streamlit form and the Next.js ``/api/save-key`` route call ``save_provider_key_to_env``
(the route via this module's CLI), so the gate, the provider→env-var resolution, and the
provider-match validation live in exactly one place.

Core invariant: the key is ALWAYS the SELECTED provider's key. The provider comes from the
form's selector — never inferred from the key string. We additionally validate that the
key *belongs* to that provider (shape/prefix + a cheap authenticated ping) and refuse a
mismatch (e.g. an ``sk-ant-…`` Claude key submitted while provider=openai).

Guardrails:
  * Server-side only; the key arrives on STDIN for the CLI (never argv / process list).
  * Gated by ALLOW_ENV_KEY_WRITE (default off) and disabled when HOSTED is set.
  * Provider must be a runnable, mapped provider (reuses ``PROVIDER_ENV_VAR``); otherwise
    refuse with "cannot save key: <provider> is not a runnable provider".
  * Atomic write (temp file + os.replace), then chmod 600; only the target var's line is
    replaced/appended — all other lines/comments are preserved. Ensures `.env` is gitignored.
  * Returns ONLY ``{provider, env_var, last4}`` (plus an ``ok`` flag). The full key is never
    returned, logged, or printed.

CLI (used by the Next.js route):
    echo -n "<key>" | python -m src.security.env_writer --provider openai
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
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

_TRUTHY = {"1", "true", "yes", "on"}
# Provider-name aliases → the one internal id the pipeline uses.
_ALIASES = {"gemini": "google", "grok": "xai"}
# Conservative key charset: typical API-key characters, no whitespace/quotes/newlines.
_KEY_RE = re.compile(r"[A-Za-z0-9_.\-]{8,512}")

# Expected key prefix per provider (where one exists). openai/deepseek both use "sk-".
_EXPECTED_PREFIX: dict[str, tuple[str, ...]] = {
    "openai": ("sk-",),
    "deepseek": ("sk-",),
    "anthropic": ("sk-ant-",),
    "xai": ("xai-",),
    "perplexity": ("pplx-",),
    "google": ("AIza",),
}
# Prefixes that UNAMBIGUOUSLY belong to a specific provider — used to catch a key pasted
# for the wrong provider (e.g. sk-ant-… while provider=openai).
_FOREIGN_PREFIX: dict[str, str] = {
    "sk-ant-": "anthropic",
    "xai-": "xai",
    "pplx-": "perplexity",
    "AIza": "google",
}


def _is_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def allow_env_key_write() -> bool:
    """Feature enabled only when ALLOW_ENV_KEY_WRITE is truthy and HOSTED is not."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    return _is_truthy("ALLOW_ENV_KEY_WRITE") and not _is_truthy("HOSTED")


def canonical_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    return _ALIASES.get(p, p)


def _provider_env_var(provider: str) -> str | None:
    """Resolve a runnable provider to its API-key env var (reuses PROVIDER_ENV_VAR)."""
    from src.agents.geo_agent import PROVIDER_ENV_VAR, create_engine_client  # noqa: F401

    return PROVIDER_ENV_VAR.get(provider)


def _prefix_ok(provider: str, key: str) -> tuple[bool, str]:
    """Reject keys whose shape clearly belongs to a different provider."""
    for prefix, owner in _FOREIGN_PREFIX.items():
        if key.startswith(prefix) and owner != provider:
            return False, (
                f"this looks like a {owner} key, not a {provider} key — "
                f"select {owner} first to save it"
            )
    expected = _EXPECTED_PREFIX.get(provider)
    if expected and not any(key.startswith(p) for p in expected):
        return False, f"a {provider} key is expected to start with {expected[0]!r}"
    return True, ""


def _verify_key(provider: str, key: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Lightest possible authenticated call to confirm the key works for THIS provider.

    Never runs the paid web-search audit — just a models/list (or a 1-token ping for
    Perplexity, which has no free list endpoint). 2xx = valid; 401/403 = rejected; any
    other outcome (other status or network error) is treated as "could not verify" and
    refused, so we never persist an unverifiable key.
    """
    import requests

    try:
        if provider == "openai":
            r = requests.get("https://api.openai.com/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        elif provider == "deepseek":
            r = requests.get("https://api.deepseek.com/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        elif provider == "xai":
            r = requests.get("https://api.x.ai/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        elif provider == "anthropic":
            r = requests.get("https://api.anthropic.com/v1/models",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                             timeout=timeout)
        elif provider == "google":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             params={"key": key}, timeout=timeout)
        elif provider == "perplexity":
            # No free list endpoint — minimal 1-token chat (cheapest authenticated call).
            r = requests.post("https://api.perplexity.ai/chat/completions",
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": "sonar", "max_tokens": 1,
                                    "messages": [{"role": "user", "content": "ping"}]},
                              timeout=timeout)
        else:
            return False, f"no verification probe for provider {provider!r}"
    except requests.RequestException as exc:
        return False, f"could not reach {provider} to verify the key ({type(exc).__name__})"

    if 200 <= r.status_code < 300:
        return True, ""
    if r.status_code in (401, 403):
        return False, f"this doesn't look like a valid {provider} key — {provider} rejected it"
    return False, f"could not verify the {provider} key ({provider} returned HTTP {r.status_code})"


def _ensure_env_gitignored() -> None:
    """Make sure `.env` is gitignored; append it if (somehow) missing."""
    try:
        lines = GITIGNORE_PATH.read_text(encoding="utf-8").splitlines() if GITIGNORE_PATH.exists() else []
        if any(ln.strip() in (".env", "*.env", "/.env") for ln in lines):
            return
        with GITIGNORE_PATH.open("a", encoding="utf-8") as fh:
            fh.write("\n.env\n")
    except OSError:
        pass  # never block a save on gitignore housekeeping


def _write_env_var(name: str, value: str) -> None:
    """Replace (or append) only ``name``'s line in .env atomically, then chmod 600."""
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
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), prefix=".env.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, ENV_PATH)
        os.chmod(ENV_PATH, 0o600)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_provider_key_to_env(provider: str, key: str, *, verify: bool = True) -> dict:
    """Persist ``key`` as the SELECTED provider's env var in .env. Key-free result.

    Returns ``{ok: True, provider, env_var, last4}`` on success, or
    ``{ok: False, message, disabled?}`` on refusal. The full key is never returned.
    ``verify`` runs the cheap auth ping (disable only in offline tests).
    """
    if not allow_env_key_write():
        return {"ok": False, "disabled": True, "message": (
            "Saving keys to the server is disabled. Enable ALLOW_ENV_KEY_WRITE=true "
            "(and ensure HOSTED is unset) for local, single-user dev only."
        )}

    provider = canonical_provider(provider)
    env_var = _provider_env_var(provider)
    if not env_var:
        return {"ok": False, "message": f"cannot save key: {provider!r} is not a runnable provider."}

    key = (key or "").strip()
    if not _KEY_RE.fullmatch(key):
        return {"ok": False, "message": (
            "Key format looks invalid — expected 8–512 characters of letters, digits, "
            "'-', '_' or '.' with no spaces or quotes."
        )}

    prefix_ok, prefix_msg = _prefix_ok(provider, key)
    if not prefix_ok:
        return {"ok": False, "message": prefix_msg}

    if verify:
        auth_ok, auth_msg = _verify_key(provider, key)
        if not auth_ok:
            return {"ok": False, "message": auth_msg}

    try:
        _ensure_env_gitignored()
        _write_env_var(env_var, key)
    except OSError as exc:
        return {"ok": False, "message": f"could not write .env: {exc}"}

    return {"ok": True, "provider": provider, "env_var": env_var, "last4": key[-4:]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a provider API key to .env (gated).")
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    # Key on STDIN only — never argv (avoids exposure via the process list).
    key = sys.stdin.read().strip()
    result = save_provider_key_to_env(args.provider, key)
    print(json.dumps(result))  # result never includes the full key


if __name__ == "__main__":
    main()
