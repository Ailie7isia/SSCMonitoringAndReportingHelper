from __future__ import annotations

import logging
import time

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

    if option is None:
        option = prompt_option()

    target = target_domains(option)

    plan = compute_plan(
        companies,
        target,
    )

    print_plan(plan)

    if dry_run:
        logging.info("Dry run complete.")
        return

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

    print_summary(report)

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