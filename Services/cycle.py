from __future__ import annotations

import logging
import time

# -----------------------------------------------------------------------------
# This file loads the current portfolio, compare it with the selected target list, 
# and add or remove domains from portofolio according to comparison result.
# -----------------------------------------------------------------------------

from Services.portfolio import (
    apply_plan,
    companies_from_payload,
    compute_plan,
    confirm_plan,
    print_plan,
    print_summary,
    prompt_option,
    target_domains,
)
from ssc_client import SecurityScorecardClient


def run_cycle(
    client: SecurityScorecardClient,
    portfolio_id: str,
    *,
    option: int | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    pause_seconds: float = 0.35,
) -> None:

    # Retrieve the current portfolio from SecurityScorecard.
    logging.info("Loading current portfolio...")

    start = time.perf_counter()

    companies = companies_from_payload(
        client.fetch_portfolio_companies(portfolio_id)
    )

    logging.info(
        "Loaded %d companies in %.2f seconds.",
        len(companies),
        time.perf_counter() - start,
    )

    # Ask the user which portfolio cycle to run if not specified.
    if option is None:
        option = prompt_option()

    # Compares target list to existing domains.
    target = target_domains(option)

    plan = compute_plan(
        companies,
        target,
    )

    # Display the comparison result.
    print_plan(plan)

    if dry_run:
        logging.info("Dry run complete.")
        return

    # Ask for confirmation before making changes.
    if not assume_yes:
        if not confirm_plan():
            print("\nCancelled.")
            return

    logging.info("Applying portfolio changes...")

    start = time.perf_counter()

    report = apply_plan(
        client,
        portfolio_id,
        plan,
        pause_seconds=pause_seconds,
    )

    logging.info(
        "Portfolio update finished in %.2f seconds.",
        time.perf_counter() - start,
    )

    # Display the final results of the portfolio update.
    print_summary(report)

    # Log whether the operation completed successfully or with failures.
    if report.has_failures:
        logging.warning(
            "Finished with failures "
            "(add=%d fail=%d | remove=%d fail=%d)",
            len(report.added_ok),
            len(report.added_failed),
            len(report.removed_ok),
            len(report.removed_failed),
        )
    else:
        logging.info("Portfolio cycle completed successfully.")