from __future__ import annotations

# -----------------------------------------------------------------------------
# This file retrieves company scores from the SecurityScorecard portfolio,
# displays a summary, and exports the results to a JSON file.
# -----------------------------------------------------------------------------

from models import Company
from collections import Counter
from pathlib import Path
from config import load_config, validate_ssc_config
from Services.portfolio import companies_from_payload
from ssc_client import SecurityScorecardClient
import json

# Grade sort for displays.
GRADE_ORDER = {
    "A": 5,
    "B": 4,
    "C": 3,
    "D": 2,
    "F": 1,
}

# Display the score for each company in the portfolio.
def display_scores(companies: list[Company]) -> None:
    print("\n========== PORTFOLIO SCORES ==========\n")

    for company in companies:
        print(
            f"[{company.score if company.score is not None else '-'}] "
            f"{company.domain}"
        )

# Export company information and scores to a JSON file.
def export_scores(
    companies: list[Company],
    output_file: Path,
) -> None:
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = [
    {
        "domain": company.domain,
        "name": company.name,
        "score": company.score,
    }
    for company in sorted(companies, key=lambda c: c.domain)
    ]

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            payload,
            f,
            indent=4,
            ensure_ascii=False,
        )

# Count the number of companies for each score/grade.
def grade_statistics(
    companies: list[Company],
) -> dict[str, int]:

    counts = Counter(
        company.grade or "Unknown"
        for company in companies
    )

    return dict(counts)

# Main workflow for retrieving, displaying, and exporting portfolio scores.
def run_score_export(
    *,
    config_path: Path,
    output: Path,
) -> None:

    config = load_config(config_path)

    api_key, portfolio_id = validate_ssc_config(config)

    client = SecurityScorecardClient(api_key)

    companies = companies_from_payload(
        client.fetch_portfolio_companies(portfolio_id)
    )

    display_scores(companies)

    print_statistics(companies)

    export_scores(
        companies,
        output,
    )

# Print a summary of the portfolio score distribution.
def print_statistics(companies: list[Company]) -> None:
    stats = grade_statistics(companies)

    print("========== GRADE SUMMARY ==========\n")

    total = sum(stats.values())

    for grade in ["A", "B", "C", "D", "F", "Unknown"]:
        if grade in stats:
            print(f"{grade:>7}: {stats[grade]}")

    print(f"\nTotal : {total}\n")