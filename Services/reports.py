"""Generate and download fresh SecurityScorecard reports for a portfolio."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Callable, TypeVar

from models import Company
from ssc_client import RateLimitError, SecurityScorecardClient
from utils import format_duration, make_filename, sanitize_filename


REPORT_TYPES = ("detailed_report", "issue_report")

# SecurityScorecard allows 5,000 requests per rolling hour, and
# POST /reports/detailed has a stricter, undisclosed per-endpoint limit.
# Requests are sent one at a time: parallel requests only reach it sooner.
RATE_LIMIT_RETRIES = 5
# Used only when a 429 response does not say how long to wait.
FALLBACK_RATE_LIMIT_WAITS = (60, 120, 300, 600, 900)
MAX_RATE_LIMIT_WAIT = 65 * 60
# Reports take minutes to generate and every status check downloads the whole
# recent-reports list, so checks start slow and back off.
POLL_INTERVALS = (15, 20, 30, 45, 60)

# Called with the local time requests will resume, then with None once waiting ends.
RateLimitCallback = Callable[[datetime | None], None]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PendingReport:
    """A report receipt returned by SSC for this specific batch."""

    receipt_id: str
    company: Company
    report_type: str
    extension: str


def _wait_for_quota(
    seconds: float,
    activity: str,
    *,
    estimated: bool,
    limit: str | None,
    on_rate_limit: RateLimitCallback | None,
) -> None:
    seconds = min(max(seconds, 1), MAX_RATE_LIMIT_WAIT)
    resume_at = datetime.now().astimezone() + timedelta(seconds=seconds)
    logging.warning(
        "SecurityScorecard request limit reached while %s%s. Waiting %s until %s (%s).",
        activity,
        f" (limit: {limit})" if limit else "",
        format_duration(seconds),
        f"{resume_at:%H:%M:%S}",
        "estimated; SecurityScorecard did not say when the quota resets"
        if estimated
        else "reset time from SecurityScorecard",
    )
    if on_rate_limit:
        on_rate_limit(resume_at)
    try:
        time.sleep(seconds)
    finally:
        if on_rate_limit:
            on_rate_limit(None)


def _with_rate_limit(
    action: Callable[[], T],
    activity: str,
    on_rate_limit: RateLimitCallback | None,
) -> T:
    """Run an API call, waiting out SecurityScorecard rate limits instead of failing."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return action()
        except RateLimitError as exc:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            estimated = exc.retry_after is None
            wait = (
                FALLBACK_RATE_LIMIT_WAITS[min(attempt, len(FALLBACK_RATE_LIMIT_WAITS) - 1)]
                if estimated
                else exc.retry_after
            )
            _wait_for_quota(wait, activity, estimated=estimated, limit=exc.limit, on_rate_limit=on_rate_limit)
    raise AssertionError("unreachable")


def _request_single(
    client: SecurityScorecardClient,
    company: Company,
    report_type: str,
) -> PendingReport:
    if report_type == "detailed_report":
        receipt = client.create_detailed_report(company.domain)
        extension = ".pdf"
    else:
        receipt = client.create_issues_report(company.domain)
        extension = ".csv"
    receipt_id = str(receipt.get("id") or "").strip()
    if not receipt_id:
        raise RuntimeError("SecurityScorecard did not return a report receipt ID.")
    return PendingReport(receipt_id, company, report_type, extension)


