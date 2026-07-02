"""OpenAI chat-completions client — shared singleton for GEO and drafting agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openai
import yaml
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_openai_config() -> dict:
    override = os.environ.get("AUDIT_GEO_CONFIG_PATH")
    config_path = Path(override) if override else REPO_ROOT / "config" / "geo_config.yaml"
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
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

# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------

class OpenAIClient:
    """Thin wrapper around the OpenAI chat completions API with a per-run call cap."""

    def __init__(self, api_key: str | None = None) -> None:
        selected_key = (api_key or _api_key).strip()
        if not selected_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Copy .env.example to .env and add your key, or provide a temporary key for this audit."
            )
        self._client = openai.OpenAI(api_key=selected_key, timeout=30, max_retries=2)
        self.call_count: int = 0

    def reset_call_count(self) -> None:
        """Zero the per-run call tally. MUST be called at the start of each audit run —
        this is a long-lived singleton, so without a reset the cap would accumulate across
        successive in-process runs (e.g. repeated Streamlit New-Audit runs)."""
        self.call_count = 0

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Send a chat completion request and return the response text.

        ``max_completion_tokens`` overrides the configured default for this call (e.g. GEO
        measurement needs more headroom). ``reasoning_effort`` (e.g. "minimal"/"low") is
        passed through when supported; if the model/SDK rejects it, the call is retried
        once without it so callers don't have to care whether it's accepted. ``model``
        overrides the configured default model for this call (e.g. a cheaper model for
        competitor extraction). ``timeout`` overrides the default 30s request timeout for
        this call (e.g. large analytical drafts on a reasoning model take longer); the
        shared call cap / retry still apply.

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

        api = self._client if timeout is None else self._client.with_options(timeout=timeout)

        try:
            self.call_count += 1
            try:
                response = api.chat.completions.create(**kwargs)
            except (TypeError, openai.BadRequestError):
                # reasoning_effort may be unsupported by this model/SDK — retry without it.
                if "reasoning_effort" in kwargs:
                    kwargs.pop("reasoning_effort")
                    response = api.chat.completions.create(**kwargs)
                else:
                    raise
            return response.choices[0].message.content or ""
        except openai.AuthenticationError as exc:
            raise RuntimeError(f"OpenAI authentication failed — check OPENAI_API_KEY: {exc}") from exc
        except openai.RateLimitError as exc:
            raise RuntimeError(f"OpenAI rate limit hit: {exc}") from exc
        except openai.OpenAIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc

    def respond_with_web_search(
        self,
        prompt: str,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        model: str | None = None,
        timeout: float | None = None,
        user_location: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run a GEO measurement via the Responses API with the web_search tool enabled.

        Returns a dict: ``{"text": str, "web_search_used": bool, "sources": [{"url","title"}]}``.
        Unlike ``chat`` (chat.completions, used for extraction/drafting), this uses
        ``responses.create`` so the model can browse and return url_citation annotations.
        The answer is read from ``output_text`` (the output is a typed array — message vs
        reasoning vs tool-call items — never assume a fixed position).

        ``user_location`` (``{country, region}``) grounds the search in a locale via the
        web_search tool's native ``user_location`` (type ``approximate``); omitted → global.

        Raises RuntimeError on cap/auth/rate/API errors (callers treat that as an
        unmeasured query, not a genuine zero). The shared per-run call cap applies.
        """
        if self.call_count >= _MAX_CALLS:
            raise RuntimeError(
                f"OpenAI call cap reached ({_MAX_CALLS} calls per run). "
                "Increase openai.max_calls_per_run in geo_config.yaml to allow more."
            )

        web_search_tool: dict[str, Any] = {"type": "web_search"}
        if user_location and user_location.get("country"):
            loc: dict[str, str] = {"type": "approximate", "country": user_location["country"]}
            if user_location.get("region"):
                loc["region"] = user_location["region"]
            web_search_tool["user_location"] = loc

        kwargs: dict[str, Any] = {
            "model": model or _MODEL,
            "input": prompt,
            "tools": [web_search_tool],
        }
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens

        api = self._client if timeout is None else self._client.with_options(timeout=timeout)

        try:
            self.call_count += 1
            response = api.responses.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise RuntimeError(f"OpenAI authentication failed — check OPENAI_API_KEY: {exc}") from exc
        except openai.RateLimitError as exc:
            raise RuntimeError(f"OpenAI rate limit hit: {exc}") from exc
        except openai.OpenAIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc

        text = (getattr(response, "output_text", None) or "").strip()
        web_search_used, sources = _extract_search_metadata(response)
        # Surface WHY the answer is (or isn't) here — never swallow an empty completion.
        # A reasoning model behind the agentic web_search tool can exhaust the output-token
        # budget on reasoning + tool calls and return empty text with status="incomplete"
        # (incomplete_details.reason="max_output_tokens"); the caller turns that into a
        # clear, actionable error instead of a misleading 0%.
        finish_reason = ""
        if not text:
            status = getattr(response, "status", None)
            incomplete = getattr(response, "incomplete_details", None)
            reason = getattr(incomplete, "reason", None) if incomplete is not None else None
            usage = getattr(response, "usage", None)
            out_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
            parts = [str(status or "empty")]
            if reason:
                parts.append(f"reason={reason}")
            if out_tokens is not None:
                parts.append(f"output_tokens={out_tokens}")
            finish_reason = ", ".join(parts)
        return {"text": text, "web_search_used": web_search_used, "sources": sources,
                "finish_reason": finish_reason}


def _extract_search_metadata(response: Any) -> tuple[bool, list[dict[str, str]]]:
    """Pull (web_search_used, sources) from a Responses object.

    ``web_search_used`` is True if the output contains a web_search tool call OR any
    url_citation annotation. ``sources`` is the de-duplicated list of url_citation
    annotations ({"url", "title"}). All access is defensive — the typed output items
    vary (message / reasoning / web_search_call) and order is not assumed.
    """
    web_search_used = False
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in getattr(response, "output", None) or []:
        itype = getattr(item, "type", "") or ""
        if "web_search" in itype:  # e.g. "web_search_call"
            web_search_used = True
        for part in getattr(item, "content", None) or []:
            for ann in getattr(part, "annotations", None) or []:
                if getattr(ann, "type", None) == "url_citation":
                    url = getattr(ann, "url", None)
                    if url and url not in seen:
                        seen.add(url)
                        sources.append({"url": url, "title": getattr(ann, "title", None) or ""})

    if sources:
        web_search_used = True
    return web_search_used, sources


# ---------------------------------------------------------------------------
# Module-level singleton — call cap is shared across the whole pipeline run
# ---------------------------------------------------------------------------

class _MissingOpenAIClient:
    def _raise(self) -> None:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and add your key, or provide a temporary key for this audit."
        )

    def reset_call_count(self) -> None:
        """No-op — there is no client, so there is no per-run tally to reset."""

    def chat(self, *args: Any, **kwargs: Any) -> str:
        self._raise()

    def respond_with_web_search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._raise()


client = OpenAIClient() if _api_key else _MissingOpenAIClient()
