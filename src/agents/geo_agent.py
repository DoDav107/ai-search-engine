"""GEO research agent for measuring brand visibility in AI engine answers."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..engine.models import GeoQueryResult, GeoReport

logger = logging.getLogger(__name__)


# Which providers can ground answers in live web search. Where True, grounding is
# MANDATORY — a search-capable client must attach its search tool or fail loudly,
# so GEO measures live AI answers, not training-data recall.
SUPPORTS_WEB_SEARCH: dict[str, bool] = {
    "openai": True,       # Responses API web_search tool
    "anthropic": True,    # web_search tool
    "google": True,       # Gemini Google Search grounding
    "xai": True,          # Grok Live Search
    "perplexity": True,   # Sonar is web-grounded by default
    "deepseek": False,    # no web-search capability — runs ungrounded
    "mock": False,        # offline fixtures
}

# Env var that holds each provider's API key (the temporary-key mechanism overrides it).
PROVIDER_ENV_VAR: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Human display name per provider for the New Audit form dropdowns.
PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Claude",
    "google": "Google Gemini",
    "deepseek": "DeepSeek",
    "xai": "xAI (Grok)",
    "perplexity": "Perplexity",
    "mock": "Mock / Demo",
}

# Whether a provider may be CHOSEN in the user-facing New Audit form. Mock is the free
# offline test path and the verify gate — it stays fully runnable from geo_config.yaml /
# CLI / the engine factory, but ui_selectable=False keeps it out of the client-facing
# dropdowns. This is a flag, never a hardcoded exclusion, so the forms simply filter on it.
UI_SELECTABLE: dict[str, bool] = {
    "openai": True,
    "anthropic": True,
    "google": True,
    "deepseek": True,
    "xai": True,
    "perplexity": True,
    "mock": False,
}

# Order providers appear in the dropdowns; unknown providers from config follow.
PROVIDER_ORDER: list[str] = ["openai", "anthropic", "google", "deepseek", "xai", "perplexity", "mock"]


def build_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """Single source of truth for the provider→models catalog used by BOTH dashboards.

    Models are derived from ``config['engines']`` — the exact provider+model strings the
    engine factory (:func:`create_engine_client`) runs — so the New Audit forms,
    geo_config.yaml, the pipeline, and the results can never drift. The per-engine
    ``enabled`` flag is intentionally ignored: it gates a batch run, not what a user may
    pick. Provider metadata (label, API-key env var, ui_selectable, grounding) comes from
    the maps above. Mock is included with ``ui_selectable=False`` so it stays runnable from
    config/CLI while the forms filter it out.

    Returns ``{default_provider, default_model, providers}`` where each provider carries
    ``{label, env_key_name, ui_selectable, web_grounded, models:[{id,label}]}``. Defaults
    always land on a UI-selectable provider so a form never defaults to mock.

    Model strings are CONFIG — verify each against the provider's current models page:
      OpenAI     https://platform.openai.com/docs/models
      Anthropic  https://docs.anthropic.com/en/docs/about-claude/models
      Google     https://ai.google.dev/gemini-api/docs/models
      DeepSeek   https://api-docs.deepseek.com
      xAI        https://docs.x.ai/docs/models
      Perplexity https://docs.perplexity.ai/getting-started/models
    """
    by_provider: dict[str, list[str]] = {}
    engines = config.get("engines")
    if isinstance(engines, list):
        for entry in engines:
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider") or "").strip().lower()
            model = str(entry.get("model") or "").strip()
            if not provider or not model:
                continue
            models = by_provider.setdefault(provider, [])
            if model not in models:
                models.append(model)

    ordered = [p for p in PROVIDER_ORDER if p in by_provider]
    ordered += [p for p in by_provider if p not in ordered]

    providers: dict[str, Any] = {}
    for provider in ordered:
        providers[provider] = {
            "label": PROVIDER_LABELS.get(provider, provider),
            "env_key_name": PROVIDER_ENV_VAR.get(provider),  # None for mock
            "ui_selectable": UI_SELECTABLE.get(provider, True),
            "web_grounded": SUPPORTS_WEB_SEARCH.get(provider, False),
            "models": [{"id": m, "label": m} for m in by_provider[provider]],
        }

    geo = config.get("geo") if isinstance(config.get("geo"), dict) else {}
    selectable = [p for p in ordered if providers[p]["ui_selectable"] and providers[p]["models"]]
    default_provider = str(geo.get("default_provider") or "").strip().lower()
    if default_provider not in selectable:
        default_provider = selectable[0] if selectable else (ordered[0] if ordered else "")
    default_model_ids = [m["id"] for m in providers.get(default_provider, {}).get("models", [])]
    default_model = str(geo.get("default_model") or "").strip()
    if default_model not in default_model_ids:
        default_model = default_model_ids[0] if default_model_ids else ""

    return {
        "default_provider": default_provider,
        "default_model": default_model,
        "providers": providers,
    }


def _require_grounding(provider: str, grounding_enabled: bool) -> None:
    """Guard: a search-capable provider must run with its grounding tool enabled."""
    if SUPPORTS_WEB_SEARCH.get(provider) and not grounding_enabled:
        raise RuntimeError(
            f"{provider} supports live web search, so grounding is mandatory — refusing to "
            f"run it ungrounded. Enable its search tool (web_search.enabled / grounding) "
            f"in geo_config.yaml, or disable this engine."
        )


def _resolve_api_key(provider: str, api_key: str | None) -> str:
    """Return the key for a provider: explicit (temporary) override, else its env var.

    Raises a clear error naming the env var if neither is present. Never falls back to
    another provider's key.
    """
    import os

    if api_key:
        return api_key
    env_var = PROVIDER_ENV_VAR.get(provider, f"{provider.upper()}_API_KEY")
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise RuntimeError(
            f"{provider} engine was selected but no API key is available. "
            f"Set {env_var} (or supply a temporary key), or disable this engine in geo_config.yaml."
        )
    return key


class EngineClient(ABC):
    """Abstract base for AI engine clients. Each client knows its provider + model."""

    provider: str = "mock"
    model: str = "mock-default"
    api_key_source: str = "none"
    # True when this engine runs with live web-search grounding active.
    web_grounded: bool = False

    @abstractmethod
    def query(self, prompt: str) -> str:
        """Send a query to the engine and return the answer text."""

    def measure(self, prompt: str, locale: dict[str, str] | None = None) -> dict[str, Any]:
        """Return ``{"text", "web_search_used", "sources", "locale_method"}``.

        The default wraps ``query`` (no browsing, no locale). Live clients override to add
        web search, citation capture, and locale grounding. Only the SOURCE of the answer
        differs between engines — brand detection / scoring downstream are identical.
        """
        return {"text": self.query(prompt), "web_search_used": False, "sources": [], "locale_method": "none"}


class MockEngineClient(EngineClient):
    """Mock engine client returning deterministic answers for testing."""

    provider = "mock"

    _CANNED_ANSWERS = {
        "How can I automate repetitive tasks in my startup?": "Many startups use workflow automation tools and Eloize to streamline repetitive processes. Consider RPA platforms, Zapier, or AI-powered solutions for efficiency.",
        "What AI tools help small business founders manage growth?": "Growth management tools like Eloize, HubSpot, and Salesforce AI integrate with your workflow. Look for solutions that combine analytics with automation.",
        "How do I govern and control AI systems in my company?": "AI governance is critical. Use monitoring tools and establish clear policies to maintain control over systems and compliance.",
        "What's the best way to implement AI workflows for SMB operations?": "Start small with high-impact processes. Tools like Zapier and Make help SMBs scale AI workflows without heavy engineering investment.",
        "How can AI improve productivity for founder-led teams?": "Founder teams benefit from automation. Eloize and similar tools reduce manual work, freeing founders to focus on strategy and growth.",
        "What are best practices for AI adoption in small B2B companies?": "Best practices include starting with clear use cases, choosing user-friendly tools, and gradual rollout. Solutions like Eloize work well for small teams.",
        "How do I streamline operations using AI as a growth partner?": "Treat AI as part of your team. Eloize and other growth partners automate operations and provide insights to drive business outcomes.",
        "What AI solutions exist for automating business processes at scale?": "Enterprise and mid-market options include custom AI, managed services, and packaged solutions. For SMBs, Eloize offers accessible automation without enterprise complexity.",
    }

    def __init__(self, model: str = "mock-default", api_key_source: str = "none") -> None:
        self.model = model or "mock-default"
        self.api_key_source = api_key_source

    def query(self, prompt: str) -> str:
        """Return a mock answer, deterministic based on the query."""
        return self._CANNED_ANSWERS.get(prompt, f"Mock answer to: {prompt}")


class OpenAIEngineClient(EngineClient):
    """Live OpenAI measurement: web search (Responses API) or plain chat, model-aware.

    Operational params (token budgets, reasoning effort, timeouts, web-search toggle)
    come from the existing ``openai``/``web_search`` config blocks — the engine list
    only selects which model to run.
    """

    provider = "openai"

    def __init__(
        self,
        model: str,
        openai_cfg: dict[str, Any] | None = None,
        web_search_cfg: dict[str, Any] | None = None,
        api_key: str | None = None,
        api_key_source: str = "env",
    ) -> None:
        self.model = model or "gpt-5.5"
        self.api_key_source = api_key_source
        oc = openai_cfg or {}
        ws = web_search_cfg or {}
        self._measure_tokens = int(oc.get("measurement_max_completion_tokens", 2000))
        self._reasoning = oc.get("reasoning_effort") or None
        self._ws_enabled = bool(ws.get("enabled", True))
        # OpenAI supports web search → grounding is mandatory (fail loudly, don't run
        # ungrounded). Checked before key resolution so the intent is unambiguous.
        _require_grounding("openai", self._ws_enabled)
        self.web_grounded = self._ws_enabled
        self._ws_reasoning = ws.get("reasoning_effort") or self._reasoning or "low"
        self._ws_timeout = float(ws.get("timeout", 180))
        self._ws_max = int(ws.get("max_output_tokens", self._measure_tokens))
        try:
            from src.clients import openai_client as openai_module
            from src.clients.openai_client import OpenAIClient, client as shared_openai_client
        except Exception as exc:  # missing key, import/config error — surface clearly
            raise RuntimeError(
                f"OpenAI engine ('{self.model}') is unavailable: {exc}. "
                "Set OPENAI_API_KEY, or disable this engine in geo_config.yaml (enabled: false)."
            ) from exc
        if not api_key and not getattr(openai_module, "_api_key", ""):
            raise RuntimeError(
                "OpenAI was selected, but no API key was provided and OPENAI_API_KEY is not set."
            )
        self._client = OpenAIClient(api_key=api_key) if api_key else shared_openai_client

    @property
    def client(self) -> Any:
        """The shared OpenAI client (reused for competitor extraction)."""
        return self._client

    def measure(self, prompt: str, locale: dict[str, str] | None = None) -> dict[str, Any]:
        if self._ws_enabled:
            # OpenAI Responses web_search supports user_location (approximate) natively.
            res = self._client.respond_with_web_search(
                _measurement_input(prompt),
                reasoning_effort=self._ws_reasoning,
                max_output_tokens=self._ws_max,
                model=self.model,
                timeout=self._ws_timeout,
                user_location=locale,
            )
            res["locale_method"] = "native_param" if locale else "none"
            return res
        text = self._client.chat(
            prompt,
            max_completion_tokens=self._measure_tokens,
            reasoning_effort=self._reasoning,
            model=self.model,
        )
        return {"text": text, "web_search_used": False, "sources": [], "locale_method": "none"}

    def query(self, prompt: str) -> str:
        return self.measure(prompt).get("text", "")


class _OpenAICompatEngineClient(EngineClient):
    """Base for OpenAI-compatible providers (DeepSeek, xAI, Perplexity).

    All three speak the OpenAI chat-completions wire format via a custom ``base_url``;
    they differ only in grounding: Perplexity/Sonar is grounded by default, xAI Grok
    enables Live Search via ``search_parameters``, DeepSeek has no search and runs
    ungrounded. Citations (when returned) populate ``sources``.
    """

    _base_url: str = ""
    _grounded: bool = False
    _extra_body: dict[str, Any] | None = None

    def __init__(self, model: str, api_key: str | None = None, api_key_source: str = "env",
                 timeout: float = 120.0) -> None:
        self.model = model
        self.api_key_source = api_key_source
        self.web_grounded = self._grounded
        _require_grounding(self.provider, self._grounded)
        key = _resolve_api_key(self.provider, api_key)
        from openai import OpenAI

        self._client = OpenAI(api_key=key, base_url=self._base_url, timeout=timeout)

    def _locale_native(self, locale: dict[str, str]) -> dict[str, Any] | None:
        """Native locale params merged into extra_body, or None if unsupported (→ suffix)."""
        return None

    def measure(self, prompt: str, locale: dict[str, str] | None = None) -> dict[str, Any]:
        locale_method = "none"
        question = prompt
        extra_body: dict[str, Any] = dict(self._extra_body or {})
        if locale:
            native = self._locale_native(locale)
            if native:
                extra_body.update(native)
                locale_method = "native_param"
            else:
                # No native locale param for this provider — fall back to a query suffix.
                question = _localized_question(prompt, locale)
                locale_method = "query_suffix"

        text_prompt = _measurement_input(question) if self._grounded else question
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": text_prompt}],
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # network/auth/rate — surface as a measurement error
            raise RuntimeError(f"{self.provider} API error: {exc}") from exc
        text = (response.choices[0].message.content or "").strip()
        # DeepSeek/xAI/Perplexity return live citations as a top-level `citations` list
        # of URL strings (xAI/Perplexity); map them to the common sources shape.
        raw = getattr(response, "citations", None) or []
        sources = [{"url": str(u), "title": ""} for u in raw if u]
        return {"text": text, "web_search_used": self._grounded and bool(sources),
                "sources": sources, "locale_method": locale_method}

    def query(self, prompt: str) -> str:
        return self.measure(prompt).get("text", "")


class DeepSeekEngineClient(_OpenAICompatEngineClient):
    """DeepSeek (OpenAI-compatible). No web search exists — runs UNGROUNDED."""

    provider = "deepseek"
    _base_url = "https://api.deepseek.com"
    _grounded = False


class XaiEngineClient(_OpenAICompatEngineClient):
    """xAI Grok with Live Search grounding enabled via search_parameters."""

    provider = "xai"
    _base_url = "https://api.x.ai/v1"
    _grounded = True
    # Grok Live Search. Confirm the exact param shape against current xAI docs.
    _extra_body = {"search_parameters": {"mode": "on", "return_citations": True}}


class PerplexityEngineClient(_OpenAICompatEngineClient):
    """Perplexity Sonar — web-grounded by default; no extra tool needed."""

    provider = "perplexity"
    _base_url = "https://api.perplexity.ai"
    _grounded = True

    def _locale_native(self, locale: dict[str, str]) -> dict[str, Any] | None:
        # Sonar supports web_search_options.user_location.country (ISO-2). Confirm shape
        # against current Perplexity docs.
        country = locale.get("country")
        if not country:
            return None
        return {"web_search_options": {"user_location": {"country": country}}}


class AnthropicEngineClient(EngineClient):
    """Anthropic Claude with the server-side web_search tool enabled (REST via requests)."""

    provider = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, api_key_source: str = "env",
                 max_tokens: int = 1024, timeout: float = 180.0) -> None:
        self.model = model
        self.api_key_source = api_key_source
        self.web_grounded = True
        _require_grounding("anthropic", True)
        self._key = _resolve_api_key("anthropic", api_key)
        self._max_tokens = max_tokens
        self._timeout = timeout

    def measure(self, prompt: str, locale: dict[str, str] | None = None) -> dict[str, Any]:
        import requests

        # Anthropic server-side web search. Confirm the tool version against current docs.
        web_search_tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search"}
        locale_method = "none"
        if locale and locale.get("country"):
            # web_search supports a user_location (approximate) hint natively.
            user_location: dict[str, str] = {"type": "approximate", "country": locale["country"]}
            if locale.get("region"):
                user_location["region"] = locale["region"]
            web_search_tool["user_location"] = user_location
            locale_method = "native_param"

        payload = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": _measurement_input(prompt)}],
            "tools": [web_search_tool],
        }
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"anthropic API error: {exc}") from exc

        text_parts: list[str] = []
        urls: set[str] = set()
        used = False
        for block in data.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
                for cite in block.get("citations", []) or []:
                    if cite.get("url"):
                        urls.add(cite["url"])
            elif btype in ("web_search_tool_result", "server_tool_use"):
                used = True
                for item in block.get("content", []) or []:
                    if isinstance(item, dict) and item.get("url"):
                        urls.add(item["url"])
        sources = [{"url": u, "title": ""} for u in urls]
        return {"text": " ".join(p for p in text_parts if p).strip(),
                "web_search_used": used or bool(sources), "sources": sources,
                "locale_method": locale_method}

    def query(self, prompt: str) -> str:
        return self.measure(prompt).get("text", "")


class GoogleEngineClient(EngineClient):
    """Google Gemini with Google Search grounding enabled (REST via requests)."""

    provider = "google"

    def __init__(self, model: str, api_key: str | None = None, api_key_source: str = "env",
                 timeout: float = 180.0) -> None:
        self.model = model
        self.api_key_source = api_key_source
        self.web_grounded = True
        _require_grounding("google", True)
        self._key = _resolve_api_key("google", api_key)
        self._timeout = timeout

    def measure(self, prompt: str, locale: dict[str, str] | None = None) -> dict[str, Any]:
        import requests

        # Gemini's google_search grounding tool exposes no per-request region parameter, so
        # ground the locale by appending the region to the question (suffix fallback).
        locale_method = "none"
        question = prompt
        if locale and locale.get("region"):
            question = _localized_question(prompt, locale)
            locale_method = "query_suffix"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": _measurement_input(question)}]}],
            # Google Search grounding tool. Confirm shape against current Gemini docs.
            "tools": [{"google_search": {}}],
        }
        try:
            resp = requests.post(url, params={"key": self._key}, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"google API error: {exc}") from exc

        candidates = data.get("candidates") or [{}]
        cand = candidates[0]
        text = " ".join(
            part.get("text", "") for part in (cand.get("content", {}).get("parts") or [])
        ).strip()
        urls: set[str] = set()
        grounding = cand.get("groundingMetadata") or {}
        for chunk in grounding.get("groundingChunks", []) or []:
            web = (chunk or {}).get("web") or {}
            if web.get("uri"):
                urls.add(web["uri"])
        sources = [{"url": u, "title": ""} for u in urls]
        return {"text": text, "web_search_used": bool(grounding) or bool(sources),
                "sources": sources, "locale_method": locale_method}

    def query(self, prompt: str) -> str:
        return self.measure(prompt).get("text", "")


def create_engine_client(
    provider: str,
    model: str,
    openai_cfg: dict[str, Any] | None = None,
    web_search_cfg: dict[str, Any] | None = None,
    api_key: str | None = None,
    api_key_source: str = "env",
) -> EngineClient:
    """Factory: build an EngineClient for a provider/model pair (from config).

    Supported: ``mock`` (offline) and ``openai`` (live). ``anthropic``/``perplexity``
    are recognised but not implemented yet — they raise a clear, actionable error so a
    misconfigured-but-enabled engine fails loudly rather than silently. Disabled engines
    are filtered out before this is called.
    """
    p = (provider or "mock").strip().lower()
    if p == "mock":
        return MockEngineClient(model=model or "mock-default", api_key_source="none")
    if p == "openai":
        return OpenAIEngineClient(
            model=model or "gpt-5.5",
            openai_cfg=openai_cfg,
            web_search_cfg=web_search_cfg,
            api_key=api_key,
            api_key_source=api_key_source,
        )
    ws = web_search_cfg or {}
    timeout = float(ws.get("timeout", 180))
    if p == "anthropic":
        return AnthropicEngineClient(model=model or "claude-sonnet-4-6", api_key=api_key,
                                     api_key_source=api_key_source, timeout=timeout)
    if p == "google":
        return GoogleEngineClient(model=model or "gemini-3-pro", api_key=api_key,
                                  api_key_source=api_key_source, timeout=timeout)
    if p == "xai":
        return XaiEngineClient(model=model or "grok-4", api_key=api_key,
                               api_key_source=api_key_source, timeout=timeout)
    if p == "deepseek":
        return DeepSeekEngineClient(model=model or "deepseek-chat", api_key=api_key,
                                    api_key_source=api_key_source, timeout=timeout)
    if p == "perplexity":
        return PerplexityEngineClient(model=model or "sonar", api_key=api_key,
                                      api_key_source=api_key_source, timeout=timeout)
    raise ValueError(f"Unknown engine provider: {provider!r}")


def get_engine_client(config: dict[str, Any]) -> EngineClient:
    """Backward-compatible single-engine client from legacy ``engine`` config.

    Retained for the drafting agent; new GEO runs use ``create_engine_client`` +
    the ``engines`` list.
    """
    engine_type = str(config.get("engine", "mock")).lower()
    if engine_type == "mock":
        return MockEngineClient()
    return create_engine_client(engine_type, str((config.get("openai") or {}).get("model") or ""))


def _resolve_engines(config: dict[str, Any]) -> list[dict[str, str]]:
    """Resolve enabled ``{provider, model}`` engines from config.

    New format: ``engines: [{provider, model, enabled}]``. Legacy fallback: synthesise
    one engine from ``engine`` / ``openai.mode`` + ``openai.model`` so old configs and
    the New-Audit-generated configs keep working unchanged.
    """
    engines = config.get("engines")
    if isinstance(engines, list) and engines:
        resolved: list[dict[str, str]] = []
        for entry in engines:
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            provider = str(entry.get("provider") or "mock").strip().lower()
            default_model = "mock-default" if provider == "mock" else ""
            resolved.append({"provider": provider, "model": str(entry.get("model") or default_model).strip()})
        return resolved

    # Legacy single-engine fallback.
    engine_type = str(config.get("engine", "mock")).lower()
    openai_cfg = config.get("openai", {})
    if engine_type == "live" or engine_type == "openai" or openai_cfg.get("mode") == "live":
        return [{"provider": "openai", "model": str(openai_cfg.get("model") or "gpt-5.5")}]
    return [{"provider": "mock", "model": "mock-default"}]


def _fold_text(value: str) -> str:
    """Case/diacritic folded text for brand matching and aggregation."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold()


