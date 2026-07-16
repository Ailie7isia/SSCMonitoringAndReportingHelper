from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_PATH = Path("config.yaml")
REPORTS_DIR = Path("reports")


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_ssc_config(config: dict) -> tuple[str, str]:
    ssc = config.get("securityscorecard", {})

    api_key = str(ssc.get("api_key", "")).strip()
    portfolio_id = str(ssc.get("portfolio_id", "")).strip()

    if not api_key:
        raise ValueError(
            "Missing 'securityscorecard.api_key' in config.yaml."
        )

    if not portfolio_id:
        raise ValueError(
            "Missing 'securityscorecard.portfolio_id' in config.yaml."
        )

    return api_key, portfolio_id