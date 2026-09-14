"""Configuration paths and validation for the local SSC setup.

Credentials live in the ignored ``config.yaml`` file. This module deliberately
contains no credentials; it only provides the shared loader used by the GUI
and command-line tools.
"""

from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config.yaml"
REPORTS_DIR = PROJECT_DIR / "reports"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load the local YAML configuration supplied by the operator."""
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _is_placeholder(value: str) -> bool:
    return not value or value.upper().startswith("YOUR_")


def validate_ssc_config(config: dict | None) -> tuple[str, str]:
    """Return the API key and portfolio identifier after validation.

    Blank template values (parsed by YAML as ``None``) and the README's
    ``YOUR_...`` placeholders are rejected before any API call is made.
    """
    ssc = (config or {}).get("securityscorecard")
    if not isinstance(ssc, dict):
        ssc = {}
    api_key = str(ssc.get("api_key") or "").strip()
    portfolio_id = str(ssc.get("portfolio_id") or "").strip()
    if _is_placeholder(api_key):
        raise ValueError("Set 'securityscorecard.api_key' in config.yaml.")
    if _is_placeholder(portfolio_id):
        raise ValueError("Set 'securityscorecard.portfolio_id' in config.yaml.")
    return api_key, portfolio_id
