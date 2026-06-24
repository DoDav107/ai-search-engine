"""GEO research agent for measuring brand visibility in AI engine answers."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..engine.models import GeoQueryResult, GeoReport

logger = logging.getLogger(__name__)


class EngineClient(ABC):
    """Abstract base for AI engine clients."""

    @abstractmethod
    def query(self, prompt: str) -> str:
        """Send a query to the engine and return the answer."""
        pass


class MockEngineClient(EngineClient):
    """Mock engine client returning deterministic answers for testing."""

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

    def query(self, prompt: str) -> str:
        """Return a mock answer, deterministic based on the query."""
        return self._CANNED_ANSWERS.get(prompt, f"Mock answer to: {prompt}")


def get_engine_client(config: dict[str, Any]) -> EngineClient:
    """Return an engine client matching the configured engine type."""
    engine_type = config.get("engine", "mock").lower()
    if engine_type == "mock":
        return MockEngineClient()
    elif engine_type == "anthropic":
        raise NotImplementedError("Anthropic client will be implemented once the API key is provisioned.")
    elif engine_type == "openai":
        raise NotImplementedError("OpenAI client will be implemented once the API key is provisioned.")
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")


def detect_brand_mentions(result: GeoQueryResult, brand: str, competitors: list[str]) -> GeoQueryResult:
    """Detect brand and competitor mentions in an engine answer."""
    if result.error:
        return result

    answer = result.answer or ""
    brand_pattern = re.compile(rf"\b{re.escape(brand)}\b", re.IGNORECASE)
    mentions = list(brand_pattern.finditer(answer))
    result.mention_count = len(mentions)
    result.brand_mentioned = bool(mentions)
    result.first_position = mentions[0].start() if mentions else None

    found_competitors: list[str] = []
    for competitor in competitors:
        competitor_pattern = re.compile(rf"\b{re.escape(competitor)}\b", re.IGNORECASE)
        if competitor_pattern.search(answer):
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


def _norm_key(name: str) -> str:
    """Matching key for a brand: casefold + drop all punctuation/whitespace.

    Collapses case and punctuation variants so "HOKA"/"Hoka" → "hoka" and
    "R.A.D"/"R.A.D." → "rad" map to one brand. Display forms are kept separately.
    """
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


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


def score_geo(report: GeoReport) -> float:
    """Compute a GEO score from brand mention prominence across queries."""
    query_values: list[float] = []
    for result in report.results:
        # Measurement errors (e.g. empty completions) are excluded entirely — they are
        # not genuine "brand absent" results, so they must not drag the score down.
        if result.error:
            continue

        if not result.brand_mentioned or not result.answer:
            query_values.append(0.0)
            continue

        answer_length = len(result.answer)
        if answer_length <= 0 or result.first_position is None:
            query_values.append(0.0)
            continue

        prominence = 1.0 - (result.first_position / answer_length)
        prominence = max(0.3, min(prominence, 1.0))
        query_values.append(prominence)

    if not query_values:
        report.geo_score = 0.0
        return 0.0

    score = round((sum(query_values) / len(query_values)) * 100, 1)
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


def run_geo(config: dict[str, Any], progress: Callable[[dict], None] | None = None) -> GeoReport:
    """Run GEO queries and collect brand visibility data.

    ``progress`` (optional) is called once per query with a dict
    ``{"phase": "geo", "index", "total", "query", "web_search_used", "error"}`` so a UI
    can stream per-query status. It must never raise; callback errors are swallowed.
    """
    brand = config.get("brand", "Unknown Brand")
    engine_type = config.get("engine", "mock")
    queries = config.get("queries", [])
    competitors = config.get("competitors", [])

    def _emit(event: dict) -> None:
        if progress is not None:
            try:
                progress(event)
            except Exception:  # a UI callback must never break the run
                pass

    openai_cfg = config.get("openai", {})
    openai_mode = openai_cfg.get("mode", "mock")
    ws_cfg = config.get("web_search", {})
    ws_enabled = bool(ws_cfg.get("enabled", True))
    openai_client = None

    # Each measurement returns a dict: {"text", "web_search_used", "sources"}. Only the
    # SOURCE of the answer differs between paths — brand detection / scoring are unchanged.
    if openai_mode == "live":
        from src.clients.openai_client import client as openai_client
        # Measurement needs more token headroom than the default so the reasoning model
        # has room for both reasoning and the answer; low reasoning effort helps too.
        measure_tokens = int(openai_cfg.get("measurement_max_completion_tokens", 2000))
        reasoning_effort = openai_cfg.get("reasoning_effort") or None

        if ws_enabled:
            # Live web search via the Responses API — reflects a browsing assistant.
            ws_reasoning = ws_cfg.get("reasoning_effort") or reasoning_effort or "low"
            ws_timeout = float(ws_cfg.get("timeout", 180))
            ws_max = int(ws_cfg.get("max_output_tokens", measure_tokens))

            def _measure(q: str) -> dict[str, Any]:
                return openai_client.respond_with_web_search(
                    _measurement_input(q),
                    reasoning_effort=ws_reasoning,
                    max_output_tokens=ws_max,
                    timeout=ws_timeout,
                )
        else:
            # Baseline: plain chat-completions on the same model (no browsing).
            def _measure(q: str) -> dict[str, Any]:
                text = openai_client.chat(
                    q, max_completion_tokens=measure_tokens, reasoning_effort=reasoning_effort
                )
                return {"text": text, "web_search_used": False, "sources": []}
    else:
        mock_client = get_engine_client(config)

        def _measure(q: str) -> dict[str, Any]:
            return {"text": mock_client.query(q), "web_search_used": False, "sources": []}

    # Competitor auto-extraction (a separate, cheap call per answer). Independent of the
    # measurement call/model/prompt; never affects scoring, prominence, or visibility.
    ce_cfg = config.get("competitor_extraction", {})
    ce_enabled = bool(ce_cfg.get("enabled", True))
    ce_model = str(ce_cfg.get("model", "gpt-4o-mini"))
    ce_max_tokens = int(ce_cfg.get("max_completion_tokens", 300))
    brand_aliases = config.get("brand_aliases") or [brand]
    extraction_client = openai_client if openai_mode == "live" else None
    if ce_enabled and extraction_client is None:
        # Extraction needs the OpenAI client even when measurement runs in mock mode.
        try:
            from src.clients.openai_client import client as extraction_client
        except Exception as exc:
            logger.warning("Competitor extraction disabled (OpenAI client unavailable): %s", exc)
            extraction_client = None
    do_extract = ce_enabled and extraction_client is not None

    def _is_empty(text: str | None) -> bool:
        return not (text or "").strip()

    results: list[GeoQueryResult] = []
    total = len(queries)
    for idx, query in enumerate(queries, 1):
        web_search_used = False
        sources: list[dict] = []
        try:
            res = _measure(query)
            answer = res.get("text", "")
            web_search_used = bool(res.get("web_search_used"))
            sources = res.get("sources") or []
            if _is_empty(answer):
                # Empty (reasoning ate the budget, or a slow web-search call returned
                # nothing) — retry once.
                res = _measure(query)
                answer = res.get("text", "")
                web_search_used = bool(res.get("web_search_used"))
                sources = res.get("sources") or []
            if _is_empty(answer):
                # Still empty: a measurement failure, NOT a genuine "brand absent".
                result = GeoQueryResult(
                    query=query, engine=engine_type, answer="",
                    error="empty completion — no answer returned after retry",
                    web_search_used=web_search_used, sources=sources,
                )
            else:
                result = GeoQueryResult(
                    query=query, engine=engine_type, answer=answer, error=None,
                    web_search_used=web_search_used, sources=sources,
                )
        except Exception as exc:
            # Error/timeout — leave it unscored with web_search_used=False; never record
            # a false zero for a query that didn't actually browse.
            result = GeoQueryResult(
                query=query, engine=engine_type, answer="", error=str(exc),
                web_search_used=False, sources=[],
            )

        # detect_brand_mentions early-returns on error, so error rows keep the default
        # (unmeasured) state and are excluded from scoring/visibility below.
        detect_brand_mentions(result, brand, competitors)

        # After measurement, populate competitors_found from the answer text itself.
        # Only for genuinely measured answers; failures leave the default empty list.
        if do_extract and not result.error and result.answer:
            result.competitors_found = extract_competitors(
                result.answer, extraction_client, ce_model, brand_aliases, ce_max_tokens
            )

        results.append(result)
        _emit({
            "phase": "geo", "index": idx, "total": total, "query": query,
            "web_search_used": result.web_search_used, "error": result.error,
        })

    report = GeoReport(brand=brand, engine=engine_type, results=results, geo_score=0.0)
    # Collapse case/punctuation variants to one display per brand BEFORE aggregating,
    # so the summary and Share of Voice count each brand once.
    normalize_competitor_names(results)
    report.competitors_summary = build_competitors_summary(results)
    report.share_of_voice = build_share_of_voice(results, brand, brand_aliases)
    report.sov_headline = sov_headline(report.share_of_voice, brand)
    score_geo(report)
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
