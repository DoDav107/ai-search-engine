"""CLI wrapper so the Next.js dashboard can call the shared client-delete action.

The Next.js route spawns this (mirroring geo_options / trends); the Streamlit dashboard
calls ``history.delete_client`` directly. Both go through the ONE shared, guarded action —
no duplicated delete logic per surface.

    python -m src.reporting.delete_client --client boba-boba
    python -m src.reporting.delete_client --client boba --hard   # skip .trash
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.reporting.history import delete_client


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, help="Client slug to remove.")
    parser.add_argument("--hard", action="store_true", help="Hard delete instead of .trash.")
    parser.add_argument("--reports-dir", default=None, help="Override reports dir (tests only).")
    args = parser.parse_args()

    try:
        result = delete_client(
            args.client,
            reports_dir=Path(args.reports_dir) if args.reports_dir else None,
            soft=not args.hard,
        )
    except ValueError as exc:  # unknown/invalid client — nothing was deleted
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 — surface a concise failure to Next.js
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"ok": True, **result}))


if __name__ == "__main__":
    main()