def _request_new_reports(
    client: SecurityScorecardClient,
    companies: list[Company],
    report_types: tuple[str, ...],
    on_rate_limit: RateLimitCallback | None,
) -> list[PendingReport]:
    """Request the selected report types; never reuse a report from a prior run."""
    pending: list[PendingReport] = []
    total = len(companies)
    for index, original in enumerate(companies, start=1):
        try:
            details = _with_rate_limit(
                partial(client.get_company, original.domain),
                f"checking {original.domain}",
                on_rate_limit,
            )
        except Exception as exc:
            logging.error(
                "[%d/%d] Could not verify a current score for %s: %s",
                index,
                total,
                original.domain,
                exc,
            )
            continue
        score = details.get("score")
        if score is None:
            logging.warning(
                "[%d/%d] Skipping %s: score is still calculating.",
                index,
                total,
                original.domain,
            )
            continue
        company = Company(
            domain=original.domain,
            name=original.name,
            grade=str(details.get("grade") or original.grade or "Unknown").upper(),
            score=score,
        )
        for report_type in report_types:
            try:
                pending.append(
                    _with_rate_limit(
                        partial(_request_single, client, company, report_type),
                        f"requesting {report_type} for {company.domain}",
                        on_rate_limit,
                    )
                )
                logging.info(
                    "[%d/%d] Requested %s for %s",
                    index,
                    total,
                    report_type,
                    company.domain,
                )
            except Exception as exc:
                logging.error(
                    "[%d/%d] Failed to request %s for %s: %s",
                    index,
                    total,
                    report_type,
                    company.domain,
                    exc,
                )
    return pending


def _wait_for_current_batch(
    client: SecurityScorecardClient,
    pending: list[PendingReport],
    *,
    timeout: int = 3600,
    on_rate_limit: RateLimitCallback | None = None,
) -> dict[str, dict]:
    """Wait only for receipts created by this run, excluding prior-month files."""
    wanted = {item.receipt_id for item in pending}
    completed: dict[str, dict] = {}
    deadline = time.monotonic() + timeout
    checks = 0
    while wanted - completed.keys() and time.monotonic() < deadline:
        interval = POLL_INTERVALS[min(checks, len(POLL_INTERVALS) - 1)]
        logging.info(
            "Waiting for %d of %d newly requested reports to finish; checking in %d seconds…",
            len(wanted) - len(completed),
            len(wanted),
            interval,
        )
        time.sleep(interval)
        checks += 1
        try:
            recent = _with_rate_limit(client.list_recent_reports, "checking report status", on_rate_limit)
        except Exception as exc:
            # A transient API error must not discard a batch that may have
            # been generating for many minutes; keep polling until timeout.
            logging.warning("Could not check report status (%s); trying again.", exc)
            continue
        for report in recent:
            receipt_id = str(report.get("id") or "")
            if receipt_id in wanted and report.get("download_url"):
                completed[receipt_id] = report
    if len(completed) != len(wanted):
        logging.error(
            "Timed out waiting for %d newly requested report(s).",
            len(wanted) - len(completed),
        )
    return completed


def _validate_download(content: bytes, extension: str, domain: str) -> None:
    """Reject empty files and error pages before they enter the reports folder."""
    minimum_size = 4_096 if extension == ".pdf" else 128
    if len(content) < minimum_size:
        raise ValueError(
            f"Downloaded {domain} report is unexpectedly small ({len(content)} bytes)."
        )
    if extension == ".pdf" and not content.lstrip().startswith(b"%PDF-"):
        raise ValueError(f"Downloaded {domain} detailed report is not a valid PDF.")
    if extension == ".csv":
        text = content.decode("utf-8-sig", errors="replace").lstrip()
        if not text or text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
            raise ValueError(f"Downloaded {domain} issues report is empty or an error page.")


def _file_labels(companies: list[Company]) -> dict[str, str]:
    """Name each domain's files, adding the domain when display names collide.

    Windows paths are case-insensitive, so names are compared that way.
    """
    counts = Counter(sanitize_filename(company.name).lower() for company in companies)
    return {
        company.domain: (
            company.name
            if counts[sanitize_filename(company.name).lower()] == 1
            else f"{company.name} ({company.domain})"
        )
        for company in companies
    }


def _destination(output_dir: Path, item: PendingReport, label: str) -> Path:
    month = datetime.now(timezone.utc).strftime("%B %Y")
    filename = make_filename(
        item.company.grade or "Unknown",
        label,
        month,
        item.report_type,
        extension=item.extension,
    )
    folder = "detailed" if item.extension == ".pdf" else "issues"
    return output_dir / folder / filename


