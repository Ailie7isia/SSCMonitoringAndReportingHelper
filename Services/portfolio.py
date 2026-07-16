from __future__ import annotations

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

def companies_from_payload(entries: Iterable[dict]) -> list[Company]:
    companies: list[Company] = []

    for item in entries:
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

def target_domains(option: int) -> set[str]:
    if option not in OPTION_VENDORS:
        raise ValueError(f"Invalid cycle option: {option}")

    pinned = {
        normalize_domain(domain)
        for domain in ALWAYS_PINNED
    }

    selected = {
        normalize_domain(domain)
        for domain in OPTION_VENDORS[option]
    }

    return pinned | selected

def compute_plan(
    companies: list[Company],
    target: set[str],
) -> PortfolioPlan:
    pinned = {
        normalize_domain(domain)
        for domain in ALWAYS_PINNED
    }

    current = {
        company.domain
        for company in companies
    }

    to_remove = sorted(
        domain
        for domain in current
        if domain not in target
        and domain not in pinned
    )

    to_add = sorted(
        domain
        for domain in target
        if domain not in current
    )

    return PortfolioPlan(
        to_add=to_add,
        to_remove=to_remove,
    )

def apply_plan(
    client: SecurityScorecardClient,
    portfolio_id: str,
    plan: PortfolioPlan,
    *,
    pause_seconds: float = 0.35,
) -> CycleApplyReport:
    report = CycleApplyReport()

    for domain in plan.to_remove:

        try:
            client.remove_company(portfolio_id, domain)
            report.removed_ok.append(domain)
            logging.info("Removed %s", domain)

        except Exception as exc:

            report.removed_failed.append((domain, str(exc)))
            logging.error("Failed removing %s: %s", domain, exc)

        if pause_seconds > 0:
            time.sleep(pause_seconds)

    for domain in plan.to_add:

        try:
            client.add_company(portfolio_id, domain)
            report.added_ok.append(domain)
            logging.info("Added %s", domain)

        except Exception as exc:

            report.added_failed.append((domain, str(exc)))
            logging.error("Failed adding %s: %s", domain, exc)

        if pause_seconds > 0:
            time.sleep(pause_seconds)

    return report

def prompt_option() -> int:
    print("\nChoose a portfolio cycle:\n")

    for option in sorted(OPTION_LABELS):
        label = OPTION_LABELS[option]
        count = len(OPTION_VENDORS[option])

        print(f"  {option}. {label} ({count} companies)")

    print()

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

from constants import ALWAYS_PINNED, OPTION_VENDORS
from utils import normalize_domain

def target_domain_order(option: int) -> list[str]:
    return [
        normalize_domain(domain)
        for domain in (
            list(ALWAYS_PINNED) + OPTION_VENDORS[option]
        )
    ]