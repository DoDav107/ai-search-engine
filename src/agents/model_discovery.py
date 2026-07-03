"""Live model discovery for the New Audit forms — the ONE shared resolver.

Both dashboards read their "AI model" dropdown through ``geo_agent.build_catalog`` (the
Streamlit form calls it via ``geo_options.load_geo_options``; the Next.js form calls the
same Python via ``/api/audit/options``). This module is the single place that turns a
provider into a usable model list:

    LIVE fetch (provider list-models API)
      -> HARD FILTER to GEO-usable chat models (allow/deny patterns)
      -> order newest-first
      -> disk-cache per provider (short TTL, so it is NOT re-fetched on every render)
    on ANY failure / timeout / empty / disabled
      -> fall back SILENTLY to the curated ``config/models.yaml`` list (+ a small note).

Only the fetch + filter + cache + fallback live here; provider metadata (labels, env vars,
grounding capability) stays in ``geo_agent``. Live fetching is wired for OpenAI (real SDK
+ ``/models``); other providers are curated/pinned via ``live_fetch: false`` and can be
wired later by adding a fetcher to ``_FETCHERS``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_CONFIG_PATH = REPO_ROOT / "config" / "models.yaml"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "model_discovery"

DEFAULT_CACHE_TTL_HOURS = 6.0
_FALLBACK_NOTE = "showing saved model list — live fetch unavailable"

# Per-provider default allow patterns (used only if models.yaml omits `allow` for it).
_DEFAULT_ALLOW: dict[str, list[str]] = {
    "openai": ["^gpt-", "^o[0-9]", "^chatgpt-"],
}
# Non-chat modalities + fine-tunes + legacy completion models, filtered out everywhere.
_DEFAULT_DENY: list[str] = [
    "embedding", "embed", "audio", "tts", "whisper", "transcribe", "realtime",
    "image", "dall-e", "moderation", "search", "computer-use",
    "instruct", "babbage", "davinci", "curie", "ada", "^ft:", ":ft",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_models_config(path: Path | str = MODELS_CONFIG_PATH) -> dict[str, Any]:
    """Load config/models.yaml. Missing/broken file -> {} (callers fall back to defaults)."""
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 — a bad catalogue must never break the form
        logger.warning("Could not read %s: %s", path, exc)
        return {}


def cache_ttl_seconds(models_config: dict[str, Any]) -> float:
    hours = (models_config.get("settings") or {}).get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS)
    try:
        return max(0.0, float(hours)) * 3600.0
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL_HOURS * 3600.0


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns or []:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:  # a bad pattern shouldn't nuke the whole filter
            continue
    return out


def _passes(model_id: str, allow: list[re.Pattern[str]], deny: list[re.Pattern[str]]) -> bool:
    """Keep a model only if it matches NO deny pattern and (if allow is set) at least one allow."""
    if any(rx.search(model_id) for rx in deny):
        return False
    if allow and not any(rx.search(model_id) for rx in allow):
        return False
    return True


# ---------------------------------------------------------------------------
# Disk cache (shared across processes — Next.js spawns a fresh Python per options call,
# so an in-memory cache would re-fetch every time; a small JSON file per provider doesn't)
# ---------------------------------------------------------------------------
def _cache_path(provider: str) -> Path:
    return CACHE_DIR / f"{provider}.json"


def _read_cache(provider: str, ttl_seconds: float) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(_cache_path(provider).read_text(encoding="utf-8"))
        if time.time() - float(data["fetched_at"]) <= ttl_seconds:
            return list(data.get("models") or [])
    except Exception:  # noqa: BLE001 — missing/stale/corrupt cache = a cache miss
        return None
    return None


def _write_cache(provider: str, models: list[dict[str, Any]]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(provider).write_text(
            json.dumps({"fetched_at": time.time(), "models": models}), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 — caching is best-effort
        logger.info("Could not write model cache for %s: %s", provider, exc)


# ---------------------------------------------------------------------------
# Provider fetchers — return [{"id","created"}] or raise. Add one per wired provider.
# ---------------------------------------------------------------------------
def _fetch_openai(api_key: str, timeout: float = 8.0) -> list[dict[str, Any]]:
    import openai

    client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
    out: list[dict[str, Any]] = []
    for m in client.models.list():
        mid = getattr(m, "id", None)
        if mid:
            out.append({"id": str(mid), "created": int(getattr(m, "created", 0) or 0)})
    return out


# Fetcher registry — a provider absent here is curated-only (config fallback).
_FETCHERS: dict[str, Callable[[str], list[dict[str, Any]]]] = {
    "openai": _fetch_openai,
}


def discover_models(
    provider: str,
    *,
    api_key: str | None,
    allow: list[str],
    deny: list[str],
    ttl_seconds: float,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> list[str] | None:
    """Return usable model ids (newest first) from the live API, or None on any failure.

    Uses the disk cache first (so repeated form opens within the TTL make NO API call).
    The RAW list is cached (unfiltered); filtering/ordering is applied after, so tweaking
    allow/deny never requires a re-fetch.
    """
    provider = (provider or "").strip().lower()
    fetcher = fetcher or _FETCHERS.get(provider)
    if fetcher is None or not api_key:
        return None

    raw = _read_cache(provider, ttl_seconds)
    if raw is None:
        try:
            raw = fetcher(api_key)
        except Exception as exc:  # noqa: BLE001 — network/auth/rate errors -> config fallback
            logger.info("Live model discovery failed for %s: %s", provider, exc)
            return None
        if not raw:
            return None
        _write_cache(provider, raw)

    allow_rx, deny_rx = _compile(allow), _compile(deny)
    usable = [m for m in raw if isinstance(m, dict) and m.get("id") and _passes(str(m["id"]), allow_rx, deny_rx)]
    usable.sort(key=lambda m: int(m.get("created") or 0), reverse=True)

    ids: list[str] = []
    for m in usable:
        mid = str(m["id"])
        if mid not in ids:
            ids.append(mid)
    return ids or None


def resolve_models(
    provider: str,
    provider_cfg: dict[str, Any],
    *,
    discover: bool,
    fallback_ids: list[str],
    ttl_seconds: float,
    api_key: str | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> tuple[list[str], str, str | None]:
    """Resolve the ordered model-id list for one provider's dropdown.

    Returns ``(ids, source, note)`` where ``source`` is ``"live"`` or ``"config"`` and
    ``note`` is set ONLY when a live fetch was attempted but we fell back (so a pinned
    ``live_fetch: false`` provider shows no scary note). The curated list is the fallback;
    if it omits ``models``, the engine-derived ``fallback_ids`` are used.
    """
    curated = [str(m).strip() for m in (provider_cfg.get("models") or fallback_ids) if str(m).strip()]
    live_fetch = bool(provider_cfg.get("live_fetch", False))

    if not (discover and live_fetch):
        return curated, "config", None

    allow = provider_cfg.get("allow") or _DEFAULT_ALLOW.get(provider, [])
    deny = provider_cfg.get("deny") or _DEFAULT_DENY
    ids = discover_models(
        provider, api_key=api_key, allow=allow, deny=deny, ttl_seconds=ttl_seconds, fetcher=fetcher
    )
    if not ids:
        return curated, "config", _FALLBACK_NOTE

    # Keep curated ids that live discovery didn't surface (e.g. the configured default), so
    # the default is always selectable even if a filter/pattern would have dropped it.
    for cid in curated:
        if cid not in ids:
            ids.append(cid)
    return ids, "live", None