def _norm_key(name: str) -> str:
    """Matching key for a brand: fold accents/case + drop punctuation/whitespace.

    Collapses display variants such as "Boba Boba", "BOBABOBA", "bōbabōba",
    and "boba-boba" to the same key: "bobaboba".
    """
    return re.sub(r"[^a-z0-9]+", "", _fold_text(name))


def _compact_with_positions(text: str) -> tuple[str, list[int]]:
    """Return a compact normalized string plus original-position map."""
    chars: list[str] = []
    positions: list[int] = []
    for pos, char in enumerate(text or ""):
        for folded in _fold_text(char):
            if folded.isalnum() and folded.isascii():
                chars.append(folded)
                positions.append(pos)
    return "".join(chars), positions


def _alias_keys(brand: str, aliases: list[str] | None = None) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for value in [brand, *(aliases or [])]:
        key = _norm_key(value)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _find_brand_mentions(answer: str, aliases: list[str]) -> list[int]:
    compact, positions = _compact_with_positions(answer)
    hits: list[int] = []
    for key in aliases:
        if not key:
            continue
        start = 0
        while True:
            idx = compact.find(key, start)
            if idx < 0:
                break
            hits.append(positions[idx] if idx < len(positions) else idx)
            start = idx + max(len(key), 1)
    return sorted(set(hits))


