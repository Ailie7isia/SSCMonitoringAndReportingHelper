from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import (
    CONFIG_PATH,
    REPORTS_DIR,
    load_config,
    validate_ssc_config,
)
from Services.portfolio import companies_from_payload
from Services.reports import download_reports
from ssc_client import SecurityScorecardClient


DEFAULT_WORKERS = 4


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

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Maximum concurrent downloads.",
    )

    return parser.parse_args()


def main() -> None:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    args = parse_args()

    try:
        config = load_config(args.config)

        api_key, portfolio_id = validate_ssc_config(config)

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

        output_dir = (
            args.output_dir
            or REPORTS_DIR / "detailed" / today
        )

        saved = download_reports(
            client,
            companies,
            output_dir,
            workers=args.workers,
        )

        print(f"\nDownloaded {len(saved)} report(s).")

        for path in saved:
            print(f"  • {path.name}")

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    except Exception:
        logging.exception("Report download failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()