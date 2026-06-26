"""Tests for the PDF trends-over-time section (conditional + noise guard + locale).

Pure HTML-string assertions — no Playwright/Chromium needed. Runnable under pytest OR:

    .venv/bin/python -m tests.test_pdf_trends
"""

from __future__ import annotations

from src.reporting.pdf_report import _trend_section, render_html


def _series(*, runs: list[dict], enough: bool) -> dict:
    return {"enough_data": enough, "min_interval_hours": 24, "runs": runs}


def _run(ts: str, unified=50.0, seo=60.0, geo=40.0, vis=70.0, low=False) -> dict:
    return {"timestamp": ts, "unified": unified, "seo": seo, "geo": geo,
            "brand_visibility": vis, "low_confidence": low}


def test_omitted_when_no_history() -> None:
    assert _trend_section(None) == ""
    assert _trend_section({"enough_data": False, "runs": []}) == ""


def test_omitted_for_single_run() -> None:
    one = _series(runs=[_run("2026-06-25T08:00:00Z")], enough=False)
    assert _trend_section(one) == ""


def test_rendered_for_two_plus_runs() -> None:
    s = _series(runs=[
        _run("2026-06-23T08:00:00Z", unified=40.0),
        _run("2026-06-24T08:00:00Z", unified=55.0),  # +24h apart → confident
    ], enough=True)
    html = _trend_section(s)
    assert "Trends Over Time" in html
    assert "<svg" in html and "polyline" in html  # chart drawn
    assert "vs prev" in html and "vs earlier today" not in html  # not same-day
    assert "▲ 15.0" in html  # unified delta 55-40


def test_same_day_noise_labelling() -> None:
    s = _series(runs=[
        _run("2026-06-25T08:00:00Z", unified=97.0),
        _run("2026-06-25T11:00:00Z", unified=78.0, low=True),  # 3h later → low confidence
    ], enough=True)
    html = _trend_section(s)
    assert "vs earlier today" in html
    assert "run-to-run variance" in html  # change note warns it's not a trend
    assert "rect" in html  # noise band drawn over the same-day interval


def test_missing_metric_shows_no_prior() -> None:
    s = _series(runs=[
        _run("2026-06-23T08:00:00Z", vis=None),
        _run("2026-06-24T08:00:00Z", vis=80.0),
    ], enough=True)
    html = _trend_section(s)
    assert "no prior" in html  # brand visibility had no comparable previous value


def test_render_html_omits_trends_without_history() -> None:
    report = {"brand": "Acme", "geo_report": {"results": []}}
    assert "Trends Over Time" not in render_html(report, "now", None, trends=None)


def test_geo_table_has_region_column() -> None:
    report = {
        "brand": "Acme",
        "geo_report": {"results": [
            {"query": "best widgets", "brand_mentioned": True, "first_position": 0,
             "answer": "Acme", "locale_applied": "AU", "locale_method": "native_param"},
        ]},
    }
    html = render_html(report, "now", None, trends=None)
    assert "Region" in html  # column header
    assert ">AU<" in html  # locale surfaced in the row


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
