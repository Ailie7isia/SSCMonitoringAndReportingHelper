from __future__ import annotations

# -----------------------------------------------------------------------------
# This file retrieves company scores from the SecurityScorecard portfolio,
# displays a summary, and exports the results to a JSON file.
# -----------------------------------------------------------------------------

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import environ
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from models import Company

DEFAULT_SCORE_HISTORY_PATH = (
    r"C:\Users\ailie\.cursor\projects\SSCMonitoringAndReportingHelper\SSC Helper Log.xlsx"
)
SCORE_HISTORY_PATH = Path(environ.get("SSC_SCORE_HISTORY_PATH", DEFAULT_SCORE_HISTORY_PATH))
HISTORY_HEADERS = ["Retrieved (UTC)", "Domain", "Company", "Score", "Grade"]
GRADE_FILLS = {
    "A": "35C98A",
    "B": "F1BE4D",
    "C": "F48F4A",
    "D": "EE5D69",
    "F": "C93546",
}


@dataclass(frozen=True, slots=True)
class ScoreTrend:
    """Current score movement compared with the closest prior observations."""

    month_over_month: float | None
    year_over_year: float | None


def score_trends_for_companies(
    companies: list[Company],
    history_file: Path = SCORE_HISTORY_PATH,
) -> dict[str, ScoreTrend]:
    """Return 30-day and 365-day score changes for the active portfolio.

    The history workbook is read once, which keeps the trends view responsive
    even when the portfolio contains many domains.
    """
    current_scores = {
        company.domain.lower(): float(company.score)
        for company in companies
        if company.score is not None
    }
    if not current_scores or not history_file.exists():
        return {domain: ScoreTrend(None, None) for domain in current_scores}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoffs = {"month": now - timedelta(days=30), "year": now - timedelta(days=365)}
    baselines: dict[str, dict[str, tuple[datetime, float] | None]] = {
        domain: {period: None for period in cutoffs}
        for domain in current_scores
    }
    try:
        workbook = load_workbook(history_file, read_only=True, data_only=True)
        worksheet = workbook.active
        for timestamp, logged_domain, _name, score, _grade in worksheet.iter_rows(
            min_row=1,
            max_col=5,
            values_only=True,
        ):
            domain = str(logged_domain).lower()
            if domain not in baselines or not isinstance(timestamp, datetime):
                continue
            timestamp = timestamp.replace(tzinfo=None)
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            for period, cutoff in cutoffs.items():
                baseline = baselines[domain][period]
                if timestamp <= cutoff and (baseline is None or timestamp > baseline[0]):
                    baselines[domain][period] = (timestamp, numeric_score)
        workbook.close()
    except (OSError, ValueError):
        return {domain: ScoreTrend(None, None) for domain in current_scores}

    return {
        domain: ScoreTrend(
            month_over_month=(
                current_scores[domain] - baselines[domain]["month"][1]
                if baselines[domain]["month"] is not None
                else None
            ),
            year_over_year=(
                current_scores[domain] - baselines[domain]["year"][1]
                if baselines[domain]["year"] is not None
                else None
            ),
        )
        for domain in current_scores
    }


def score_change_over_past_month(
    domain: str,
    current_score: int | float | None,
    history_file: Path = SCORE_HISTORY_PATH,
) -> float | None:
    """Compare ``current_score`` with the latest observation at least 30 days old."""
    if current_score is None or not history_file.exists():
        return None
    try:
        workbook = load_workbook(history_file, read_only=True, data_only=True)
        worksheet = workbook.active
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        baseline: tuple[datetime, float] | None = None
        for timestamp, logged_domain, _name, score, _grade in worksheet.iter_rows(
            min_row=1,
            max_col=5,
            values_only=True,
        ):
            if not isinstance(timestamp, datetime) or str(logged_domain).lower() != domain.lower():
                continue
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            if timestamp <= cutoff and (baseline is None or timestamp > baseline[0]):
                baseline = (timestamp, numeric_score)
        workbook.close()
    except (OSError, ValueError):
        return None
    if baseline is None:
        return None
    return float(current_score) - baseline[1]

# Display the score for each company in the portfolio.
def display_scores(companies: list[Company]) -> None:
    print("\n========== PORTFOLIO SCORES ==========\n")

    for company in companies:
        print(
            f"[{company.score if company.score is not None else '-'}] "
            f"{company.domain}"
        )

def append_score_history(
    companies: list[Company],
    output_file: Path = SCORE_HISTORY_PATH,
) -> int:
    """Append one timestamped record per company without replacing history."""
    if output_file.exists():
        workbook = load_workbook(output_file)
        worksheet = workbook.active
    else:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        worksheet = workbook.active

    if worksheet["A1"].value is None:
        worksheet.merge_cells("A1:E1")
        worksheet["A1"] = "SSC Monitoring Helper — Score History"
        worksheet["A1"].font = Font(bold=True, size=16, color="FFFFFF")
        worksheet["A1"].fill = PatternFill("solid", fgColor="14212D")
        for column, header in enumerate(HISTORY_HEADERS, start=1):
            cell = worksheet.cell(row=2, column=column, value=header)
            cell.font = Font(bold=True, color="10202A")
            cell.fill = PatternFill("solid", fgColor="2FBF8F")
        worksheet.freeze_panes = "A3"

    retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for company in sorted(companies, key=lambda item: item.domain.lower()):
        grade = (company.grade or "Unknown").upper()
        worksheet.append([retrieved_at, company.domain, company.name, company.score, grade])
        row = worksheet.max_row
        worksheet.cell(row=row, column=1).number_format = "yyyy-mm-dd hh:mm:ss"
        worksheet.cell(row=row, column=4).number_format = "0"
        worksheet.cell(row=row, column=5).font = Font(bold=True)
        if grade in GRADE_FILLS:
            worksheet.cell(row=row, column=5).fill = PatternFill("solid", fgColor=GRADE_FILLS[grade])

    workbook.save(output_file)
    return len(companies)

# Count the number of companies for each score/grade.
def grade_statistics(
    companies: list[Company],
) -> dict[str, int]:

    counts = Counter(
        company.grade or "Unknown"
        for company in companies
    )

    return dict(counts)

# Print a summary of the portfolio score distribution.
def print_statistics(companies: list[Company]) -> None:
    stats = grade_statistics(companies)

    print("========== GRADE SUMMARY ==========\n")

    total = sum(stats.values())

    for grade in ["A", "B", "C", "D", "F", "Unknown"]:
        if grade in stats:
            print(f"{grade:>7}: {stats[grade]}")

    print(f"\nTotal : {total}\n")
