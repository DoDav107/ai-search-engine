"""GEO research agent for measuring brand visibility in AI engine answers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from ..engine.models import GeoQueryResult, GeoReport


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


def score_geo(report: GeoReport) -> float:
    """Compute a GEO score from brand mention prominence across queries."""
    query_values: list[float] = []
    for result in report.results:
        if result.error or not result.brand_mentioned or not result.answer:
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


def run_geo(config: dict[str, Any]) -> GeoReport:
    """Run GEO queries and collect brand visibility data."""
    brand = config.get("brand", "Unknown Brand")
    engine_type = config.get("engine", "mock")
    queries = config.get("queries", [])
    competitors = config.get("competitors", [])

    openai_mode = config.get("openai", {}).get("mode", "mock")
    if openai_mode == "live":
        from src.clients.openai_client import client as openai_client
        _get_answer = lambda q: openai_client.chat(q)
    else:
        mock_client = get_engine_client(config)
        _get_answer = lambda q: mock_client.query(q)

    results: list[GeoQueryResult] = []
    for query in queries:
        try:
            answer = _get_answer(query)
            result = GeoQueryResult(query=query, engine=engine_type, answer=answer, error=None)
        except Exception as exc:
            result = GeoQueryResult(query=query, engine=engine_type, answer="", error=str(exc))

        detect_brand_mentions(result, brand, competitors)
        results.append(result)

    report = GeoReport(brand=brand, engine=engine_type, results=results, geo_score=0.0)
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

    visibility_score = round((mentioned_count / len(report.results)) * 100, 1) if report.results else 0.0
    print(f"Brand visibility: {visibility_score}% of queries")
    print(f"Overall GEO score: {report.geo_score}%")


if __name__ == "__main__":
    main()
