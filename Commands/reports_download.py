from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Services.portfolio import companies_from_payload
from Services.reports import download_reports
from ssc_client import SecurityScorecardClient
from config import (
    CONFIG_PATH,
    REPORTS_DIR,
    load_config,
    validate_ssc_config,
)

# -----------------------------------------------------------------------------
# This file serves as the entry point for downloading SecurityScorecard
# reports. It loads the configuration, retrieves the portfolio, and
# starts the report download workflow.
# -----------------------------------------------------------------------------

# Parse command-line arguments for the report download command.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download SecurityScorecard reports."
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.yaml",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for downloaded reports.",
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

        # Create the SecurityScorecard API client.
        api_key, portfolio_id = validate_ssc_config(config)

        # Retrieve the current portfolio.
        client = SecurityScorecardClient(api_key)

        logging.info("Loading portfolio...")

        companies = companies_from_payload(
            client.fetch_portfolio_companies(portfolio_id)
        )

        if not companies:
            logging.warning("Portfolio is empty.")
            return

        today = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d")

        # Use today's date if no output directory is specified.
        output_dir = (
            args.output_dir
            or REPORTS_DIR / today
        )

        # Download reports for all companies in the portfolio.
        saved = download_reports(
            client,
            companies,
            output_dir,
        )

        print(f"\nDownloaded {len(saved)} newly generated report(s).")

        for path in saved:
            print(f"  • {path.name}")

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    # Log unexpected errors and exit with a failure status. 
    except Exception:
        logging.exception("Report download failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
