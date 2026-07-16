from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from models import Company
from config import CONFIG_PATH, REPORTS_DIR, load_config, validate_ssc_config
from Services.scores import display_scores, export_scores
from ssc_client import SecurityScorecardClient

# -----------------------------------------------------------------------------
# This file serves as the entry point for retrieving SecurityScorecard
# company scores and exporting them to a JSON file.
# -----------------------------------------------------------------------------

# Parse command-line arguments for the score export command.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display and export SecurityScorecard portfolio scores."
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.yaml",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=REPORTS_DIR / "scores.json",
        help="Output JSON file.",
    )

    return parser.parse_args()


def main() -> None:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    args = parse_args()

    try:
        # Load application configuration.
        config = load_config(args.config)

        api_key, portfolio_id = validate_ssc_config(config)

        # Create the SecurityScorecard API client.
        client = SecurityScorecardClient(api_key)

        # Retrieve the companies in the current portfolio.
        entries = client.fetch_portfolio_companies(portfolio_id)

        companies = []

        # Retrieve each company's latest score and grade.
        for item in entries:
            domain = item["domain"]

            details = client.get_company(domain)

            companies.append(
                Company(
                    domain=domain,
                    name=item.get("name", domain),
                    grade=details.get("grade", ""),
                    score=details.get("score"),
                )
            )

        # Display the scores and export them to a JSON file.
        display_scores(companies)

        export_scores(
            companies,
            args.output,
        )

        logging.info(
            "Scores exported to %s",
            args.output,
        )

    # Exit gracefully if the operation is cancelled by the user.
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    # Log unexpected errors and exit with a failure status.
    except Exception:
        logging.exception("Score export failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()