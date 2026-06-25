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


class EngineClient(ABC):
    """Abstract base for AI engine clients. Each client knows its provider + model."""

    provider: str = "mock"
    model: str = "mock-default"

    @abstractmethod
    def query(self, prompt: str) -> str:
        """Send a query to the engine and return the answer text."""

    def measure(self, prompt: str) -> dict[str, Any]:
        """Return ``{"text", "web_search_used", "sources"}`` for a measurement query.

        The default wraps ``query`` (no browsing). Live clients override to add web
        search and citation capture. Only the SOURCE of the answer differs between
        engines — brand detection / scoring downstream are identical.
        """
        return {"text": self.query(prompt), "web_search_used": False, "sources": []}


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

    def __init__(self, model: str = "mock-default") -> None:
        self.model = model or "mock-default"

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
    ) -> None:
        self.model = model or "gpt-5.5"
        oc = openai_cfg or {}
        ws = web_search_cfg or {}
        self._measure_tokens = int(oc.get("measurement_max_completion_tokens", 2000))
        self._reasoning = oc.get("reasoning_effort") or None
        self._ws_enabled = bool(ws.get("enabled", True))
        self._ws_reasoning = ws.get("reasoning_effort") or self._reasoning or "low"
        self._ws_timeout = float(ws.get("timeout", 180))
        self._ws_max = int(ws.get("max_output_tokens", self._measure_tokens))
        try:
            from src.clients.openai_client import client as openai_client
        except Exception as exc:  # missing key, import/config error — surface clearly
            raise RuntimeError(
                f"OpenAI engine ('{self.model}') is unavailable: {exc}. "
                "Set OPENAI_API_KEY, or disable this engine in geo_config.yaml (enabled: false)."
            ) from exc
        self._client = openai_client

    @property
    def client(self) -> Any:
        """The shared OpenAI client (reused for competitor extraction)."""
        return self._client

    def measure(self, prompt: str) -> dict[str, Any]:
        if self._ws_enabled:
            return self._client.respond_with_web_search(
                _measurement_input(prompt),
                reasoning_effort=self._ws_reasoning,
                max_output_tokens=self._ws_max,
                model=self.model,
                timeout=self._ws_timeout,
            )
        text = self._client.chat(
            prompt,
            max_completion_tokens=self._measure_tokens,
            reasoning_effort=self._reasoning,
            model=self.model,
        )
        return {"text": text, "web_search_used": False, "sources": []}

    def query(self, prompt: str) -> str:
        return self.measure(prompt).get("text", "")


