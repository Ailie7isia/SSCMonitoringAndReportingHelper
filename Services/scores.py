from __future__ import annotations

# -----------------------------------------------------------------------------
# This file retrieves company scores from the SecurityScorecard portfolio,
# displays a summary, and appends the results to the Excel score history.
# -----------------------------------------------------------------------------

import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import environ
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException

from config import PROJECT_DIR
from models import Company

DEFAULT_SCORE_HISTORY_PATH = PROJECT_DIR / "SSC Helper Log.xlsx"
SCORE_HISTORY_PATH = Path(environ.get("SSC_SCORE_HISTORY_PATH", DEFAULT_SCORE_HISTORY_PATH))
# A missing, locked, corrupt, or half-synced workbook is treated as no history
# so read-only views (including dashboard start-up) never crash.
UNREADABLE_WORKBOOK_ERRORS = (OSError, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException)
HISTORY_HEADERS = ["Retrieved (UTC)", "Domain", "Company", "Score", "Grade", "Cycle"]
GRADE_FILLS = {
    "A": "35C98A",
    "B": "F1BE4D",
    "C": "F48F4A",
    "D": "EE5D69",
    "F": "C93546",
}
# Sheet holding factor scores (see Services/factors.py); every other sheet
# lookup in this module means the score history.
FACTOR_SHEET = "Factor History"


def score_sheet(workbook, *, create: bool = False):
    """Return the score-history sheet: the first sheet that is not the factor sheet.

    ``workbook.active`` is whichever sheet was selected when the file was last
    saved, so after the workbook is saved in Excel on the Factor History tab it
    would point there. Readers use this lookup instead.
    """
    for worksheet in workbook.worksheets:
        if worksheet.title != FACTOR_SHEET:
            return worksheet
    if create:
        return workbook.create_sheet("Score History", 0)
    raise KeyError("The workbook has no score-history sheet.")


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

    A domain does not need to still be in the live portfolio. Scores are based on the newest saved
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
        worksheet = score_sheet(workbook)
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
    except UNREADABLE_WORKBOOK_ERRORS:
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
        worksheet = score_sheet(workbook)
        cutoff =datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
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
    except UNREADABLE_WORKBOOK_ERRORS:
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
    else:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
    worksheet = score_sheet(workbook, create=True)

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
        worksheet = score_sheet(workbook)
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
    except UNREADABLE_WORKBOOK_ERRORS:
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
