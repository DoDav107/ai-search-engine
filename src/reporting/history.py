"""Report history — timestamped, client-scoped copies of each run (for trends).

Each pipeline run keeps ``data/reports/latest_report.json`` as the "most recent"
pointer AND writes an immutable copy to
``data/reports/history/<client-slug>/<YYYY-MM-DDTHH-MM-SSZ>.json`` so historical
runs are never overwritten. ``list_reports`` returns a client's history sorted by
time, ready for a future trend view.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "data" / "reports"


def slugify(name: str) -> str:
    """Filesystem-safe client slug: lowercase, non-alphanumerics → hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or "unknown"


def _timestamp(when: datetime | None = None) -> str:
    """UTC timestamp safe for filenames and lexically sortable: YYYY-MM-DDTHH-MM-SSZ."""
    dt = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H-%M-%SZ")


def client_history_dir(client: str, reports_dir: Path | None = None) -> Path:
    """Directory holding one client's historical reports."""
    return (reports_dir or REPORTS_DIR) / "history" / slugify(client)


def save_report_history(
    payload: dict[str, Any],
    client: str,
    when: datetime | None = None,
    reports_dir: Path | None = None,
) -> Path:
    """Write a timestamped, client-scoped copy of the report. Returns its path.

    Never overwrites a previous run; if two runs land in the same second a numeric
    suffix is added.
    """
    directory = client_history_dir(client, reports_dir)
    directory.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp(when)
    path = directory / f"{stamp}.json"
    counter = 1
    while path.exists():
        path = directory / f"{stamp}-{counter}.json"
        counter += 1

    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def list_reports(client: str, reports_dir: Path | None = None) -> list[Path]:
    """All historical report files for a client, sorted oldest → newest.

    The timestamped filenames sort lexically in chronological order.
    """
    directory = client_history_dir(client, reports_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def list_clients(reports_dir: Path | None = None) -> list[str]:
    """All client slugs that have at least one historical report."""
    base = (reports_dir or REPORTS_DIR) / "history"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def parse_timestamp(path: Path | str) -> datetime | None:
    """Parse the run time from a history filename (YYYY-MM-DDTHH-MM-SSZ[.json])."""
    stem = Path(path).stem
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z", stem)
    if not match:
        return None
    y, mo, d, hh, mm, ss = (int(g) for g in match.groups())
    try:
        return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
    except ValueError:
        return None


def load_reports(client: str, reports_dir: Path | None = None) -> list[tuple[datetime | None, dict]]:
    """Load every historical report for a client as (run_timestamp, payload).

    Sorted oldest → newest (by filename). Unreadable files are skipped. This is the
    single entry point a trend view uses — no API calls, no scoring.
    """
    runs: list[tuple[datetime | None, dict]] = []
    for path in list_reports(client, reports_dir):
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        runs.append((parse_timestamp(path), payload))
    return runs
