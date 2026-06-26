"""Provider/model options for the dashboards' New Audit forms.

Thin wrapper over the single source of truth (``geo_agent.build_catalog`` — derived from
geo_config.yaml's ``engines:`` list) so the forms, the config, the factory, and the
results never drift. Adds ``key_present`` per provider (is the API-key env var set?) so a
form can warn before a run instead of failing silently mid-pipeline.

The ``ui_selectable`` flag is preserved (mock is ui_selectable=False); the forms filter on
it — this module never hardcodes mock's exclusion.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml


def load_geo_options(path: str = "config/geo_config.yaml") -> dict[str, Any]:
    from src.agents.geo_agent import build_catalog

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}

    catalog = build_catalog(config)
    for provider in catalog.get("providers", {}).values():
        env_key = provider.get("env_key_name")
        # No env var (mock) needs no key; otherwise report whether it's configured.
        provider["key_present"] = bool(os.environ.get(env_key)) if env_key else True
    return catalog


def main() -> None:
    print(json.dumps(load_geo_options(), ensure_ascii=False))


if __name__ == "__main__":
    main()
