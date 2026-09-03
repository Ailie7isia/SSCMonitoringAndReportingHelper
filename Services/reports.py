"""Generate and download fresh SecurityScorecard reports for a portfolio."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models import Company
from ssc_client import SecurityScorecardClient
from utils import make_filename


# Keep report requests polite to the API while avoiding one slow domain holding
# up every other report in the portfolio.
REQUEST_WORKERS = 2
REPORT_TYPES = ("detailed_report", "issue_report")


@dataclass(frozen=True, slots=True)
class PendingReport:
    """A report receipt returned by SSC for this specific batch."""

    receipt_id: str
    company: Company
    report_type: str
    extension: str


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
) -> list[PendingReport]:
    """Request the selected report types; never reuse a report from a prior run.

    Each worker owns a separate requests session. This lets report generation
    start for multiple domains at once without sharing a Session across threads.
    """
    if not companies:
        return []

    def request_company(index: int, original: Company) -> tuple[int, list[PendingReport]]:
        worker_client = SecurityScorecardClient(client.api_key, timeout=client.timeout)
        company = original
        try:
            details = worker_client.get_company(company.domain)
            score = details.get("score")
            if score is None:
                logging.warning(
                    "[%d/%d] Skipping %s: score is still calculating.",
                    index,
                    len(companies),
                    company.domain,
                )
                return index, []
            company = Company(
                domain=company.domain,
                name=company.name,
                grade=str(details.get("grade") or company.grade or "Unknown").upper(),
                score=score,
            )
        except Exception as exc:
            logging.error(
                "[%d/%d] Could not verify a current score for %s: %s",
                index,
                len(companies),
                company.domain,
                exc,
            )
            return index, []
        requested: list[PendingReport] = []
        for report_type in report_types:
            try:
                requested.append(_request_single(worker_client, company, report_type))
                logging.info(
                    "[%d/%d] Requested %s for %s",
                    index,
                    len(companies),
                    report_type,
                    company.domain,
                )
            except Exception as exc:
                logging.error(
                    "[%d/%d] Failed to request %s for %s: %s",
                    index,
                    len(companies),
                    report_type,
                    company.domain,
                exc,
            )
        return index, requested

    pending_by_index: dict[int, list[PendingReport]] = {}
    worker_count = min(REQUEST_WORKERS, len(companies))
    logging.info(
        "Verifying and requesting reports with up to %d concurrent workers.",
        worker_count,
    )
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="report-request") as executor:
        futures = [
            executor.submit(request_company, index, company)
            for index, company in enumerate(companies, start=1)
        ]
        for future in as_completed(futures):
            index, requested = future.result()
            pending_by_index[index] = requested
    pending = [
        report
        for index in range(1, len(companies) + 1)
        for report in pending_by_index.get(index, [])
    ]
    return pending


def _wait_for_current_batch(
    client: SecurityScorecardClient,
    pending: list[PendingReport],
    *,
    timeout: int = 3600,
    interval: int = 5,
) -> dict[str, dict]:
    """Wait only for receipts created by this run, excluding prior-month files."""
    wanted = {item.receipt_id for item in pending}
    completed: dict[str, dict] = {}
    deadline = time.monotonic() + timeout
    while wanted - completed.keys() and time.monotonic() < deadline:
        for report in client.list_recent_reports():
            receipt_id = str(report.get("id") or "")
            if receipt_id in wanted and report.get("download_url"):
                completed[receipt_id] = report
        remaining = len(wanted) - len(completed)
        if remaining:
            logging.info(
                "Waiting for %d of %d newly requested reports to finish; checking again in %d seconds…",
                remaining,
                len(wanted),
                interval,
            )
            time.sleep(interval)
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


def _destination(output_dir: Path, item: PendingReport) -> Path:
    month = datetime.now(timezone.utc).strftime("%B %Y")
    filename = make_filename(
        item.company.grade or "Unknown",
        item.company.name,
        month,
        item.report_type,
        extension=item.extension,
    )
    folder = "detailed" if item.extension == ".pdf" else "issues"
    return output_dir / folder / filename


def _save_completed_report(
    client: SecurityScorecardClient,
    item: PendingReport,
    report: dict,
    output_dir: Path,
) -> Path:
    content = client.download_report(str(report["download_url"]))
    _validate_download(content, item.extension, item.company.domain)
    destination = _destination(output_dir, item)
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
) -> list[Path]:
    """Generate selected report types, then save valid files only.

    Every file is tied to a receipt returned during this invocation, preventing
    a stale report from a previous month from being downloaded by mistake.
    """
    if not companies:
        return []
    invalid_types = set(report_types) - set(REPORT_TYPES)
    if invalid_types:
        raise ValueError(f"Unknown report type(s): {', '.join(sorted(invalid_types))}")
    if not report_types:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.info(
        "Requesting fresh %s reports for %d companies…",
        ", ".join(report_types),
        len(companies),
    )
    pending = _request_new_reports(client, companies, report_types)
    if not pending:
        return []
    completed = _wait_for_current_batch(client, pending)
    saved: list[Path] = []
    for item in pending:
        report = completed.get(item.receipt_id)
        if report is None:
            logging.error("[%s] %s was not ready before timeout.", item.company.domain, item.report_type)
            continue
        try:
            destination = _save_completed_report(client, item, report, output_dir)
            saved.append(destination)
            logging.info("[%s] Saved %s", item.company.domain, destination.name)
        except Exception as exc:
            logging.warning(
                "[%s] Invalid %s download (%s). Requesting one retry…",
                item.company.domain,
                item.report_type,
                exc,
            )
            try:
                retry = _request_single(client, item.company, item.report_type)
                retry_report = _wait_for_current_batch(
                    client,
                    [retry],
                    timeout=600,
                ).get(retry.receipt_id)
                if retry_report is None:
                    raise TimeoutError("replacement report was not ready within 10 minutes")
                destination = _save_completed_report(client, retry, retry_report, output_dir)
                saved.append(destination)
                logging.info("[%s] Saved retry %s", item.company.domain, destination.name)
            except Exception as retry_exc:
                logging.error(
                    "[%s] Failed downloading %s after retry: %s",
                    item.company.domain,
                    item.report_type,
                    retry_exc,
                )
    logging.info(
        "Finished downloading %d/%d newly generated reports.",
        len(saved),
        len(pending),
    )
    return sorted(saved, key=lambda path: str(path).lower())
