from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import CONFIG_PATH, load_config, validate_ssc_config
from constants import OPTION_VENDORS
from ssc_client import SecurityScorecardClient
from Services.cycle import run_cycle

# -----------------------------------------------------------------------------
# This file is the entry point for running a portfolio cycle.
# It reads the configuration, creates the SecurityScorecard client,
# and starts the portfolio update workflow.
# -----------------------------------------------------------------------------

# Parse command-line arguments for the portfolio cycle command.
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Run a SecurityScorecard portfolio cycle."
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
    )

    parser.add_argument(
        "--option",
        type=int,
        choices=sorted(OPTION_VENDORS),
        help="Portfolio cycle to apply.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.35,
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

        # Run the portfolio cycle workflow.
        run_cycle(
            client,
            portfolio_id,
            option=args.option,
            dry_run=args.dry_run,
            assume_yes=args.yes,
            pause_seconds=args.pause,
        )

    # Exit gracefully if the operation is cancelled by the user.
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    # Log unexpected errors and exit with a failure status.
    except Exception:
        logging.exception("Portfolio cycle failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
