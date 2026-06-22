"""OpenAI chat-completions client — shared singleton for GEO and drafting agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openai
import yaml
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_openai_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "config" / "geo_config.yaml"
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("openai", {})


_cfg = _load_openai_config()
_MODEL = str(_cfg.get("model", "gpt-4o"))
_MAX_TOKENS = int(_cfg.get("max_completion_tokens", 500))
_MAX_CALLS = int(_cfg.get("max_calls_per_run", 5))

# ---------------------------------------------------------------------------
# API key — fail loudly if absent
# ---------------------------------------------------------------------------

_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
if not _api_key:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. "
        "Copy .env.example to .env and add your key, or export it in your shell."
    )

# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------

class OpenAIClient:
    """Thin wrapper around the OpenAI chat completions API with a per-run call cap."""

    def __init__(self) -> None:
        self._client = openai.OpenAI(api_key=_api_key, timeout=30, max_retries=2)
        self.call_count: int = 0

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> str:
        """Send a chat completion request and return the response text.

        ``max_completion_tokens`` overrides the configured default for this call (e.g. GEO
        measurement needs more headroom). ``reasoning_effort`` (e.g. "minimal"/"low") is
        passed through when supported; if the model/SDK rejects it, the call is retried
        once without it so callers don't have to care whether it's accepted. ``model``
        overrides the configured default model for this call (e.g. a cheaper model for
        competitor extraction); the shared call cap / timeout / retry still apply.

        Raises RuntimeError if the per-run call cap is reached before the call is made,
        or if the API returns an auth or rate-limit error.
        """
        if self.call_count >= _MAX_CALLS:
            raise RuntimeError(
                f"OpenAI call cap reached ({_MAX_CALLS} calls per run). "
                "Increase openai.max_calls_per_run in geo_config.yaml to allow more."
            )

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": model or _MODEL,
            "max_completion_tokens": max_completion_tokens if max_completion_tokens is not None else _MAX_TOKENS,
            "messages": messages,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        try:
            self.call_count += 1
            try:
                response = self._client.chat.completions.create(**kwargs)
            except (TypeError, openai.BadRequestError):
                # reasoning_effort may be unsupported by this model/SDK — retry without it.
                if "reasoning_effort" in kwargs:
                    kwargs.pop("reasoning_effort")
                    response = self._client.chat.completions.create(**kwargs)
                else:
                    raise
            return response.choices[0].message.content or ""
        except openai.AuthenticationError as exc:
            raise RuntimeError(f"OpenAI authentication failed — check OPENAI_API_KEY: {exc}") from exc
        except openai.RateLimitError as exc:
            raise RuntimeError(f"OpenAI rate limit hit: {exc}") from exc
        except openai.OpenAIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc


# ---------------------------------------------------------------------------
# Module-level singleton — call cap is shared across the whole pipeline run
# ---------------------------------------------------------------------------

client = OpenAIClient()
