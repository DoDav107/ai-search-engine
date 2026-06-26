"""Trends-over-time series built from saved report history (no API, no rescoring).

Single source of truth for the "Trends over time" view on BOTH dashboards: it reuses
``src.reporting.history`` (the same timestamped, client-scoped report copies the Streamlit
view reads) and the same metric formulas, then exposes a JSON time series the Next.js page
fetches via ``/api/trends`` and a CLI prints.

Noise guard: live web-search GEO scores jitter run-to-run, so two runs the SAME DAY look
like a confident trend when they're really variance. ``low_confidence`` flags each run
whose gap to the PREVIOUS run is below ``min_interval_hours`` (default 24h, configurable
via the ``TREND_MIN_INTERVAL_HOURS`` env var or the CLI/route). Both surfaces shade those
intervals as a low-confidence band and relabel same-day change cards.

CLI (mirrors geo_options):
    python -m src.reporting.trends                  -> {"clients": [...]}
    python -m src.reporting.trends --client adidas  -> full series for that client
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any

from src.reporting import history as _hist

DEFAULT_MIN_INTERVAL_HOURS = 24.0


def min_interval_hours(override: float | None = None) -> float:
    """Configurable noise-guard threshold (hours). override > env > default."""
    if override is not None:
        return float(override)
    raw = os.environ.get("TREND_MIN_INTERVAL_HOURS")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_MIN_INTERVAL_HOURS


def low_confidence_flags(timestamps: list[datetime], hours: float) -> list[bool]:
    """Per-run flag: True when the gap to the PREVIOUS run is < ``hours`` (same-day noise).

    The first run is always False (no prior to compare). Shared by both surfaces so the
    guard is identical everywhere.
    """
    flags = [False] * len(timestamps)
    threshold = hours * 3600.0
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        flags[i] = gap < threshold
    return flags


# ----- metric extractors (mirror the Streamlit trends view; pure, crash-safe) -----
def _num(payload: dict, key: str) -> float | None:
    v = payload.get(key)
    return round(float(v), 1) if isinstance(v, (int, float)) else None


def brand_visibility(payload: dict) -> float | None:
    results = (payload.get("geo_report") or {}).get("results") or []
    measured = [r for r in results if not r.get("error")]
    if not measured:
        return None
    mentioned = sum(1 for r in measured if r.get("brand_mentioned"))
    return round(mentioned / len(measured) * 100, 1)


def _subject_sov(payload: dict) -> float | None:
    for s in (payload.get("geo_report") or {}).get("share_of_voice") or []:
        if s.get("is_subject"):
            return round((s.get("share") or 0.0) * 100, 1)
    return None


def _sov_map(payload: dict) -> dict[str, float]:
    return {
        (s.get("brand") or "").strip(): round((s.get("share") or 0.0) * 100, 1)
        for s in (payload.get("geo_report") or {}).get("share_of_voice") or []
    }


def _query_prominence(payload: dict, query: str) -> tuple[bool, float | None]:
    for r in (payload.get("geo_report") or {}).get("results") or []:
        if r.get("query") == query:
            if r.get("error"):
                return (False, None)
            mentioned = bool(r.get("brand_mentioned"))
            prom = None
            if mentioned and r.get("first_position") is not None:
                length = len(r.get("answer") or "")
                if length > 0:
                    prom = round(max(0.0, min((1.0 - r["first_position"] / length) * 100, 100.0)), 1)
            return (mentioned, prom)
    return (False, None)


def series_for_client(client: str, override_hours: float | None = None) -> dict[str, Any]:
    """Full trends payload for one client: runs + scores + SoV + per-query + noise flags.

    ``runs`` is oldest→newest. Single-run (or empty) histories return their snapshot with
    ``enough_data: False`` so the UI shows a "need ≥2 runs" message instead of a chart.
    """
    threshold = min_interval_hours(override_hours)
    loaded = [(ts, p) for ts, p in _hist.load_reports(client) if ts is not None]
    timestamps = [ts for ts, _ in loaded]
    flags = low_confidence_flags(timestamps, threshold)

    runs = [
        {
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "unified": _num(p, "unified_score"),
            "seo": _num(p, "seo_score"),
            "geo": _num(p, "geo_score"),
            "brand_visibility": brand_visibility(p),
            "subject_sov": _subject_sov(p),
            "low_confidence": flags[i],  # gap to previous run < threshold
        }
        for i, (ts, p) in enumerate(loaded)
    ]

    # SoV series: subject + top-3 competitors ranked by the latest run (parity w/ Streamlit).
    subject_name = client
    sov: list[dict[str, Any]] = []
    if loaded:
        last_sov = (loaded[-1][1].get("geo_report") or {}).get("share_of_voice") or []
        subject_name = next((s.get("brand") for s in last_sov if s.get("is_subject")), client)
        comps = [s.get("brand") for s in sorted(last_sov, key=lambda s: -(s.get("share") or 0.0))
                 if not s.get("is_subject")][:3]
        maps = [_sov_map(p) for _, p in loaded]
        if any(_subject_sov(p) is not None for _, p in loaded):
            sov.append({"name": subject_name, "is_subject": True,
                        "values": [_subject_sov(p) for _, p in loaded]})
            for comp in comps:
                sov.append({"name": comp, "is_subject": False,
                            "values": [m.get(comp) for m in maps]})

    # Per-query prominence/mention across runs.
    queries: list[str] = []
    for _, p in loaded:
        for r in (p.get("geo_report") or {}).get("results") or []:
            q = r.get("query")
            if q and q not in queries:
                queries.append(q)
    query_series = {
        q: [
            {"prominence": prom, "mentioned": mentioned}
            for (mentioned, prom) in (_query_prominence(p, q) for _, p in loaded)
        ]
        for q in queries
    }

    return {
        "client": client,
        "subject_name": subject_name,
        "min_interval_hours": threshold,
        "enough_data": len(runs) >= 2,
        "runs": runs,
        "sov": sov,
        "queries": queries,
        "query_series": query_series,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default=None, help="Client slug; omit to list clients.")
    parser.add_argument("--min-interval-hours", type=float, default=None)
    args = parser.parse_args()

    if not args.client:
        print(json.dumps({"clients": _hist.list_clients(), "min_interval_hours": min_interval_hours(args.min_interval_hours)}))
        return
    print(json.dumps(series_for_client(args.client, args.min_interval_hours), ensure_ascii=False))


if __name__ == "__main__":
    main()
