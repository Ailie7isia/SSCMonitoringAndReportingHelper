from __future__ import annotations

# -----------------------------------------------------------------------------
# This file manages the process of retrieving SecurityScorecard reports.
# It checks for existing reports, generates new ones when needed, waits
# for completion, and saves the downloaded PDF files.
# -----------------------------------------------------------------------------

import logging
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from models import Company
from ssc_client import SecurityScorecardClient
from utils import make_filename

# -----------------------------------------------------------------------------

# Check whether a recent report already exists for the company.
def ensure_report(
    company: Company,
    report_map: dict[str, str],
) -> str | None:

    return report_map.get(company.domain.lower())

# -----------------------------------------------------------------------------

# Wait until SecurityScorecard finishes generating the report.
# Returns the download URL when the report is ready.
def wait_until_complete(
    client: SecurityScorecardClient,
    report_id: str,
    *,
    timeout: int = 600,
    interval: int = 10,
) -> str:
    deadline = time.time() + timeout

    while time.time() < deadline:

        report = client.get_report(report_id)

        status = (
            report.get("status")
            or report.get("state")
            or ""
        ).lower()

        if status in {"completed", "complete", "finished", "ready"}:

            url = report.get("download_url")

            if not url:
                raise RuntimeError(
                    "Report completed but download URL is missing."
                )

            return url

        if status in {"failed", "error"}:
            raise RuntimeError(
                f"Report generation failed ({report_id})."
            )

        logging.info(
            "Waiting for report %s (%s)...",
            report_id,
            status or "processing",
        )

        time.sleep(interval)

    raise TimeoutError(
        f"Timed out waiting for report {report_id}."
    )

# -----------------------------------------------------------------------------

# Download a report for a single company.
# Generates a new report if no recent report is available.
def download_single(
    client: SecurityScorecardClient,
    company: Company,
    output_dir: Path,
    report_map: dict[str, str],
    *,
    report_type: str = "detailed_report",
) -> Path:

    # Reuse an existing report when available.
    url = ensure_report(
        company,
        report_map,
    )

    if url is None:

        logging.info(
            "[%s] No recent report found. Generating...",
            company.domain,
        )

        report = client.create_report(
            domain=company.domain,
            report_type=report_type,
        )

        report_id = report.get("id")

        if not report_id:
            raise RuntimeError(
                f"SSC did not return a report ID for {company.domain}."
            )

        url = wait_until_complete(
            client,
            report_id,
        )

    else:

        logging.info(
            "[%s] Using existing report.",
            company.domain,
        )

    pdf = client.download_report(url)

    month = datetime.now(
        timezone.utc
    ).strftime("%B %Y")

    filename = make_filename(
        company.grade,
        company.name,
        month,
        report_type,
    )

    destination = output_dir / filename

    destination.write_bytes(pdf)

    logging.info(
        "[%s] Saved %s",
        company.domain,
        destination.name,
    )

    return destination

# -----------------------------------------------------------------------------

# Save the downloaded PDF using the standard filename format.
def download_reports(
    client: SecurityScorecardClient,
    companies: list[Company],
    output_dir: Path,
    *,
    workers: int = 4,
) -> list[Path]:

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Fetch the recent report list once to avoid repeated API calls.
    logging.info("Fetching recent reports...")

    recent_reports = client.list_recent_reports()

    report_map: dict[str, str] = {}

    for report in recent_reports:

        if report.get("format") != "pdf":
            continue

        params = report.get("params") or {}

        domain = params.get("domain", "").lower()

        url = report.get("download_url")

        if domain and url:
            report_map[domain] = url

    logging.info(
        "Found %d existing reports.",
        len(report_map),
    )

    workers = max(
        1,
        min(workers, len(companies)),
    )

    logging.info(
        "Downloading reports (%d companies, %d workers)...",
        len(companies),
        workers,
    )

    saved: list[Path] = []

    # Download reports concurrently to improve performance.
    with ThreadPoolExecutor(max_workers=workers) as executor:

        futures = {
            executor.submit(
                download_single,
                client,
                company,
                output_dir,
                report_map,
            ): company
            for company in companies
        }

        completed = 0

        # Process completed downloads as they finish.
        for future in as_completed(futures):

            company = futures[future]
            completed += 1

            try:
                path = future.result()

                saved.append(path)

                logging.info(
                    "[%d/%d] ✓ %s",
                    completed,
                    len(companies),
                    company.domain,
                )

            except Exception as exc:

                logging.error(
                    "[%d/%d] ✗ %s (%s)",
                    completed,
                    len(companies),
                    company.domain,
                    exc,
                )

    logging.info(
        "Finished downloading %d/%d reports.",
        len(saved),
        len(companies),
    )

    return sorted(
        saved,
        key=lambda p: p.name,
    )