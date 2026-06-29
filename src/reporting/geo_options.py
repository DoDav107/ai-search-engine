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

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_geo_options(path: str = "config/geo_config.yaml") -> dict[str, Any]:
    from dotenv import load_dotenv

    from src.agents.geo_agent import build_catalog
    from src.security.env_writer import allow_env_key_write

    # Reflect the SAME .env the pipeline loads (src/clients/openai_client.py calls
    # load_dotenv at import). The web server's bare process env usually lacks these keys,
    # which previously produced a false "no key configured" warning. Loading the repo .env
    # here makes key presence match what an actual audit run would see.
    load_dotenv(REPO_ROOT / ".env")

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}

    catalog = build_catalog(config)
    for provider in catalog.get("providers", {}).values():
        env_key = provider.get("env_key_name")
        # No env var (mock) needs no key; otherwise report whether it's configured.
        provider["key_present"] = bool(os.environ.get(env_key)) if env_key else True
    # Whether the opt-in "save key to server .env" feature is enabled (default off).
    catalog["allow_env_key_write"] = allow_env_key_write()
    return catalog


def main() -> None:
    print(json.dumps(load_geo_options(), ensure_ascii=False))


if __name__ == "__main__":
    main()
