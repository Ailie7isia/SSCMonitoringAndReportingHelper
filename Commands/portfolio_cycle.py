from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import CONFIG_PATH, load_config, validate_ssc_config
from ssc_client import SecurityScorecardClient
from Services.cycle import run_cycle


def parse_args() -> argparse.Namespace:

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
        choices=range(1, 6),
        help="Portfolio cycle (1-5).",
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

    return parser.parse_args()


def main() -> None:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    args = parse_args()

    try:
        #
        # Load configuration
        #
        config = load_config(args.config)

        api_key, portfolio_id = validate_ssc_config(config)

        #
        # Create SSC client
        #
        client = SecurityScorecardClient(api_key)

        #
        # Execute cycle
        #
        run_cycle(
            client,
            portfolio_id,
            option=args.option,
            dry_run=args.dry_run,
            assume_yes=args.yes,
            pause_seconds=args.pause,
        )

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    except Exception:
        logging.exception("Portfolio cycle failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()