def detect_brand_mentions(
    result: GeoQueryResult,
    brand: str,
    competitors: list[str],
    aliases: list[str] | None = None,
) -> GeoQueryResult:
    """Detect brand and competitor mentions in an engine answer."""
    if result.error:
        return result

    answer = result.answer or ""
    mentions = _find_brand_mentions(answer, _alias_keys(brand, aliases))
    result.mention_count = len(mentions)
    result.brand_mentioned = bool(mentions)
    result.first_position = mentions[0] if mentions else None

    if competitors:
        found_competitors: list[str] = []
        for competitor in competitors:
            if _find_brand_mentions(answer, _alias_keys(competitor)):
                found_competitors.append(competitor)
        result.competitors_found = found_competitors
    return result


_EXTRACTION_SYSTEM = "You are a precise information extractor. Respond with valid JSON only — no prose, no code fences."

_EXTRACTION_PROMPT = (
    "Extract every brand or company name that EXPLICITLY appears in the text below. "
    "Ground your answer strictly in the text — do NOT add brands from your own knowledge "
    "and do NOT infer brands that are not literally present. "
    'Return ONLY a JSON array of strings, e.g. ["BrandA", "BrandB"]. '
    "If no brands appear, return [].\n\n"
    'TEXT:\n"""\n{answer}\n"""'
)


