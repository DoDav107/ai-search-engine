"""Tests for word-boundary brand-mention detection (precision fix).

The old matcher squashed separators and did a substring find, so a brand name that is a
substring of/across other words ("richaffic", "chafficient", "rich affic") wrongly matched.
Detection now uses word-boundary token matching. Fully offline. Runnable under pytest OR:

    .venv/bin/python -m tests.test_brand_mention_precision
"""

from __future__ import annotations

from src.agents.geo_agent import detect_brand_mentions
from src.engine.models import GeoQueryResult


def _detect(brand: str, answer: str, aliases: list[str] | None = None):
    r = GeoQueryResult(query="q", engine="mock", answer=answer)
    detect_brand_mentions(r, brand, [], aliases=aliases or [brand])
    return r


def test_true_matches_all_count() -> None:
    for text in ("Chaffic", "chaffic", "CHAFFIC", "Chaffic's", "Chaffic, the tool",
                 "Chaffic.", "Use Cháffic here"):
        assert _detect("Chaffic", text).brand_mentioned, text


def test_false_matches_rejected() -> None:
    # The reported false positives — brand name inside/across other words.
    for text in ("richaffic tools", "chafficient product", "rich affic squashed",
                 "a chaffication", "Chaffle instead"):
        r = _detect("Chaffic", text)
        assert not r.brand_mentioned and r.mention_count == 0, text


def test_count_and_first_position_preserved() -> None:
    r = _detect("Chaffic", "Use Chaffic and Chaffic again")
    assert r.mention_count == 2
    assert r.first_position == 4  # start of the first "Chaffic"


def test_multiword_brand_whitespace_tolerant_but_boundary_safe() -> None:
    # Extra whitespace / squashed / hyphen forms of a real multi-word brand match…
    for text in ("Chaffic Tea rocks", "chaffic-tea", "ChafficTea"):
        assert _detect("Chaffic Tea", text).brand_mentioned, text
    # …but a squashed run inside another word, or split across unrelated words, does not.
    for text in ("richaffictea nope", "chaffic and green tea"):
        assert not _detect("Chaffic Tea", text).brand_mentioned, text


def test_configured_brand_and_alias_regression() -> None:
    assert _detect("Nike", "Nike is #1", ["Nike", "Air Jordan"]).brand_mentioned
    assert _detect("Nike", "Air Jordan sneakers", ["Nike", "Air Jordan"]).brand_mentioned
    assert _detect("Nike", "airjordan combo", ["Nike", "Air Jordan"]).brand_mentioned
    # 'nike' inside 'unlike' must NOT match.
    assert not _detect("Nike", "unlike other tools", ["Nike"]).brand_mentioned


def test_deterministic() -> None:
    a = _detect("Chaffic", "Chaffic then chaffic")
    b = _detect("Chaffic", "Chaffic then chaffic")
    assert (a.brand_mentioned, a.mention_count, a.first_position) == \
           (b.brand_mentioned, b.mention_count, b.first_position)


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failures += 1; print(f"FAIL  {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1; print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
