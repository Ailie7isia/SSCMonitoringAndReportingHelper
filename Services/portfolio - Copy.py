from __future__ import annotations

# -----------------------------------------------------------------------------#
# This file contains the core logic for managing the SecurityScorecard
# portfolio, including loading company data, comparing portfolio cycles,
# and applying additions or removals.
# -----------------------------------------------------------------------------

import logging
import time
from typing import Iterable

from constants import (
    ALWAYS_PINNED,
    OPTION_LABELS,
    OPTION_VENDORS,
)
from models import (
    Company,
    CycleApplyReport,
    PortfolioPlan,
)
from ssc_client import (
    ApiRequestError,
    SecurityScorecardClient,
)
from utils import (
    normalize_domain,
    normalize_grade,
)

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------

# Ask the user to confirm before applying portfolio changes.
def confirm_plan() -> bool:
    print()
    print("=" * 40)
    print("Type YES to apply these changes.")
    print("Anything else will cancel.")
    print("=" * 40)

    try:
        answer = input("> ").strip()
    except EOFError:
        return False

    return answer == "YES"

# Convert the API response into a list of Company objects.
def companies_from_payload(entries: Iterable[dict]) -> list[Company]:
    companies: list[Company] = []

    for item in entries:
        # SecurityScorecard may return the domain under different field names.
        raw_domain = item.get("domain") or item.get("website")
        if not raw_domain:
            continue

        domain = normalize_domain(str(raw_domain))

        companies.append(
            Company(
                domain=domain,
                name=str(item.get("name") or domain).strip(),
                grade=normalize_grade(
                    item.get("grade")
                    or item.get("current_grade")
                    or item.get("score_grade")
                ),
            )
        )

    return companies

# Build the target domain list for the selected portfolio cycle.
def target_domains(option: int) -> set[str]:
    if option not in OPTION_VENDORS:
        raise ValueError(f"Invalid cycle option: {option}")

    # Always include the permanently monitored domains.
    pinned = {
        normalize_domain(domain)
        for domain in ALWAYS_PINNED
    }

    # Add the domains for the selected cycle.
    selected = {
        normalize_domain(domain)
        for domain in OPTION_VENDORS[option]
    }

    # Combine pinned and selected domains.
    return pinned | selected

# Compare the current portfolio with the target list and determine
# which domains need to be added or removed.
def compute_plan(
    companies: list[Company],
    target: set[str],
) -> PortfolioPlan:
    # Always keep pinned domains in the portfolio.
    pinned = {
        normalize_domain(domain)
        for domain in ALWAYS_PINNED
    }

    current = {
        # Get the domains currently in the portfolio.
        company.domain
        for company in companies
    }

    # Domains to remove (excluding pinned domains).
    to_remove = sorted(
        domain
        for domain in current
        if domain not in target
        and domain not in pinned
    )

    # Domains that need to be added.
    to_add = sorted(
        domain
        for domain in target
        if domain not in current
    )

    return PortfolioPlan(
        to_add=to_add,
        to_remove=to_remove,
    )

# Apply the planned portfolio changes and record the results.
def apply_plan(
    client: SecurityScorecardClient,
    portfolio_id: str,
    plan: PortfolioPlan,
    *,
    pause_seconds: float = 0.35,
) -> CycleApplyReport:
    report = CycleApplyReport()

    # Remove domains that are no longer required.
    for domain in plan.to_remove:

        try:
            client.remove_company(portfolio_id, domain)
            report.removed_ok.append(domain)
            logging.info("Removed %s", domain)

        except Exception as exc:

            report.removed_failed.append((domain, str(exc)))
            logging.error("Failed removing %s: %s", domain, exc)

        # Brief pause to avoid sending API requests too quickly.
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    # Add new domains to the portfolio.
    for domain in plan.to_add:

        try:
            client.add_company(portfolio_id, domain)
            report.added_ok.append(domain)
            logging.info("Added %s", domain)

        except Exception as exc:

            report.added_failed.append((domain, str(exc)))
            logging.error("Failed adding %s: %s", domain, exc)

        # Brief pause to avoid sending API requests too quickly.
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    return report

# Display the available portfolio cycle options and return the user's selection.
def prompt_option() -> int:
    print("\nChoose a portfolio cycle:\n")

    for option in sorted(OPTION_LABELS):
        label = OPTION_LABELS[option]
        count = len(OPTION_VENDORS[option])

        print(f"  {option}. {label} ({count} companies)")

    print()

    # Keep asking until a valid option is entered.
    while True:
        try:
            raw = input("Enter option [1-5]: ").strip()
        except EOFError:
            raise KeyboardInterrupt

        try:
            option = int(raw)
        except ValueError:
            print("Please enter a number between 1 and 5.\n")
            continue

        if option in OPTION_VENDORS:
            return option

        print("Invalid option.\n")

# Display the planned portfolio additions and removals.
def print_plan(plan: PortfolioPlan) -> None:
    print("\n========== PORTFOLIO PLAN ==========\n")

    print(f"Companies to add    : {len(plan.to_add)}")
    if plan.to_add:
        for domain in plan.to_add:
            print(f"  + {domain}")

    print()

    print(f"Companies to remove : {len(plan.to_remove)}")
    if plan.to_remove:
        for domain in plan.to_remove:
            print(f"  - {domain}")

    print()

# Display a summary of the portfolio update results.
def print_summary(report: CycleApplyReport) -> None:
    print("\n========== SUMMARY ==========\n")

    print(f"Added successfully   : {len(report.added_ok)}")

    if report.added_failed:
        print(f"\nFailed to add ({len(report.added_failed)}):")
        for domain, reason in report.added_failed:
            print(f"  • {domain}")
            print(f"    {reason}")

    print()

    print(f"Removed successfully : {len(report.removed_ok)}")

    if report.removed_failed:
        print(f"\nFailed to remove ({len(report.removed_failed)}):")
        for domain, reason in report.removed_failed:
            print(f"  • {domain}")
            print(f"    {reason}")

    print()

# Return the expected domain order for the selected portfolio cycle.
# Pinned domains are always listed first
def target_domain_order(option: int) -> list[str]:
    return [
        normalize_domain(domain)
        for domain in (
            list(ALWAYS_PINNED) + OPTION_VENDORS[option]
        )
    ]