def _parse_brand_list(raw: str | None) -> list[str]:
    """Parse the extractor response into a list of brand strings, defensively.

    Handles code fences, surrounding prose, empty/non-JSON output. Returns [] on
    anything that isn't a usable JSON array of strings.
    """
    if not raw:
        return []
    text = raw.strip()

    # Strip ```json ... ``` (or plain ```) fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    data: Any
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first [...] block embedded in surrounding prose.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _clean_competitors(names: list[str], aliases: list[str]) -> list[str]:
    """Remove subject-brand aliases and dedupe on the normalized key, keeping first display form."""
    alias_keys = {_norm_key(a) for a in aliases if a and a.strip()}
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in names:
        key = _norm_key(name)
        if not key or key in alias_keys or key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def extract_competitors(
    answer: str,
    openai_client: Any,
    model: str,
    aliases: list[str],
    max_completion_tokens: int = 300,
) -> list[str]:
    """Run a separate, lightweight extraction pass to find rival brands in an answer.

    Uses a cheap model via the shared client (so the call cap / timeout / retry apply).
    Never raises: on cap/exhaustion or any API/parse error, logs and returns []. The
    subject brand and its aliases are stripped, and the result is deduped case-insensitively.
    """
    if not (answer or "").strip():
        return []
    try:
        raw = openai_client.chat(
            _EXTRACTION_PROMPT.format(answer=answer),
            system=_EXTRACTION_SYSTEM,
            max_completion_tokens=max_completion_tokens,
            model=model,
        )
    except Exception as exc:  # cap reached, auth, rate limit, network — never crash the run
        logger.warning("Competitor extraction skipped (call failed): %s", exc)
        return []
    return _clean_competitors(_parse_brand_list(raw), aliases)


def normalize_competitor_names(results: list[GeoQueryResult]) -> None:
    """Collapse case/punctuation variants across the run to ONE display form per brand.

    Rewrites each query's ``competitors_found`` in place: every name with the same
    normalized key is replaced by a single canonical display (the most query-frequent
    variant, ties broken by first appearance), and each query is re-deduped on the key.
    """
    from collections import Counter

    variant_counts: dict[str, Counter] = {}
    first_seen: dict[tuple[str, str], int] = {}
    seq = 0
    for result in results:
        for name in result.competitors_found or []:
            key = _norm_key(name)
            if not key:
                continue
            variant_counts.setdefault(key, Counter())[name] += 1
            if (key, name) not in first_seen:
                first_seen[(key, name)] = seq
                seq += 1

    canonical: dict[str, str] = {}
    for key, counter in variant_counts.items():
        # most frequent variant wins; tie-break by earliest appearance (stable)
        canonical[key] = sorted(
            counter.items(), key=lambda kv: (-kv[1], first_seen[(key, kv[0])])
        )[0][0]

    for result in results:
        seen: set[str] = set()
        rebuilt: list[str] = []
        for name in result.competitors_found or []:
            key = _norm_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            rebuilt.append(canonical.get(key, name))
        result.competitors_found = rebuilt


def build_competitors_summary(results: list[GeoQueryResult]) -> list[dict]:
    """Aggregate competitors across queries into a ranked [{name, query_count}] list.

    Counts each competitor once per query (in how many queries it surfaced), deduped on
    the normalized key, sorted by query_count desc then name. Assumes display names have
    already been canonicalized via ``normalize_competitor_names``.
    """
    counts: dict[str, list] = {}  # norm-key -> [display_name, query_count]
    for result in results:
        seen_in_query: set[str] = set()
        for name in result.competitors_found:
            key = _norm_key(name)
            if not key or key in seen_in_query:
                continue
            seen_in_query.add(key)
            if key not in counts:
                counts[key] = [name, 0]
            counts[key][1] += 1
    summary = [{"name": display, "query_count": count} for display, count in counts.values()]
    summary.sort(key=lambda item: (-item["query_count"], item["name"].lower()))
    return summary


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', etc."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_share_of_voice(
    results: list[GeoQueryResult], subject_brand: str, aliases: list[str]
) -> list[dict]:
    """Share of Voice by PRESENCE: per brand, (# queries it appears in) / (measured queries).

    The subject brand is included in the ranking (matched via its aliases on
    brand_mentioned). Pure post-processing over already-captured data — no API calls,
    and prominence/visibility/geo_score are untouched. Sorted by share desc.
    """
    measured = [r for r in results if not r.error]
    total = len(measured)
    subj_key = _norm_key(subject_brand)
    alias_keys = {_norm_key(a) for a in (aliases or [subject_brand]) if a and a.strip()}
    alias_keys.add(subj_key)

    # norm-key -> [display, queries_present, is_subject]; subject always present in ranking
    counts: dict[str, list] = {subj_key: [subject_brand, 0, True]}
    for result in measured:
        present: set[str] = set()
        if result.brand_mentioned:
            present.add(subj_key)
        for name in result.competitors_found or []:
            key = _norm_key(name)
            if not key:
                continue
            present.add(key)
            if key not in counts:
                counts[key] = [name, 0, key in alias_keys]
        for key in present:
            counts[key][1] += 1

    sov = [
        {
            "brand": display,
            "is_subject": bool(is_subject),
            "queries_present": qp,
            "share": round(qp / total, 4) if total else 0.0,
        }
        for display, qp, is_subject in counts.values()
    ]
    sov.sort(key=lambda x: (-x["share"], -x["queries_present"], x["brand"].lower()))
    return sov


def sov_headline(share_of_voice: list[dict], subject_brand: str) -> str:
    """Punchy one-liner: 'Nike ranks 1st of 12 brands by Share of Voice'."""
    if not share_of_voice:
        return ""
    subject = next((s for s in share_of_voice if s.get("is_subject")), None)
    if subject is None:
        return ""
    total = len(share_of_voice)
    rank = 1 + sum(1 for s in share_of_voice if s["share"] > subject["share"])
    tied = sum(1 for s in share_of_voice if s["share"] == subject["share"]) > 1
    tie_txt = " (tied)" if tied else ""
    return f"{subject_brand} ranks {_ordinal(rank)} of {total} brands by Share of Voice{tie_txt}"


def _prominence(result: GeoQueryResult) -> float | None:
    """Clamped prominence (0.3..1.0) of the brand's first mention; None if absent/error."""
    if result.error or not result.brand_mentioned or not result.answer:
        return None
    answer_length = len(result.answer)
    if answer_length <= 0 or result.first_position is None:
        return None
    return max(0.3, min(1.0 - (result.first_position / answer_length), 1.0))


