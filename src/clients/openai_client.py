"""OpenAI chat-completions client — shared singleton for GEO and drafting agents."""

from __future__ import annotations

import os
from pathlib import Path

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

    def chat(self, prompt: str, system: str | None = None) -> str:
        """Send a chat completion request and return the response text.

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

        try:
            self.call_count += 1
            response = self._client.chat.completions.create(
                model=_MODEL,
                max_completion_tokens=_MAX_TOKENS,
                messages=messages,
            )
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
