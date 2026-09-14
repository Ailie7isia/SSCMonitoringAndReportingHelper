from __future__ import annotations
import math
import re

# -----------------------------------------------------------------------------
# This file contains small helper functions that are shared by different
# parts of the program, such as:
# - formatting filenames for downloaded reports,
# - cleaning up company names and domains,
# - standardizing SecurityScorecard data.

# Keeping these common functions in one place avoids repeating the same
# code in multiple files and makes future maintenance easier.
# -----------------------------------------------------------------------------

# Regex patterns used for filename sanitization.
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_MULTIPLE_SPACES = re.compile(r"\s+")
# Zero-width characters survive str.strip() and often arrive via copy-paste.
_INVISIBLE_CHARS = re.compile("[\u200b-\u200d\u2060\ufeff]")

# Normalize grade by capitaling string.
def normalize_grade(value: object) -> str:
    return str(value or "").strip().upper()

# Normalize a domain by removing invisible characters and whitespace and
# converting to lowercase.
def normalize_domain(value: str) -> str:
    return _INVISIBLE_CHARS.sub("", value).strip().lower()

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
    *,
    extension: str = ".pdf",
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
        f"{report_name} - {month}{extension}"
    )

# Format a duration as m:ss, or h:mm:ss for an hour or longer.
# Rounds up so a countdown never shows 0:00 while time remains.
def format_duration(seconds: float) -> str:
    total = max(0, math.ceil(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
