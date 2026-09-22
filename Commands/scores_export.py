from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from models import Company
from config import CONFIG_PATH, load_config, validate_ssc_config
from constants import OPTION_VENDORS
from Services.factors import update_factor_history
from Services.portfolio import companies_for_cycle_action, companies_from_payload
from Services.scores import SCORE_HISTORY_PATH, append_score_history, display_scores
from ssc_client import SecurityScorecardClient
from utils import normalize_domain

# -----------------------------------------------------------------------------
# This file serves as the entry point for retrieving SecurityScorecard
# company scores and appending them to the Excel history.
# -----------------------------------------------------------------------------

# Parse command-line arguments for the score export command.
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display and append SecurityScorecard portfolio scores."
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.yaml",
    )

    parser.add_argument(
        "--history",
        type=Path,
        default=SCORE_HISTORY_PATH,
        help="Excel workbook that receives appended score history.",
    )
    parser.add_argument(
        "--cycle",
        type=int,
        choices=sorted(OPTION_VENDORS),
        required=True,
        help="Portfolio cycle to record.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    args = parse_args(argv)

    try:
        # Load application configuration.
        config = load_config(args.config)

        api_key, portfolio_id = validate_ssc_config(config)

        # Create the SecurityScorecard API client.
        client = SecurityScorecardClient(api_key)

        # Retrieve the companies in the current portfolio.
        entries = client.fetch_portfolio_companies(portfolio_id)

        selected_domains = {
            company.domain
            for company in companies_for_cycle_action(
                companies_from_payload(entries), args.cycle
            )
        }
        companies = []

        # Retrieve each company's latest score and grade.
        for item in entries:
            # Match companies_from_payload, which also accepts "website".
            domain = str(item.get("domain") or item.get("website") or "").strip()
            if not domain or normalize_domain(domain) not in selected_domains:
                continue

            details = client.get_company(domain)

            companies.append(
                Company(
                    domain=domain,
                    name=item.get("name", domain),
                    grade=details.get("grade", ""),
                    score=details.get("score"),
                )
            )

        # Display the scores and append them to the Excel history.
        display_scores(companies)

        appended = append_score_history(companies, args.cycle, args.history)

        logging.info(
            "Appended %d score records to %s",
            appended,
            args.history,
        )

        # Record the ten factor scores alongside, backfilling missing past months.
        factor_update = update_factor_history(client, companies, args.cycle, args.history)
        logging.info(
            "Saved factor scores for %d domains (%d past months backfilled).",
            factor_update.live,
            factor_update.backfilled,
        )
        if factor_update.failed:
            logging.warning("Factor scores unavailable for: %s", ", ".join(factor_update.failed))

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