# --- GEO quality signals (rule-based, deterministic — no extra LLM call) ----------
# Tunable word lists. Kept small and explainable; matched as whole words (case-folded).
_POSITIVE_WORDS = (
    "recommended", "recommend", "good choice", "great choice", "leading", "best",
    "top", "trusted", "specialist", "popular", "reliable", "excellent", "ideal",
    "favorite", "favourite", "go-to", "preferred", "strong option", "industry leader",
)
_NEGATIVE_WORDS = (
    "limited", "unknown", "not well-known", "not well known", "less established",
    "lesser-known", "lesser known", "poor", "weak", "obscure", "unproven", "outdated",
    "lacking", "niche",
)
# Words that, near the brand, signal an explicit recommendation / top placement.
_RECOMMEND_WORDS = (
    "best", "top", "leading", "recommended", "recommend", "top choice", "ideal",
    "go-to", "number one", "most popular",
)
_SENTIMENT_WINDOW = 140  # chars on each side of a brand mention to scan for tone

_URL_RE = re.compile(r"https?://[^\s)\]>]+")
_NUMBERED_LIST_RE = re.compile(r"(?m)^\s*(\d+)[.)]\s+(.+)$")
_ACCURACY_VALUE = {"accurate": 1.0, "partially_accurate": 0.5, "inaccurate": 0.0}

_DEFAULT_WEIGHTS = {
    "visibility_weight": 0.35,
    "prominence_weight": 0.20,
    "sentiment_weight": 0.15,
    "recommendation_weight": 0.15,
    "citation_weight": 0.10,
    "accuracy_weight": 0.05,
}


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    """Count whole-word occurrences of any term (case-insensitive)."""
    if not terms:
        return 0
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


def _count_citations(result: GeoQueryResult) -> tuple[int, bool]:
    """Detected source links: http(s) URLs in the answer ∪ engine-returned `sources`."""
    urls = set(_URL_RE.findall(result.answer or ""))
    for source in result.sources or []:
        if isinstance(source, dict) and source.get("url"):
            urls.add(source["url"])
    return len(urls), len(urls) > 0


def _brand_rank(result: GeoQueryResult, brand: str, brand_aliases: list[str]) -> tuple[int | None, bool]:
    """Estimate the brand's rank among listed options.

    Returns ``(rank, from_explicit_list)``. ``rank`` is None if not inferable.
    1) If the answer has a numbered list and an item names the brand, use that number
       (``from_explicit_list=True``).
    2) Otherwise infer by first-mention order vs competitors (``from_explicit_list=False``).
    """
    answer = result.answer or ""
    alias_keys = _alias_keys(brand, brand_aliases)
    for match in _NUMBERED_LIST_RE.finditer(answer):
        if _find_brand_mentions(match.group(2), alias_keys):
            return int(match.group(1)), True
    if result.first_position is None:
        return None, False
    earlier = 0
    for competitor in result.competitors_found or []:
        positions = _find_brand_mentions(answer, _alias_keys(competitor))
        if positions and positions[0] < result.first_position:
            earlier += 1
    return earlier + 1, False


def analyze_quality_signals(
    result: GeoQueryResult,
    brand: str,
    brand_aliases: list[str],
    accuracy_keywords: list[str] | None = None,
    pos_words: tuple[str, ...] = _POSITIVE_WORDS,
    neg_words: tuple[str, ...] = _NEGATIVE_WORDS,
    rec_words: tuple[str, ...] = _RECOMMEND_WORDS,
) -> GeoQueryResult:
    """Populate the rule-based GEO quality signals on a query result, in place.

    Deterministic and offline — no extra model call. Sentiment/recommendation keyword
    lists are config-editable (passed in). Errored/absent rows get safe defaults
    ("unknown"/"none"). See field docs on GeoQueryResult.
    """
    # Competitors mirror the already-detected list (single source of truth).
    result.competitor_names_mentioned = list(result.competitors_found or [])
    result.competitor_count = len(result.competitor_names_mentioned)
    result.citation_count, result.citations_present = _count_citations(result)

    if result.error:
        return result

    answer = result.answer or ""
    lower = answer.lower()

    # Accuracy — placeholder only; never guesses "inaccurate".
    # TODO: upgrade to a live LLM evaluator that checks the answer's factual claims
    # about the brand against the crawled site content, returning accurate /
    # partially_accurate / inaccurate with evidence.
    if result.brand_mentioned and accuracy_keywords:
        matched = [k for k in accuracy_keywords if k.lower() in lower]
        if matched:
            result.answer_accuracy_label = "accurate"
            result.answer_accuracy_notes = "Matched relevant terms: " + ", ".join(matched[:5])
        else:
            result.answer_accuracy_label = "unknown"
            result.answer_accuracy_notes = "Accuracy not evaluated by live model yet."
    else:
        result.answer_accuracy_label = "unknown"
        result.answer_accuracy_notes = "Accuracy not evaluated by live model yet."

    if not result.brand_mentioned:
        result.sentiment_label, result.sentiment_score = "unknown", 0.0
        result.recommendation_strength, result.recommendation_score = "none", 0.0
        result.brand_rank_position = None
        return result

    # Sentiment — scan a window around each brand mention for positive/negative tone.
    positions = _find_brand_mentions(answer, _alias_keys(brand, brand_aliases))
    windows = [lower[max(0, p - _SENTIMENT_WINDOW): p + _SENTIMENT_WINDOW] for p in positions]
    context = " ".join(windows) if windows else lower
    pos_hits = _count_terms(context, pos_words)
    neg_hits = _count_terms(context, neg_words)
    if pos_hits + neg_hits == 0:
        result.sentiment_label, result.sentiment_score = "neutral", 0.0
    else:
        score = (pos_hits - neg_hits) / (pos_hits + neg_hits)
        result.sentiment_score = round(max(-1.0, min(1.0, score)), 3)
        result.sentiment_label = (
            "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
        )

    rank, from_list = _brand_rank(result, brand, brand_aliases)
    result.brand_rank_position = rank

    # Recommendation strength — only "strong" when there's an explicit signal: the brand
    # tops an actual numbered list, or recommend-words sit near the brand. Being placed
    # in a list below #1 is "moderate"; a positive-but-unranked mention is "moderate";
    # a merely-named mention is "weak".
    recommend_near = _count_terms(context, rec_words) > 0
    if (from_list and rank == 1) or (recommend_near and not (from_list and rank and rank > 1)):
        result.recommendation_strength, result.recommendation_score = "strong", 1.0
    elif (from_list and rank and rank > 1) or result.sentiment_label == "positive":
        result.recommendation_strength, result.recommendation_score = "moderate", 0.6
    else:
        result.recommendation_strength, result.recommendation_score = "weak", 0.3
    return result


def geo_weights(config: dict[str, Any]) -> dict[str, float]:
    """Load the (tunable) GEO scoring weights from config, falling back to defaults."""
    scoring = config.get("scoring") or {}
    return {key: float(scoring.get(key, default)) for key, default in _DEFAULT_WEIGHTS.items()}