def _download_valid(
    client: SecurityScorecardClient,
    item: PendingReport,
    report: dict,
    on_rate_limit: RateLimitCallback | None,
) -> bytes:
    content = _with_rate_limit(
        partial(client.download_report, str(report["download_url"])),
        f"downloading {item.report_type} for {item.company.domain}",
        on_rate_limit,
    )
    _validate_download(content, item.extension, item.company.domain)
    return content


def _save_report(
    client: SecurityScorecardClient,
    item: PendingReport,
    report: dict,
    output_dir: Path,
    label: str,
    on_rate_limit: RateLimitCallback | None,
) -> Path:
    """Save a finished report, downloading it again and then regenerating it if invalid.

    Re-downloading is tried first because generating a replacement counts
    against SecurityScorecard's stricter report-generation limit.
    """
    try:
        content = _download_valid(client, item, report, on_rate_limit)
    except RateLimitError:
        raise
    except Exception as exc:
        logging.warning(
            "[%s] Invalid %s download (%s). Downloading it again…",
            item.company.domain,
            item.report_type,
            exc,
        )
        try:
            content = _download_valid(client, item, report, on_rate_limit)
        except RateLimitError:
            raise
        except Exception as second_exc:
            logging.warning(
                "[%s] %s is still invalid (%s). Requesting a replacement report…",
                item.company.domain,
                item.report_type,
                second_exc,
            )
            replacement = _with_rate_limit(
                partial(_request_single, client, item.company, item.report_type),
                f"requesting a replacement {item.report_type} for {item.company.domain}",
                on_rate_limit,
            )
            replacement_report = _wait_for_current_batch(
                client,
                [replacement],
                timeout=600,
                on_rate_limit=on_rate_limit,
            ).get(replacement.receipt_id)
            if replacement_report is None:
                raise TimeoutError("replacement report was not ready within 10 minutes") from second_exc
            item = replacement
            content = _download_valid(client, replacement, replacement_report, on_rate_limit)

    destination = _destination(output_dir, item, label)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return destination


def download_reports(
    client: SecurityScorecardClient,
    companies: list[Company],
    output_dir: Path,
    report_types: tuple[str, ...] = REPORT_TYPES,
    *,
    on_rate_limit: RateLimitCallback | None = None,
) -> list[Path]:
    """Generate selected report types, then save valid files only.

    Every file is tied to a receipt returned during this invocation, preventing
    a stale report from a previous month from being downloaded by mistake.
    When SecurityScorecard rate-limits a request, the batch waits for the
    quota to reset and ``on_rate_limit`` receives the expected resume time.
    """
    if not companies:
        return []
    invalid_types = set(report_types) - set(REPORT_TYPES)
    if invalid_types:
        raise ValueError(f"Unknown report type(s): {', '.join(sorted(invalid_types))}")
    if not report_types:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = _file_labels(companies)
    logging.info(
        "Requesting fresh %s reports for %d companies…",
        ", ".join(report_types),
        len(companies),
    )
    pending = _request_new_reports(client, companies, report_types, on_rate_limit)
    if not pending:
        return []
    completed = _wait_for_current_batch(client, pending, on_rate_limit=on_rate_limit)
    saved: list[Path] = []
    for item in pending:
        report = completed.get(item.receipt_id)
        if report is None:
            logging.error("[%s] %s was not ready before timeout.", item.company.domain, item.report_type)
            continue
        label = labels.get(item.company.domain, item.company.name)
        try:
            destination = _save_report(client, item, report, output_dir, label, on_rate_limit)
        except Exception as exc:
            logging.error(
                "[%s] Failed downloading %s: %s",
                item.company.domain,
                item.report_type,
                exc,
            )
            continue
        saved.append(destination)
        logging.info("[%s] Saved %s", item.company.domain, destination.name)
    logging.info(
        "Finished downloading %d/%d newly generated reports.",
        len(saved),
        len(pending),
    )
    return sorted(saved, key=lambda path: str(path).lower())
