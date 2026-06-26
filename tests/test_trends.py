"""Tests for the trends-over-time series + noise guard (src.reporting.trends).

Fully offline. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_trends
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from src.reporting.trends import (
    DEFAULT_MIN_INTERVAL_HOURS,
    brand_visibility,
    low_confidence_flags,
    min_interval_hours,
    _query_prominence,
)


def _t(h: float) -> datetime:
    return datetime(2026, 6, 25, tzinfo=timezone.utc) + timedelta(hours=h)


def test_low_confidence_flags_same_day_vs_apart() -> None:
    # Runs at 0h, +2h (same-day noise), +30h (a real day later), +31h (noise again).
    ts = [_t(0), _t(2), _t(30), _t(31)]
    flags = low_confidence_flags(ts, hours=24)
    assert flags == [False, True, False, True]


def test_low_confidence_threshold_is_configurable() -> None:
    ts = [_t(0), _t(2), _t(30)]
    # A 1h threshold makes the 2h gap "confident"; a 48h threshold makes the 30h gap noise.
    assert low_confidence_flags(ts, hours=1) == [False, False, False]
    assert low_confidence_flags(ts, hours=48) == [False, True, True]


def test_min_interval_hours_precedence(monkeypatch=None) -> None:
    assert min_interval_hours() == DEFAULT_MIN_INTERVAL_HOURS
    assert min_interval_hours(12) == 12.0  # explicit override wins
    os.environ["TREND_MIN_INTERVAL_HOURS"] = "6"
    try:
        assert min_interval_hours() == 6.0          # env honoured
        assert min_interval_hours(3) == 3.0         # override still wins over env
    finally:
        os.environ.pop("TREND_MIN_INTERVAL_HOURS", None)


def test_empty_flags() -> None:
    assert low_confidence_flags([], hours=24) == []
    assert low_confidence_flags([_t(0)], hours=24) == [False]


def test_brand_visibility_excludes_errors() -> None:
    payload = {"geo_report": {"results": [
        {"brand_mentioned": True},
        {"brand_mentioned": False},
        {"error": "timeout"},  # excluded from the denominator
    ]}}
    assert brand_visibility(payload) == 50.0  # 1 of 2 measured
    assert brand_visibility({"geo_report": {"results": []}}) is None


def test_query_prominence_absent_and_error() -> None:
    payload = {"geo_report": {"results": [
        {"query": "q1", "brand_mentioned": True, "first_position": 0, "answer": "abcd"},
        {"query": "q2", "error": "boom"},
        {"query": "q3", "brand_mentioned": False},
    ]}}
    mentioned, prom = _query_prominence(payload, "q1")
    assert mentioned is True and prom == 100.0  # first_position 0 → top of answer
    assert _query_prominence(payload, "q2") == (False, None)
    assert _query_prominence(payload, "q3") == (False, None)
    assert _query_prominence(payload, "missing") == (False, None)


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
