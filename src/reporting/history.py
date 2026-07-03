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
import shutil
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


def _repoint_latest_if_owned(base: Path, deleted_slug: str) -> str | None:
    """If ``latest_report.json`` belongs to the deleted client, repoint or clear it.

    Repoints to the most recent run of any REMAINING client (the history payload has the
    same shape as latest_report.json), else clears it for an empty state. The stale
    ``latest_report.pdf`` is removed either way (a future run regenerates it) so a mismatched
    PDF is never served. Returns the slug repointed to, or None (cleared / not owned).
    """
    latest = base / "latest_report.json"
    pdf = base / "latest_report.pdf"
    if not latest.exists():
        return None
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    owner = slugify(str(payload.get("client") or payload.get("brand") or ""))
    if owner != deleted_slug:
        return None  # latest belongs to a different client — leave it untouched

    # Newest remaining run across all remaining clients (by parsed run timestamp).
    best: tuple[datetime, Path, str] | None = None
    fallback: tuple[Path, str] | None = None
    for client in list_clients(base):
        files = list_reports(client, base)
        if not files:
            continue
        newest_file = files[-1]
        fallback = (newest_file, client)
        ts = parse_timestamp(newest_file)
        if ts is not None and (best is None or ts > best[0]):
            best = (ts, newest_file, client)

    chosen = (best[1], best[2]) if best else fallback
    if chosen is not None:
        latest.write_text(chosen[0].read_text(encoding="utf-8"), encoding="utf-8")
        pdf.unlink(missing_ok=True)  # stale — belonged to the deleted client
        return chosen[1]

    # Nothing left anywhere — clear to the empty state (dashboards handle this gracefully).
    latest.unlink(missing_ok=True)
    pdf.unlink(missing_ok=True)
    return None


def delete_client(client_id: str, reports_dir: Path | None = None, soft: bool = True) -> dict[str, Any]:
    """Remove ONE client's saved report history. The single shared delete both surfaces call.

    DESTRUCTIVE, so it is guarded: ``client_id`` is validated against the enumerated client
    list (never interpolated into a path), the resolved target must sit directly under
    ``<reports>/history``, and only that directory is touched — never code, config, .env, or
    other clients. ``soft=True`` (default) moves the directory to ``<reports>/.trash`` so it
    is recoverable; ``soft=False`` hard-deletes. If the client owned ``latest_report.json``
    it is repointed to the newest remaining run (or cleared).

    Returns ``{deleted, runs_removed, soft, latest_repointed, trashed_to}``.
    Raises ValueError for an unknown/invalid client (nothing is deleted).
    """
    base = reports_dir or REPORTS_DIR
    slug = slugify(client_id)
    if slug not in list_clients(base):
        raise ValueError(f"Unknown client: {client_id!r}")

    history_base = (base / "history").resolve()
    target = (history_base / slug).resolve()
    # Defense in depth: the resolved path must be a direct child of history/ (no traversal).
    if target.parent != history_base or not target.is_dir():
        raise ValueError(f"Refusing to delete outside the reports history: {client_id!r}")

    runs_removed = len(list(target.glob("*.json")))
    trashed_to: str | None = None
    if soft:
        trash = base / ".trash" / "history"
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / f"{slug}-{_timestamp()}"
        counter = 1
        while dest.exists():
            dest = trash / f"{slug}-{_timestamp()}-{counter}"
            counter += 1
        shutil.move(str(target), str(dest))
        trashed_to = str(dest)
    else:
        shutil.rmtree(target)

    latest_repointed = _repoint_latest_if_owned(base, slug)
    return {
        "deleted": slug,
        "runs_removed": runs_removed,
        "soft": soft,
        "latest_repointed": latest_repointed,
        "trashed_to": trashed_to,
    }


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