def sentiment_words(config: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Config-editable positive/negative/recommend keyword lists (with defaults)."""
    sent = (config.get("scoring") or {}).get("sentiment") or {}

    def _as_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, list) and value:
            return tuple(str(v).strip() for v in value if str(v).strip())
        return default

    return {
        "pos_words": _as_tuple(sent.get("positive"), _POSITIVE_WORDS),
        "neg_words": _as_tuple(sent.get("negative"), _NEGATIVE_WORDS),
        "rec_words": _as_tuple(sent.get("recommend"), _RECOMMEND_WORDS),
    }


def neutral_accuracy_value(config: dict[str, Any]) -> float:
    """The neutral value used for unevaluated accuracy. New key with legacy fallback."""
    scoring = config.get("scoring") or {}
    if "neutral_accuracy_value" in scoring:
        return float(scoring["neutral_accuracy_value"])
    return float(scoring.get("accuracy_unknown_score", 0.5))


def _entity_quality(
    measured: list[GeoQueryResult],
    name: str,
    pos_words: tuple[str, ...],
    neg_words: tuple[str, ...],
    rec_words: tuple[str, ...],
) -> dict[str, Any] | None:
    """Aggregate sentiment / recommendation / best rank for ONE entity (competitor).

    Mirrors the brand signals but for an arbitrary name, aggregated across the answers
    that mention it. Used for the zero-visibility pivot ("who DID get mentioned and how").
    Returns None if the entity isn't mentioned anywhere.
    """
    keys = _alias_keys(name)
    sent_scores: list[float] = []
    ranks: list[int] = []
    strengths: list[int] = []
    answers = 0
    for result in measured:
        answer = result.answer or ""
        positions = _find_brand_mentions(answer, keys)
        if not positions:
            continue
        answers += 1
        lower = answer.lower()
        context = " ".join(lower[max(0, p - _SENTIMENT_WINDOW): p + _SENTIMENT_WINDOW] for p in positions)
        pos_h, neg_h = _count_terms(context, pos_words), _count_terms(context, neg_words)
        score = (pos_h - neg_h) / (pos_h + neg_h) if (pos_h + neg_h) else 0.0
        sent_scores.append(max(-1.0, min(1.0, score)))
        rank = None
        for match in _NUMBERED_LIST_RE.finditer(answer):
            if _find_brand_mentions(match.group(2), keys):
                rank = int(match.group(1))
                break
        if rank:
            ranks.append(rank)
        if rank == 1 or _count_terms(context, rec_words) > 0:
            strengths.append(3)
        elif score > 0.15:
            strengths.append(2)
        else:
            strengths.append(1)
    if not answers:
        return None
    avg = sum(sent_scores) / len(sent_scores)
    label = "positive" if avg > 0.15 else "negative" if avg < -0.15 else "neutral"
    avg_strength = sum(strengths) / len(strengths)
    rec = "strong" if avg_strength >= 2.5 else "moderate" if avg_strength >= 1.5 else "weak"
    return {
        "name": name,
        "mentions": answers,
        "sentiment_label": label,
        "recommendation_strength": rec,
        "rank": min(ranks) if ranks else None,
    }


def build_engine_quality(
    results: list[GeoQueryResult],
    brand: str,
    brand_aliases: list[str],
    words: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    """Per-engine GEO quality aggregates with EXPLICIT, consistent denominators.

    Single source of truth for both dashboards so labels and math match:
      - sentiment / recommendation / brand rank → over BRAND-MENTION answers only.
      - citation coverage / competitor mentions → over ALL measured answers.
      - SoV = brand-mention answers / measured answers.
      - top_competitors: ranked by # answers mentioning them (name-normalised).
      - competitor_leaders: top-3 rivals with their sentiment/recommendation/rank
        (the zero-visibility pivot — "what winning answers look like").
    """
    measured = [r for r in results if not r.error]
    n_all = len(measured)
    mentioned = [r for r in measured if r.brand_mentioned]
    n_mentions = len(mentioned)

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    sent_scores = [float(r.sentiment_score or 0.0) for r in mentioned]
    rec_scores = [float(r.recommendation_score or 0.0) for r in mentioned]
    ranks = [r.brand_rank_position for r in mentioned if r.brand_rank_position]

    # Competitor mentions counted once per answer, collapsing case/punct variants.
    counts: dict[str, list] = {}  # norm-key -> [display, answers_count]
    for result in measured:
        seen: set[str] = set()
        for raw in result.competitors_found or []:
            key = _norm_key(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            if key not in counts:
                counts[key] = [raw, 0]
            counts[key][1] += 1
    top = sorted(counts.values(), key=lambda dc: (-dc[1], dc[0].lower()))
    top_competitors = [{"name": d, "count": c} for d, c in top[:8]]
    competitor_total = sum(c for _, c in counts.values())

    leaders = [
        q for q in (_entity_quality(measured, d, words["pos_words"], words["neg_words"], words["rec_words"])
                    for d, _ in top[:3]) if q
    ]

    return {
        "answers_total": n_all,
        "brand_mentions": n_mentions,
        "sov": round(n_mentions / n_all, 4) if n_all else 0.0,
        "sentiment": {
            "avg": _avg(sent_scores),
            "positive": sum(1 for r in mentioned if r.sentiment_label == "positive"),
            "neutral": sum(1 for r in mentioned if r.sentiment_label == "neutral"),
            "negative": sum(1 for r in mentioned if r.sentiment_label == "negative"),
        },
        "recommendation": {
            "avg": _avg(rec_scores),
            "strong": sum(1 for r in mentioned if r.recommendation_strength == "strong"),
            "moderate": sum(1 for r in mentioned if r.recommendation_strength == "moderate"),
            "weak": sum(1 for r in mentioned if r.recommendation_strength == "weak"),
        },
        "avg_brand_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "citations_answers": sum(1 for r in measured if r.citations_present),
        "citation_coverage": round(sum(1 for r in measured if r.citations_present) / n_all, 4) if n_all else 0.0,
        "competitor_total": competitor_total,
        "top_competitors": top_competitors,
        "competitor_leaders": leaders,
    }


def per_query_geo_score(
    result: GeoQueryResult,
    weights: dict[str, float],
    accuracy_neutral: float = 0.5,
) -> float | None:
    """Weighted per-query GEO score (0..100). None for errored (unmeasured) rows.

    Explainable formula — weighted average of six 0..1 component scores:
        visibility   (1 if the brand is mentioned, else 0)
        prominence   (existing 0..1 prominence of the first mention)
        sentiment    (sentiment_score mapped from -1..1 to 0..1)
        recommendation (0..1 recommendation_score)
        citation     (1 if any source link present, else 0)
        accuracy     (accurate=1, partial=0.5, inaccurate=0, unknown=neutral)
    A brand that is NOT mentioned scores 0 — visibility gates the quality signals,
    so an absent brand never earns sentiment/citation/accuracy credit.
    """
    if result.error:
        return None
    if not result.brand_mentioned:
        return 0.0
    total = sum(weights.values()) or 1.0
    accuracy = _ACCURACY_VALUE.get(result.answer_accuracy_label, accuracy_neutral)
    combined = (
        weights["visibility_weight"] * 1.0
        + weights["prominence_weight"] * (result.prominence_score or 0.0)
        + weights["sentiment_weight"] * ((result.sentiment_score + 1.0) / 2.0)
        + weights["recommendation_weight"] * (result.recommendation_score or 0.0)
        + weights["citation_weight"] * (1.0 if result.citations_present else 0.0)
        + weights["accuracy_weight"] * accuracy
    ) / total
    return round(combined * 100, 1)


def _engine_stats(results: list[GeoQueryResult]) -> dict[str, Any]:
    """GEO score + visibility/prominence stats for one engine's query results.

    The engine GEO score is the mean of the per-query GEO scores (which already blend
    visibility, prominence, sentiment, recommendation, citations, accuracy). Errored
    rows are excluded; measured-but-absent rows contribute 0.
    """
    measured = [r for r in results if not r.error]
    scores = [r.per_query_geo_score for r in measured if r.per_query_geo_score is not None]
    prominences = [r.prominence_score for r in measured if r.prominence_score is not None]
    mentions = sum(1 for r in measured if r.brand_mentioned)
    web_grounded = bool(results) and all(r.web_grounded for r in results)
    sources_count = sum(int(r.sources_count or 0) for r in results)
    return {
        "geo_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "visibility_rate": round(mentions / len(measured), 4) if measured else 0.0,
        "queries_run": len(results),
        "brand_mentions": mentions,
        "avg_prominence": round(sum(prominences) / len(prominences), 4) if prominences else 0.0,
        "web_grounded": web_grounded,
        "sources_count": sources_count,
    }


def overall_grounded_score(engine_scores: list[dict[str, Any]]) -> float:
    """Headline GEO score = average of ENABLED, WEB-GROUNDED engines that ran.

    Ungrounded engines (e.g. DeepSeek) and errored/empty engines are excluded so an
    ungrounded model can't drag a live-visibility metric. Returns 0.0 if none qualify.
    """
    grounded = [
        e["geo_score"]
        for e in engine_scores
        if e.get("error") is None and e.get("queries_run") and e.get("web_grounded")
    ]
    return round(sum(grounded) / len(grounded), 1) if grounded else 0.0


def score_geo(report: GeoReport) -> float:
    """Compute a GEO score across all of a report's query results (single-engine helper)."""
    score = _engine_stats(report.results)["geo_score"]
    report.geo_score = score
    return score


def _measurement_input(query: str) -> str:
    """Frame a measurement query to encourage a current, web-informed answer.

    Brand-neutral on purpose — it must not bias the answer toward any brand; it only
    nudges the model to browse so the result reflects a real browsing assistant.
    """
    return (
        "Use web search to find current information, then answer the question for a "
        "general user. Recommend specific brands/companies where relevant.\n\n"
        f"Question: {query}"
    )


# Minimal ISO-3166 alpha-2 → display-region map for the query-suffix fallback (used when
# a provider exposes no native locale parameter). Extend as needed; an unknown code falls
# back to the code itself so grounding still happens, just with a less natural region word.
COUNTRY_NAMES: dict[str, str] = {
    "AU": "Australia", "US": "the United States", "GB": "the United Kingdom",
    "NZ": "New Zealand", "CA": "Canada", "IE": "Ireland", "IN": "India",
    "SG": "Singapore", "ZA": "South Africa", "DE": "Germany", "FR": "France",
    "ES": "Spain", "IT": "Italy", "NL": "the Netherlands", "JP": "Japan",
    "BR": "Brazil", "MX": "Mexico", "AE": "the United Arab Emirates",
}


def _normalize_locale(value: Any) -> dict[str, str] | None:
    """Coerce a config locale value into ``{"country","region"}`` or None (global).

    Accepts: a code string ("AU"), the literal "global"/"" (→ None), or a dict
    ``{country, region}`` (region optional — filled from COUNTRY_NAMES). Returns None for
    anything that resolves to no grounding.
    """
    if value is None:
        return None
    if isinstance(value, str):
        code = value.strip()
        if not code or code.lower() == "global":
            return None
        country = code.upper()
        return {"country": country, "region": COUNTRY_NAMES.get(country, code)}
    if isinstance(value, dict):
        country = str(value.get("country") or "").strip().upper()
        region = str(value.get("region") or "").strip()
        if not country and not region:
            return None
        if country and country.lower() == "global":
            return None
        return {"country": country, "region": region or COUNTRY_NAMES.get(country, country)}
    return None


def audit_default_locale(config: dict[str, Any]) -> dict[str, str] | None:
    """The audit/client-level default locale (``geo.locale`` or top-level ``locale``)."""
    geo = config.get("geo") if isinstance(config.get("geo"), dict) else {}
    return _normalize_locale(geo.get("locale") if geo.get("locale") is not None else config.get("locale"))


def normalize_queries(queries: Any, audit_default: dict[str, str] | None) -> list[dict[str, Any]]:
    """Resolve the configured query set into ``[{"text", "locale"}]``.

    Each entry may be a plain string (inherits ``audit_default``) or an object
    ``{text, locale}`` where ``locale`` is a code, ``"global"`` (explicit no grounding),
    or ``{country, region}``. Resolution order: per-query locale > audit default > global.
    Backward compatible: a list of plain strings behaves exactly as before plus the
    audit default.
    """
    resolved: list[dict[str, Any]] = []
    for item in queries or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            locale = audit_default if "locale" not in item else _normalize_locale(item.get("locale"))
            resolved.append({"text": text, "locale": locale})
        else:
            text = str(item or "").strip()
            if text:
                resolved.append({"text": text, "locale": audit_default})
    return resolved


def _localized_question(query: str, locale: dict[str, str] | None) -> str:
    """Append the region to the question text (the suffix fallback). Global → unchanged."""
    if locale and locale.get("region"):
        return f"{query} in {locale['region']}"
    return query


def _run_engine(
    client: EngineClient,
    queries: list[dict[str, Any]],
    brand: str,
    brand_aliases: list[str],
    competitors: list[str],
    extract_settings: dict[str, Any],
    quality_cfg: dict[str, Any],
    emit: Callable[[dict], None],
    index_offset: int,
    grand_total: int,
) -> list[GeoQueryResult]:
    """Run every query through ONE engine client; return results tagged provider/model.

    The per-query measurement/retry/error handling is identical across engines — only
    the answer SOURCE (``client.measure``) differs.
    """
    do_extract = extract_settings.get("enabled") and extract_settings.get("client") is not None

    def _is_empty(text: str | None) -> bool:
        return not (text or "").strip()

    results: list[GeoQueryResult] = []
    for i, item in enumerate(queries, 1):
        query = item["text"]
        locale = item.get("locale")
        locale_applied = locale["country"] if locale and locale.get("country") else "global"
        locale_method = "none"
        web_search_used = False
        sources: list[dict] = []
        finish_reason = ""
        try:
            res = client.measure(query, locale)
            answer = res.get("text", "")
            web_search_used = bool(res.get("web_search_used"))
            sources = res.get("sources") or []
            locale_method = res.get("locale_method", "none")
            finish_reason = res.get("finish_reason", "") or ""
            if _is_empty(answer):
                # Empty (reasoning ate the budget, or a slow web-search call returned
                # nothing) — retry once.
                res = client.measure(query, locale)
                answer = res.get("text", "")
                web_search_used = bool(res.get("web_search_used"))
                sources = res.get("sources") or []
                locale_method = res.get("locale_method", locale_method)
                finish_reason = res.get("finish_reason", "") or finish_reason
            if _is_empty(answer):
                # Still empty: a measurement FAILURE, NOT a genuine "brand absent". Carry the
                # provider's finish reason so a truncated/incomplete answer is actionable
                # (e.g. "raise web_search.max_output_tokens") instead of a silent 0%.
                detail = f" ({finish_reason})" if finish_reason else ""
                hint = (" — raise web_search.max_output_tokens"
                        if "max_output_tokens" in finish_reason else "")
                result = GeoQueryResult(
                    query=query, engine=client.provider, answer="",
                    error=f"engine returned no answer after retry{detail}{hint}",
                    web_search_used=web_search_used, sources=sources,
                    provider=client.provider, model=client.model,
                    api_key_source=client.api_key_source,
                )
            else:
                result = GeoQueryResult(
                    query=query, engine=client.provider, answer=answer, error=None,
                    web_search_used=web_search_used, sources=sources,
                    provider=client.provider, model=client.model,
                    api_key_source=client.api_key_source,
                )
        except Exception as exc:
            # Error/timeout — leave it unscored; never record a false zero for a query
            # that didn't actually run.
            result = GeoQueryResult(
                query=query, engine=client.provider, answer="", error=str(exc),
                web_search_used=False, sources=[],
                provider=client.provider, model=client.model,
                api_key_source=client.api_key_source,
            )

        # Grounding evidence: whether this engine browses, and how many live sources.
        result.web_grounded = client.web_grounded
        result.sources_count = len(result.sources or [])
        # Locale grounding actually applied (kept even on error rows, for debuggability).
        result.locale_applied = locale_applied
        result.locale_method = locale_method

        # detect_brand_mentions early-returns on error, so error rows keep the default
        # (unmeasured) state and are excluded from scoring/visibility.
        detect_brand_mentions(result, brand, competitors, aliases=brand_aliases)
        result.prominence_score = _prominence(result)

        # Populate competitors_found from the answer text itself (only for measured rows).
        if do_extract and not result.error and result.answer:
            result.competitors_found = extract_competitors(
                result.answer,
                extract_settings["client"],
                extract_settings["model"],
                brand_aliases,
                extract_settings["max_tokens"],
            )

        # Rule-based GEO quality signals + richer per-query score (deterministic, offline).
        _w = quality_cfg["words"]
        analyze_quality_signals(
            result, brand, brand_aliases, quality_cfg["accuracy_keywords"],
            pos_words=_w["pos_words"], neg_words=_w["neg_words"], rec_words=_w["rec_words"],
        )
        result.per_query_geo_score = per_query_geo_score(
            result, quality_cfg["weights"], quality_cfg["accuracy_neutral"]
        )

        results.append(result)
        emit({
            "phase": "geo", "index": index_offset + i, "total": grand_total, "query": query,
            "provider": client.provider, "model": client.model,
            "web_search_used": result.web_search_used, "error": result.error,
        })
    return results


def run_geo(config: dict[str, Any], progress: Callable[[dict], None] | None = None) -> GeoReport:
    """Run the configured query set across every ENABLED engine/model and aggregate.

    Brand visibility is tracked separately per provider/model (``report.engine_scores``);
    the overall ``geo_score`` is the average of the per-engine scores. ``progress`` is
    called once per (engine, query) with ``{phase, index, total, query, provider, model,
    web_search_used, error}``; it must never raise.

    Backward compatible: a legacy single-engine config produces one engine, so the
    overall score and per-query behaviour match the previous implementation.
    """
    brand = config.get("brand", "Unknown Brand")
    # Resolve each query into {text, locale}: per-query override > audit default > global.
    queries = normalize_queries(config.get("queries", []), audit_default_locale(config))
    competitors = config.get("competitors", [])
    brand_aliases = config.get("brand_aliases") or [brand]
    openai_cfg = config.get("openai", {})
    ws_cfg = config.get("web_search", {})
    audit_settings = config.get("audit_settings") or {}
    api_key_source = str(audit_settings.get("api_key_source") or "env")
    temporary_api_key = str(config.get("_temporary_api_key") or "").strip() or None

    def _emit(event: dict) -> None:
        if progress is not None:
            try:
                progress(event)
            except Exception:  # a UI callback must never break the run
                pass

    # Competitor auto-extraction uses the shared OpenAI client regardless of the
    # measurement engine. Set it up once; disable gracefully if the client is unavailable.
    ce_cfg = config.get("competitor_extraction", {})
    extraction_client = None
    if bool(ce_cfg.get("enabled", True)):
        try:
            from src.clients.openai_client import client as extraction_client
        except Exception as exc:
            logger.warning("Competitor extraction disabled (OpenAI client unavailable): %s", exc)
            extraction_client = None
    extract_settings = {
        "enabled": bool(ce_cfg.get("enabled", True)),
        "client": extraction_client,
        "model": str(ce_cfg.get("model", "gpt-4o-mini")),
        "max_tokens": int(ce_cfg.get("max_completion_tokens", 300)),
    }

    # Tunable scoring weights + accuracy settings + (config-editable) sentiment words.
    scoring_cfg = config.get("scoring") or {}
    quality_cfg = {
        "weights": geo_weights(config),
        "accuracy_neutral": neutral_accuracy_value(config),
        "accuracy_keywords": list(scoring_cfg.get("accuracy_keywords") or config.get("accuracy_keywords") or []),
        "words": sentiment_words(config),
    }

    engines = _resolve_engines(config)
    grand_total = len(engines) * len(queries)

    all_results: list[GeoQueryResult] = []
    engine_scores: list[dict[str, Any]] = []
    labels: list[str] = []
    index_offset = 0

    for engine in engines:
        provider, model = engine["provider"], engine["model"]
        labels.append(f"{provider}/{model}")
        try:
            client = create_engine_client(
                provider,
                model,
                openai_cfg=openai_cfg,
                web_search_cfg=ws_cfg,
                api_key=temporary_api_key if api_key_source == "temporary" else None,
                api_key_source=api_key_source if provider != "mock" else "none",
            )
        except Exception as exc:
            # An enabled-but-unavailable engine (missing key / not implemented) is
            # surfaced, not silently dropped, and never crashes the other engines.
            logger.warning("Engine %s/%s skipped: %s", provider, model, exc)
            engine_scores.append({
                "provider": provider, "model": model, "geo_score": 0.0,
                "visibility_rate": 0.0, "queries_run": 0, "brand_mentions": 0,
                "avg_prominence": 0.0, "api_key_source": api_key_source if provider != "mock" else "none",
                "web_grounded": False, "sources_count": 0, "grounding_warning": None,
                "quality": None,
                "error": str(exc),
            })
            _emit({"phase": "geo_engine_error", "provider": provider, "model": model, "error": str(exc)})
            continue

        engine_results = _run_engine(
            client, queries, brand, brand_aliases, competitors,
            extract_settings, quality_cfg, _emit, index_offset, grand_total,
        )
        index_offset += len(queries)
        all_results.extend(engine_results)
        stats = _engine_stats(engine_results)
        # Flag a search-capable engine that returned zero live sources across all
        # queries — likely a grounding/config problem, not a clean run.
        grounding_warning = None
        if SUPPORTS_WEB_SEARCH.get(provider) and stats["queries_run"] and stats["sources_count"] == 0:
            grounding_warning = "0 live sources returned — check grounding/config."
        # If queries ran but EVERY one failed to return a usable answer, this is an engine
        # ERROR, not a real 0% — mark it so the breakdown/PDF show a clear failure state
        # rather than "brand mentioned in 0 of 0 answers". Surface a representative reason.
        measured_rows = [r for r in engine_results if not r.error]
        engine_error = None
        if stats["queries_run"] and not measured_rows:
            sample = next((r.error for r in engine_results if r.error), "no answer returned")
            engine_error = (
                f"{stats['queries_run']} query(ies) ran but returned no usable answer "
                f"(e.g. {sample}). Not a real 0% — the engine produced no answers."
            )
        engine_scores.append({
            "provider": provider, "model": model,
            **stats,
            "api_key_source": client.api_key_source,
            "grounding_warning": grounding_warning,
            # No usable answers → no quality signals (don't render a misleading "0 of 0"
            # block; the engine error explains the failure instead).
            "quality": None if engine_error else build_engine_quality(
                engine_results, brand, brand_aliases, quality_cfg["words"]),
            "error": engine_error,
        })

    # Collapse case/punctuation variants to one display per brand BEFORE aggregating,
    # so the summary and Share of Voice count each brand once (across all engines).
    normalize_competitor_names(all_results)

    # Overall = average of ENABLED, WEB-GROUNDED engines only, so an ungrounded engine
    # (e.g. DeepSeek) can't drag a live-visibility metric. Ungrounded engines still
    # appear in the breakdown table, just excluded from this headline number.
    overall = overall_grounded_score(engine_scores)

    report = GeoReport(
        brand=brand,
        engine=", ".join(labels) or "none",
        results=all_results,
        geo_score=overall,
    )
    report.engine_scores = engine_scores
    report.competitors_summary = build_competitors_summary(all_results)
    report.share_of_voice = build_share_of_voice(all_results, brand, brand_aliases)
    report.sov_headline = sov_headline(report.share_of_voice, brand)
    return report


def load_geo_config(path: str = "config/geo_config.yaml") -> dict[str, Any]:
    """Load GEO configuration from a YAML file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def main() -> None:
    config = load_geo_config()
    report = run_geo(config)

    print(f"Brand: {report.brand}")
    print(f"Engine: {report.engine}")
    print(f"Queries: {len(report.results)}\n")

    mentioned_count = 0
    for result in report.results:
        query_score = 0.0
        if not result.error and result.brand_mentioned and result.first_position is not None and result.answer:
            query_score = round(max(0.3, min(1.0, 1.0 - (result.first_position / len(result.answer)))) * 100, 1)
            mentioned_count += 1

        print(f"Query: {result.query}")
        if result.error:
            print(f"  Error: {result.error}")
        else:
            preview = result.answer[:120] + "..." if len(result.answer) > 120 else result.answer
            print(f"  Answer: {preview}")
            print(f"  Brand mentioned: {'yes' if result.brand_mentioned else 'no'}")
            print(f"  Mention count: {result.mention_count}")
            print(f"  First position: {result.first_position}")
            print(f"  Query GEO sub-score: {query_score}%")
            if result.competitors_found:
                print(f"  Competitors found: {', '.join(result.competitors_found)}")
        print()

    # Exclude measurement errors from the denominator — they aren't genuine misses.
    measured = [r for r in report.results if not r.error]
    errored = len(report.results) - len(measured)
    visibility_score = round((mentioned_count / len(measured)) * 100, 1) if measured else 0.0
    print(f"Brand visibility: {visibility_score}% of {len(measured)} measured queries")
    if errored:
        print(f"  ({errored} query(ies) excluded: no answer returned)")
    print(f"Overall GEO score: {report.geo_score}%")


if __name__ == "__main__":
    main()
