"""Generate and download fresh SecurityScorecard reports for a portfolio."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from models import Company
from Services.rate_limit import RequestPacer, StatusCallback
from ssc_client import RateLimitError, SecurityScorecardClient
from utils import make_filename, sanitize_filename


REPORT_TYPES = ("detailed_report", "issue_report")

# Pacing is tracked per endpoint: SecurityScorecard limits POST /reports/detailed
# more strictly than everything else, and a limit there should not slow the rest.
REPORT_ENDPOINTS = {"detailed_report": "reports/detailed", "issue_report": "reports/issues"}

# Reports take minutes to generate and every status check downloads the whole
# recent-reports list, so checks start slow and back off.
POLL_INTERVALS = (15, 20, 30, 45, 60)


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


def _request_report(pacer: RequestPacer, client: SecurityScorecardClient, company: Company, report_type: str) -> PendingReport:
    return pacer.run(
        REPORT_ENDPOINTS[report_type],
        partial(_request_single, client, company, report_type),
        f"requesting {report_type} for {company.domain}",
    )


def _request_new_reports(
    client: SecurityScorecardClient,
    companies: list[Company],
    report_types: tuple[str, ...],
    pacer: RequestPacer,
) -> list[PendingReport]:
    """Request the selected report types; never reuse a report from a prior run."""
    pending: list[PendingReport] = []
    total = len(companies)
    for index, original in enumerate(companies, start=1):
        try:
            details = pacer.run(
                "companies",
                partial(client.get_company, original.domain),
                f"checking {original.domain}",
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
                pending.append(_request_report(pacer, client, company, report_type))
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
    pacer: RequestPacer,
    *,
    timeout: int = 3600,
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
            recent = pacer.run("reports/recent", client.list_recent_reports, "checking report status")
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
    pacer: RequestPacer,
) -> bytes:
    content = pacer.run(
        "download",
        partial(client.download_report, str(report["download_url"])),
        f"downloading {item.report_type} for {item.company.domain}",
    )
    _validate_download(content, item.extension, item.company.domain)
    return content


def _save_report(
    client: SecurityScorecardClient,
    item: PendingReport,
    report: dict,
    output_dir: Path,
    label: str,
    pacer: RequestPacer,
) -> Path:
    """Save a finished report, downloading it again and then regenerating it if invalid.

    Re-downloading is tried first because generating a replacement counts
    against SecurityScorecard's stricter report-generation limit.
    """
    try:
        content = _download_valid(client, item, report, pacer)
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
            content = _download_valid(client, item, report, pacer)
        except RateLimitError:
            raise
        except Exception as second_exc:
            logging.warning(
                "[%s] %s is still invalid (%s). Requesting a replacement report…",
                item.company.domain,
                item.report_type,
                second_exc,
            )
            replacement = _request_report(pacer, client, item.company, item.report_type)
            replacement_report = _wait_for_current_batch(
                client,
                [replacement],
                pacer,
                timeout=600,
            ).get(replacement.receipt_id)
            if replacement_report is None:
                raise TimeoutError("replacement report was not ready within 10 minutes") from second_exc
            item = replacement
            content = _download_valid(client, replacement, replacement_report, pacer)

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
    on_status: StatusCallback | None = None,
) -> list[Path]:
    """Generate selected report types, then save valid files only.

    Every file is tied to a receipt returned during this invocation, preventing
    a stale report from a previous month from being downloaded by mistake.
    Requests are paced and rate limits waited out by one shared RequestPacer;
    ``on_status`` receives its state for the rate-limit timer.
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
    pacer = RequestPacer(
        # Looked up on each call so tests can patch the time module.
        sleep=lambda seconds: time.sleep(seconds),
        clock=lambda: time.monotonic(),
        on_status=on_status,
    )
    logging.info(
        "Requesting fresh %s reports for %d companies…",
        ", ".join(report_types),
        len(companies),
    )
    saved: list[Path] = []
    pending: list[PendingReport] = []
    try:
        pending = _request_new_reports(client, companies, report_types, pacer)
        if not pending:
            return []
        completed = _wait_for_current_batch(client, pending, pacer)
        for item in pending:
            report = completed.get(item.receipt_id)
            if report is None:
                logging.error("[%s] %s was not ready before timeout.", item.company.domain, item.report_type)
                continue
            label = labels.get(item.company.domain, item.company.name)
            try:
                destination = _save_report(client, item, report, output_dir, label, pacer)
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
    finally:
        logging.info(pacer.finish())
    return sorted(saved, key=lambda path: str(path).lower())