def create_engine_client(
    provider: str,
    model: str,
    openai_cfg: dict[str, Any] | None = None,
    web_search_cfg: dict[str, Any] | None = None,
) -> EngineClient:
    """Factory: build an EngineClient for a provider/model pair (from config).

    Supported: ``mock`` (offline) and ``openai`` (live). ``anthropic``/``perplexity``
    are recognised but not implemented yet — they raise a clear, actionable error so a
    misconfigured-but-enabled engine fails loudly rather than silently. Disabled engines
    are filtered out before this is called.
    """
    p = (provider or "mock").strip().lower()
    if p == "mock":
        return MockEngineClient(model=model or "mock-default")
    if p == "openai":
        return OpenAIEngineClient(model=model or "gpt-5.5", openai_cfg=openai_cfg, web_search_cfg=web_search_cfg)
    if p == "anthropic":
        raise NotImplementedError(
            f"Anthropic engine ('{model}') is not implemented yet. Disable it in "
            "geo_config.yaml (enabled: false), or add an Anthropic client + ANTHROPIC_API_KEY."
        )
    if p == "perplexity":
        raise NotImplementedError(
            f"Perplexity engine ('{model}') is not implemented yet. Disable it in "
            "geo_config.yaml (enabled: false), or add a Perplexity client + PERPLEXITY_API_KEY."
        )
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
) -> GeoQueryResult:
    """Populate the rule-based GEO quality signals on a query result, in place.

    Deterministic and offline — no extra model call. Errored/absent rows get safe
    defaults ("unknown"/"none"). See field docs on GeoQueryResult.
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
    pos_hits = _count_terms(context, _POSITIVE_WORDS)
    neg_hits = _count_terms(context, _NEGATIVE_WORDS)
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
    recommend_near = _count_terms(context, _RECOMMEND_WORDS) > 0
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
    return {
        "geo_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "visibility_rate": round(mentions / len(measured), 4) if measured else 0.0,
        "queries_run": len(results),
        "brand_mentions": mentions,
        "avg_prominence": round(sum(prominences) / len(prominences), 4) if prominences else 0.0,
    }


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


def _run_engine(
    client: EngineClient,
    queries: list[str],
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
    for i, query in enumerate(queries, 1):
        web_search_used = False
        sources: list[dict] = []
        try:
            res = client.measure(query)
            answer = res.get("text", "")
            web_search_used = bool(res.get("web_search_used"))
            sources = res.get("sources") or []
            if _is_empty(answer):
                # Empty (reasoning ate the budget, or a slow web-search call returned
                # nothing) — retry once.
                res = client.measure(query)
                answer = res.get("text", "")
                web_search_used = bool(res.get("web_search_used"))
                sources = res.get("sources") or []
            if _is_empty(answer):
                # Still empty: a measurement failure, NOT a genuine "brand absent".
                result = GeoQueryResult(
                    query=query, engine=client.provider, answer="",
                    error="empty completion — no answer returned after retry",
                    web_search_used=web_search_used, sources=sources,
                    provider=client.provider, model=client.model,
                )
            else:
                result = GeoQueryResult(
                    query=query, engine=client.provider, answer=answer, error=None,
                    web_search_used=web_search_used, sources=sources,
                    provider=client.provider, model=client.model,
                )
        except Exception as exc:
            # Error/timeout — leave it unscored; never record a false zero for a query
            # that didn't actually run.
            result = GeoQueryResult(
                query=query, engine=client.provider, answer="", error=str(exc),
                web_search_used=False, sources=[],
                provider=client.provider, model=client.model,
            )

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
        analyze_quality_signals(result, brand, brand_aliases, quality_cfg["accuracy_keywords"])
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
    queries = config.get("queries", [])
    competitors = config.get("competitors", [])
    brand_aliases = config.get("brand_aliases") or [brand]
    openai_cfg = config.get("openai", {})
    ws_cfg = config.get("web_search", {})

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

    # Tunable scoring weights + accuracy settings for the per-query GEO quality score.
    scoring_cfg = config.get("scoring") or {}
    quality_cfg = {
        "weights": geo_weights(config),
        "accuracy_neutral": float(scoring_cfg.get("accuracy_unknown_score", 0.5)),
        "accuracy_keywords": list(scoring_cfg.get("accuracy_keywords") or config.get("accuracy_keywords") or []),
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
            client = create_engine_client(provider, model, openai_cfg=openai_cfg, web_search_cfg=ws_cfg)
        except Exception as exc:
            # An enabled-but-unavailable engine (missing key / not implemented) is
            # surfaced, not silently dropped, and never crashes the other engines.
            logger.warning("Engine %s/%s skipped: %s", provider, model, exc)
            engine_scores.append({
                "provider": provider, "model": model, "geo_score": 0.0,
                "visibility_rate": 0.0, "queries_run": 0, "brand_mentions": 0,
                "avg_prominence": 0.0, "error": str(exc),
            })
            _emit({"phase": "geo_engine_error", "provider": provider, "model": model, "error": str(exc)})
            continue

        engine_results = _run_engine(
            client, queries, brand, brand_aliases, competitors,
            extract_settings, quality_cfg, _emit, index_offset, grand_total,
        )
        index_offset += len(queries)
        all_results.extend(engine_results)
        engine_scores.append({
            "provider": provider, "model": model,
            **_engine_stats(engine_results), "error": None,
        })

    # Collapse case/punctuation variants to one display per brand BEFORE aggregating,
    # so the summary and Share of Voice count each brand once (across all engines).
    normalize_competitor_names(all_results)

    # Overall = average of the engines that actually ran (don't penalise for an
    # unimplemented/keyless engine that produced no score).
    ran = [e["geo_score"] for e in engine_scores if e.get("error") is None and e.get("queries_run")]
    overall = round(sum(ran) / len(ran), 1) if ran else 0.0

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
