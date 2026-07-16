from __future__ import annotations
import re

# -----------------------------------------------------------------------------
# This file contains small helper functions that are shared by different
# parts of the program, such as:
# - formatting filenames for downloaded reports,
# - cleaning up company names and domains,
# - standardizing SecurityScorecard data,
# - validating the application configuration.

# Keeping these common functions in one place avoids repeating the same
# code in multiple files and makes future maintenance easier.
# -----------------------------------------------------------------------------

# Regex patterns used for filename sanitization.
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_MULTIPLE_SPACES = re.compile(r"\s+")

from pathlib import Path
from typing import Iterable

# Normalize grade by capitaling string.
def normalize_grade(value: object) -> str:
    return str(value or "").strip().upper()

# Normalize a domain by removing whitespace and converting to lowercase.
def normalize_domain(value: str) -> str:
    return value.strip().lower()

# Remove characters that are invalid in filenames and clean up spacing.
# Returns "Unknown" if the resulting filename is empty.
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

# Generate a standardized filename for downloaded reports.
def make_filename(
    grade: str,
    company_name: str,
    month: str,
    report_type: str,
) -> str:

    # Convert API report type for easier reading.
    report_name = {
        "detailed_report": "Detailed Report",
        "issue_report": "Issue Report",
    }.get(report_type, report_type)

    # Remove invalid filename characters from the company name.
    safe_name = sanitize_filename(company_name)

    return (
        f"[{grade}] - {safe_name} - "
        f"{report_name} - {month}.pdf"
    )

# Validate the SecurityScorecard configuration before making API calls.
# Returns the API key and portfolio ID if both are valid.
def validate_ssc_config(config: dict) -> tuple[str, str]:
    ssc = config.get("securityscorecard") or {}
    api_key = str(ssc.get("api_key") or "").strip()
    portfolio_id = str(ssc.get("portfolio_id") or "").strip()

    if not api_key or api_key.upper().startswith("YOUR_"):
        raise ValueError("config.yaml: set securityscorecard.api_key")
    if not portfolio_id:
        raise ValueError("config.yaml: set securityscorecard.portfolio_id")

    return api_key, portfolio_id