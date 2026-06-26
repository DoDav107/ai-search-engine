"""Tests for per-engine GEO quality aggregates (denominators, SoV, ranked competitors).

Fully offline (no API). Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_geo_quality_aggregates
"""

from __future__ import annotations

from src.agents.geo_agent import (
    build_engine_quality,
    neutral_accuracy_value,
    sentiment_words,
    _norm_key,
)
from src.engine.models import GeoQueryResult

_BRAND = "Eloize"
_ALIASES = ["Eloize"]
_WORDS = sentiment_words({})


def _row(answer: str, *, mentioned: bool, competitors=None, cites=False,
         sentiment="unknown", sent_score=0.0, rec="none", rec_score=0.0,
         rank=None, error=None) -> GeoQueryResult:
    r = GeoQueryResult(query="q", engine="mock", answer=answer, error=error)
    r.brand_mentioned = mentioned
    r.competitors_found = competitors or []
    r.competitor_count = len(r.competitors_found)
    r.citations_present = cites
    r.sentiment_label = sentiment
    r.sentiment_score = sent_score
    r.recommendation_strength = rec
    r.recommendation_score = rec_score
    r.brand_rank_position = rank
    return r


def test_brand_metrics_na_at_zero_visibility() -> None:
    # Brand never mentioned → sentiment / recommendation / rank must be N/A (None),
    # NEVER a misleading number. Citations/competitors still computed over all answers.
    rows = [
        _row("HOKA is the best choice.", mentioned=False, competitors=["HOKA"], cites=True),
        _row("Brooks and Asics are popular.", mentioned=False, competitors=["Brooks", "Asics"]),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    assert q["brand_mentions"] == 0
    assert q["sentiment"]["avg"] is None
    assert q["recommendation"]["avg"] is None
    assert q["avg_brand_rank"] is None
    # Across-all-answers metrics still meaningful.
    assert q["answers_total"] == 2
    assert q["citation_coverage"] == 0.5  # 1 of 2 answers had a citation
    assert q["competitor_total"] == 3


def test_brand_metrics_only_over_mentioned_answers() -> None:
    # Denominator for sentiment is the 2 brand-mention answers, not all 3.
    rows = [
        _row("Eloize is the best.", mentioned=True, sentiment="positive", sent_score=1.0,
             rec="strong", rec_score=1.0, rank=1, cites=True),
        _row("Eloize is limited.", mentioned=True, sentiment="negative", sent_score=-1.0,
             rec="weak", rec_score=0.3, rank=3),
        _row("Brooks is great.", mentioned=False, competitors=["Brooks"]),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    assert q["brand_mentions"] == 2
    assert q["sentiment"]["avg"] == 0.0  # (1.0 + -1.0) / 2
    assert q["sentiment"]["positive"] == 1 and q["sentiment"]["negative"] == 1
    assert q["avg_brand_rank"] == 2.0  # (1 + 3) / 2, only mentioned rows
    assert q["citation_coverage"] == round(1 / 3, 4)  # 1 of ALL 3 answers


def test_share_of_voice_math() -> None:
    rows = [
        _row("Eloize.", mentioned=True),
        _row("Eloize.", mentioned=True),
        _row("Brooks.", mentioned=False),
        _row("Asics.", mentioned=False),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    assert q["sov"] == 0.5  # 2 brand-mention answers / 4 total


def test_name_normalisation_collapses_variants() -> None:
    # HOKA / Hoka / hoka. must collapse to ONE competitor counted once per answer.
    assert _norm_key("HOKA") == _norm_key("Hoka") == _norm_key("hoka.")
    rows = [
        _row("a", mentioned=False, competitors=["HOKA", "Brooks"]),
        _row("b", mentioned=False, competitors=["Hoka", "Asics"]),
        _row("c", mentioned=False, competitors=["hoka."]),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    top = {c["name"]: c["count"] for c in q["top_competitors"]}
    # The three Hoka variants collapse to a single entity mentioned in 3 answers.
    assert max(top.values()) == 3
    hoka = next(c for c in q["top_competitors"] if _norm_key(c["name"]) == _norm_key("HOKA"))
    assert hoka["count"] == 3
    # competitor_total counts each answer's distinct competitors.
    assert q["competitor_total"] == 5  # 2 + 2 + 1


def test_ranked_competitors_ordered_by_count() -> None:
    rows = [
        _row("a", mentioned=False, competitors=["Brooks", "Asics", "HOKA"]),
        _row("b", mentioned=False, competitors=["Brooks", "HOKA"]),
        _row("c", mentioned=False, competitors=["Brooks"]),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    names = [c["name"] for c in q["top_competitors"]]
    counts = [c["count"] for c in q["top_competitors"]]
    assert names[0] == "Brooks" and counts[0] == 3
    assert counts == sorted(counts, reverse=True)  # descending


def test_zero_visibility_leaders_pivot() -> None:
    # Brand absent → competitor_leaders surfaces who won and how strongly.
    rows = [
        _row("Top picks:\n1. HOKA is the best, most recommended choice.",
             mentioned=False, competitors=["HOKA"]),
        _row("HOKA is a leading, trusted brand.", mentioned=False, competitors=["HOKA"]),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    assert q["brand_mentions"] == 0
    leaders = q["competitor_leaders"]
    assert leaders, "should surface leaders when brand absent"
    hoka = leaders[0]
    assert hoka["name"] == "HOKA" and hoka["mentions"] == 2
    assert hoka["sentiment_label"] == "positive"
    assert hoka["recommendation_strength"] == "strong"
    assert hoka["rank"] == 1


def test_errored_rows_excluded_from_denominators() -> None:
    rows = [
        _row("Eloize is good.", mentioned=True, sentiment="positive", sent_score=0.5),
        _row("", mentioned=False, error="timeout"),
    ]
    q = build_engine_quality(rows, _BRAND, _ALIASES, _WORDS)
    assert q["answers_total"] == 1  # errored row excluded
    assert q["sov"] == 1.0


def test_config_editable_sentiment_words() -> None:
    cfg = {"scoring": {"sentiment": {"positive": ["wonderful"], "negative": ["dreadful"]}}}
    w = sentiment_words(cfg)
    assert w["pos_words"] == ("wonderful",)
    assert w["neg_words"] == ("dreadful",)
    # Omitted list falls back to defaults (recommend not overridden here).
    assert len(w["rec_words"]) > 1


def test_neutral_accuracy_value_with_legacy_fallback() -> None:
    assert neutral_accuracy_value({}) == 0.5
    assert neutral_accuracy_value({"scoring": {"neutral_accuracy_value": 0.7}}) == 0.7
    # Legacy key still honoured when the new one is absent.
    assert neutral_accuracy_value({"scoring": {"accuracy_unknown_score": 0.3}}) == 0.3


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
