from __future__ import annotations
import re

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_MULTIPLE_SPACES = re.compile(r"\s+")


from pathlib import Path
from typing import Iterable

def normalize_grade(value: object) -> str:
    return str(value or "").strip().upper()

def normalize_domain(value: str) -> str:
    return value.strip().lower()

def sanitize_filename(name: str, replacement: str = "_") -> str:
    if not name:
        return "Unknown"

    name = str(name).strip()
    name = _INVALID_FILENAME_CHARS.sub(replacement, name)
    name = _MULTIPLE_SPACES.sub(" ", name)
    name = name.rstrip(" .")

    escaped = re.escape(replacement)
    name = re.sub(f"{escaped}+", replacement, name)

    return name or "Unknown"

def make_filename(
    grade: str,
    company_name: str,
    month: str,
    report_type: str,
) -> str:

    report_name = {
        "detailed_report": "Detailed Report",
        "issue_report": "Issue Report",
    }.get(report_type, report_type)

    safe_name = sanitize_filename(company_name)

    return (
        f"[{grade}] - {safe_name} - "
        f"{report_name} - {month}.pdf"
    )

def validate_ssc_config(config: dict) -> tuple[str, str]:
    ssc = config.get("securityscorecard") or {}
    api_key = str(ssc.get("api_key") or "").strip()
    portfolio_id = str(ssc.get("portfolio_id") or "").strip()

    if not api_key or api_key.upper().startswith("YOUR_"):
        raise ValueError("config.yaml: set securityscorecard.api_key")
    if not portfolio_id:
        raise ValueError("config.yaml: set securityscorecard.portfolio_id")

    return api_key, portfolio_id