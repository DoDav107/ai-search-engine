"""Tests for the rule-based GEO quality signals and the richer per-query score.

Fully offline (no API). Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_geo_quality
"""

from __future__ import annotations

from src.agents.geo_agent import (
    analyze_quality_signals,
    detect_brand_mentions,
    geo_weights,
    per_query_geo_score,
    run_geo,
    _prominence,
)
from src.engine.models import GeoQueryResult

_BRAND = "Eloize"
_ALIASES = ["Eloize"]


def _analyze(answer: str, competitors: list[str] | None = None) -> GeoQueryResult:
    r = GeoQueryResult(query="q", engine="mock", answer=answer)
    detect_brand_mentions(r, _BRAND, [], aliases=_ALIASES)
    r.prominence_score = _prominence(r)
    if competitors is not None:
        r.competitors_found = competitors
    analyze_quality_signals(r, _BRAND, _ALIASES, [])
    return r


def test_positive_sentiment_detection() -> None:
    r = _analyze("Eloize is the best, a trusted and leading choice for SMBs.")
    assert r.sentiment_label == "positive" and r.sentiment_score > 0


def test_negative_sentiment_detection() -> None:
    r = _analyze("Eloize is a limited, less established and not well-known option.")
    assert r.sentiment_label == "negative" and r.sentiment_score < 0


def test_neutral_sentiment_detection() -> None:
    r = _analyze("Eloize is an automation tool that some teams use.")
    assert r.sentiment_label == "neutral" and r.sentiment_score == 0.0


def test_unknown_sentiment_when_absent() -> None:
    r = _analyze("Jasper and Arvow are popular tools.", competitors=["Jasper", "Arvow"])
    assert r.sentiment_label == "unknown" and r.recommendation_strength == "none"


def test_recommendation_strength_mapping() -> None:
    strong = _analyze("Best tools:\n1. Eloize\n2. Jasper", competitors=["Jasper"])
    assert strong.recommendation_strength == "strong" and strong.recommendation_score == 1.0
    moderate = _analyze("Top tools:\n1. Jasper\n2. Eloize", competitors=["Jasper"])
    assert moderate.recommendation_strength == "moderate" and moderate.brand_rank_position == 2
    weak = _analyze("Eloize is an automation tool teams sometimes use.")
    assert weak.recommendation_strength == "weak"
    none = _analyze("Jasper is great.", competitors=["Jasper"])
    assert none.recommendation_strength == "none"


def test_citation_detection() -> None:
    plain = _analyze("Eloize is good. See https://eloize.io/about for details.")
    assert plain.citation_count == 1 and plain.citations_present is True
    markdown = _analyze("Eloize is good. [docs](https://eloize.io/docs).")
    assert markdown.citation_count == 1 and markdown.citations_present is True
    none = _analyze("Eloize is good but no links here.")
    assert none.citation_count == 0 and none.citations_present is False
    # Engine-returned sources also count as citations.
    r = GeoQueryResult(query="q", engine="openai", answer="Eloize is good.",
                       sources=[{"url": "https://rtings.com/x"}, {"url": "https://b.com/y"}])
    detect_brand_mentions(r, _BRAND, [], aliases=_ALIASES)
    analyze_quality_signals(r, _BRAND, _ALIASES, [])
    assert r.citation_count == 2 and r.citations_present is True


def test_competitor_count_mirrors_found() -> None:
    r = _analyze("Eloize, Jasper and Arvow are options.", competitors=["Jasper", "Arvow"])
    assert r.competitor_count == 2
    assert r.competitor_names_mentioned == ["Jasper", "Arvow"]


def test_per_query_geo_score() -> None:
    weights = geo_weights({})
    positive = _analyze("Eloize is the best, most recommended, trusted leading choice. https://eloize.io")
    negative = _analyze("Eloize is a limited, less established, not well-known option.")
    absent = _analyze("Jasper is popular.", competitors=["Jasper"])
    p = per_query_geo_score(positive, weights)
    n = per_query_geo_score(negative, weights)
    z = per_query_geo_score(absent, weights)
    assert z == 0.0                       # visibility gate: absent brand scores 0
    assert 0.0 < n < p <= 100.0           # negative scores lower than positive
    # Errored rows are unscored.
    err = GeoQueryResult(query="q", engine="mock", answer="", error="boom")
    assert per_query_geo_score(err, weights) is None


def test_overall_geo_score_from_per_query() -> None:
    cfg = {
        "brand": _BRAND,
        "queries": [
            "How can I automate repetitive tasks in my startup?",  # mentions Eloize
            "How do I govern and control AI systems in my company?",  # no Eloize
        ],
        "competitor_extraction": {"enabled": False},
        "engine": "mock",
    }
    report = run_geo(cfg)
    assert all(r.per_query_geo_score is not None for r in report.results)
    measured = [r for r in report.results if not r.error]
    expected = round(sum(r.per_query_geo_score for r in measured) / len(measured), 1)
    assert report.engine_scores[0]["geo_score"] == expected
    assert report.geo_score == expected  # single engine ⇒ overall == engine score


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
