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
HISTORY_HEADERS = ["Retrieved (UTC)", "Domain", "Company", "Score", "Grade", "Cycle"]
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


@dataclass(frozen=True, slots=True)
class HistoricalScoreTrend:
    """A workbook domain's calendar-month scores and movement."""

    this_month_score: float | None
    last_month_score: float | None
    month_over_month: float | None
    year_over_year: float | None


def score_trends_from_history(
    history_file: Path = SCORE_HISTORY_PATH,
) -> dict[str, HistoricalScoreTrend]:
    """Return trends for every domain recorded in the score-history workbook.

    Unlike :func:`score_trends_for_companies`, this does not require a domain
    to still be in the live portfolio. Scores are based on the newest saved
    entry in each calendar month. A missing current-month entry remains empty.
    """
    if not history_file.exists():
        return {}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start
    last_month_start = (last_month_end - timedelta(days=1)).replace(day=1)
    last_year_month_start = this_month_start.replace(year=this_month_start.year - 1)
    last_year_month_end = (last_year_month_start + timedelta(days=32)).replace(day=1)
    observations: dict[str, list[tuple[datetime, float]]] = {}
    try:
        workbook = load_workbook(history_file, read_only=True, data_only=True)
        worksheet = workbook.active
        for timestamp, logged_domain, _name, score, _grade in worksheet.iter_rows(
            min_row=3, max_col=5, values_only=True
        ):
            if not isinstance(timestamp, datetime) or not logged_domain:
                continue
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            domain = str(logged_domain).strip().lower()
            if domain:
                observations.setdefault(domain, []).append((timestamp.replace(tzinfo=None), numeric_score))
        workbook.close()
    except (OSError, ValueError):
        return {}

    trends: dict[str, HistoricalScoreTrend] = {}
    for domain, values in observations.items():
        def latest_in_period(start: datetime, end: datetime) -> float | None:
            entry = max(
                (item for item in values if start <= item[0] < end),
                default=None,
                key=lambda item: item[0],
            )
            return entry[1] if entry else None

        this_month_score = latest_in_period(this_month_start, now + timedelta(days=1))
        last_month_score = latest_in_period(last_month_start, last_month_end)
        last_year_score = latest_in_period(last_year_month_start, last_year_month_end)
        trends[domain] = HistoricalScoreTrend(
            this_month_score=this_month_score,
            last_month_score=last_month_score,
            month_over_month=(
                this_month_score - last_month_score
                if this_month_score is not None and last_month_score is not None
                else None
            ),
            year_over_year=(
                this_month_score - last_year_score
                if this_month_score is not None and last_year_score is not None
                else None
            ),
        )
    return trends


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
    cycle: int | str,
    output_file: Path = SCORE_HISTORY_PATH,
) -> int:
    """Append one timestamped score record per company for a source group."""
    if not companies:
        raise ValueError(
            f"{cycle} has no live score records to add; the workbook was not changed."
        )
    if output_file.exists():
        workbook = load_workbook(output_file)
        worksheet = workbook.active
    else:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        worksheet = workbook.active

    if worksheet["A1"].value is None:
        worksheet.merge_cells("A1:F1")
        worksheet["A1"] = "SSC Monitoring Helper — Score History"
        worksheet["A1"].font = Font(bold=True, size=16, color="FFFFFF")
        worksheet["A1"].fill = PatternFill("solid", fgColor="14212D")
        for column, header in enumerate(HISTORY_HEADERS, start=1):
            cell = worksheet.cell(row=2, column=column, value=header)
            cell.font = Font(bold=True, color="10202A")
            cell.fill = PatternFill("solid", fgColor="2FBF8F")
        worksheet.freeze_panes = "A3"
    elif worksheet["F2"].value is None:
        # Upgrade workbooks created before cycle-specific snapshots were added.
        if "A1:E1" in {str(cell_range) for cell_range in worksheet.merged_cells.ranges}:
            worksheet.unmerge_cells("A1:E1")
            worksheet.merge_cells("A1:F1")
        worksheet["F2"] = "Cycle"
        worksheet["F2"].font = Font(bold=True, color="10202A")
        worksheet["F2"].fill = PatternFill("solid", fgColor="2FBF8F")

    retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for company in sorted(companies, key=lambda item: item.domain.lower()):
        grade = (company.grade or "Unknown").upper()
        worksheet.append([retrieved_at, company.domain, company.name, company.score, grade, cycle])
        row = worksheet.max_row
        worksheet.cell(row=row, column=1).number_format = "yyyy-mm-dd hh:mm:ss"
        worksheet.cell(row=row, column=4).number_format = "0"
        worksheet.cell(row=row, column=5).font = Font(bold=True)
        if grade in GRADE_FILLS:
            worksheet.cell(row=row, column=5).fill = PatternFill("solid", fgColor=GRADE_FILLS[grade])

    try:
        workbook.save(output_file)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot update {output_file.name} because it is open in Excel. "
            "Close the workbook and try Update score again."
        ) from exc
    finally:
        workbook.close()
    return len(companies)


def current_month_history_status(
    history_file: Path = SCORE_HISTORY_PATH,
    cycle: int | None = None,
) -> tuple[datetime | None, int]:
    """Return the newest current-month export timestamp and its record count.

    The workbook is opened read-only, keeping this safe to call while building
    the dashboard and before an export is started.
    """
    if not history_file.exists():
        return None, 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    newest: datetime | None = None
    count = 0
    try:
        workbook = load_workbook(history_file, read_only=True, data_only=True)
        worksheet = workbook.active
        for row in worksheet.iter_rows(min_row=3, max_col=6, values_only=True):
            timestamp, logged_cycle = row[0], row[5]
            if cycle is not None and logged_cycle != cycle:
                continue
            if isinstance(timestamp, datetime) and month_start <= timestamp.replace(tzinfo=None) <= now:
                count += 1
                timestamp = timestamp.replace(tzinfo=None)
                if newest is None or timestamp > newest:
                    newest = timestamp
        workbook.close()
    except (OSError, ValueError):
        return None, 0
    return newest, count

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
