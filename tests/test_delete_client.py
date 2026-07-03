"""Tests for the shared, guarded client-delete action (Trends "Remove client").

Fully offline against a SEEDED temp reports dir — never touches data/reports. Runnable
under pytest OR directly:

    .venv/bin/python -m tests.test_delete_client
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.reporting import history as H


def _seed(base: Path) -> None:
    """Seed three clients with a couple of runs each + a latest_report owned by 'boba'."""
    runs = {
        "boba": ["2026-01-01T10-00-00Z", "2026-01-02T10-00-00Z"],
        "boba-boba": ["2026-01-01T11-00-00Z"],
        "nandos": ["2026-03-01T09-00-00Z", "2026-03-02T09-00-00Z", "2026-03-03T09-00-00Z"],
    }
    for slug, stamps in runs.items():
        d = base / "history" / slug
        d.mkdir(parents=True, exist_ok=True)
        for s in stamps:
            (d / f"{s}.json").write_text(json.dumps({"client": slug, "geo_report": {}}), encoding="utf-8")
    # latest_report.json belongs to 'boba' (newest boba run); + a stale pdf.
    (base / "latest_report.json").write_text(json.dumps({"client": "boba"}), encoding="utf-8")
    (base / "latest_report.pdf").write_bytes(b"%PDF-1.4 stale")


def test_delete_removes_only_target_and_soft_trashes() -> None:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        _seed(base)
        assert H.list_clients(base) == ["boba", "boba-boba", "nandos"]

        res = H.delete_client("boba-boba", reports_dir=base)  # not the latest owner
        assert res["deleted"] == "boba-boba" and res["runs_removed"] == 1 and res["soft"] is True
        # Gone from the enumerated list + off its history location…
        assert H.list_clients(base) == ["boba", "nandos"]
        assert not (base / "history" / "boba-boba").exists()
        # …recoverable in .trash, and other clients untouched.
        assert res["trashed_to"] and Path(res["trashed_to"]).is_dir()
        assert (base / "history" / "boba").is_dir() and (base / "history" / "nandos").is_dir()
        # latest belonged to 'boba' (not deleted) → left exactly as-is.
        assert json.loads((base / "latest_report.json").read_text())["client"] == "boba"
        assert (base / "latest_report.pdf").exists()


def test_delete_selected_client_repoints_latest_and_drops_stale_pdf() -> None:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        _seed(base)
        res = H.delete_client("boba", reports_dir=base)  # owns latest_report.json
        assert res["deleted"] == "boba" and res["runs_removed"] == 2
        # Repointed to the newest remaining run overall → nandos (2026-03-03).
        assert res["latest_repointed"] == "nandos"
        assert json.loads((base / "latest_report.json").read_text())["client"] == "nandos"
        # Stale pdf removed (belonged to the deleted client).
        assert not (base / "latest_report.pdf").exists()


def test_delete_last_client_clears_latest_to_empty_state() -> None:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "history" / "solo").mkdir(parents=True)
        (base / "history" / "solo" / "2026-01-01T10-00-00Z.json").write_text(
            json.dumps({"client": "solo"}), encoding="utf-8")
        (base / "latest_report.json").write_text(json.dumps({"client": "solo"}), encoding="utf-8")
        (base / "latest_report.pdf").write_bytes(b"%PDF stale")

        res = H.delete_client("solo", reports_dir=base)
        assert res["latest_repointed"] is None
        assert H.list_clients(base) == []
        # Cleared to empty state so the dashboards don't try to load a deleted report.
        assert not (base / "latest_report.json").exists()
        assert not (base / "latest_report.pdf").exists()


def test_unknown_client_is_rejected_and_deletes_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        _seed(base)
        before = H.list_clients(base)
        for bogus in ("../../etc", "does-not-exist", "..", "boba/../nandos", ""):
            try:
                H.delete_client(bogus, reports_dir=base)
                raise AssertionError(f"{bogus!r} should have been rejected")
            except ValueError:
                pass
        # Nothing changed — no dir removed, latest intact.
        assert H.list_clients(base) == before
        assert (base / "latest_report.json").exists()


def test_hard_delete_skips_trash() -> None:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        _seed(base)
        res = H.delete_client("nandos", reports_dir=base, soft=False)
        assert res["soft"] is False and res["trashed_to"] is None
        assert not (base / "history" / "nandos").exists()
        assert not (base / ".trash").exists()


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
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
