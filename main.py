from __future__ import annotations

import sys

from Commands.portfolio_cycle import main as portfolio_cycle
from Commands.reports_download import main as reports_download
from Commands.scores_export import main as scores_export


MENU = {
    "1": ("Portfolio Cycle", portfolio_cycle),
    "2": ("Download Reports", reports_download),
    "3": ("Export Scores", scores_export),
}


def print_banner() -> None:
    print("=" * 45)
    print(" SecurityScorecard Portfolio Toolkit")
    print("=" * 45)
    print()


def print_menu() -> None:
    for key, (name, _) in MENU.items():
        print(f"{key}. {name}")

    print("0. Exit")
    print()


def main() -> None:

    while True:

        print_banner()
        print_menu()

        try:
            choice = input("Select an option: ").strip()

        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return

        if choice == "0":
            print("Goodbye.")
            return

        command = MENU.get(choice)

        if command is None:
            print("\nInvalid option.\n")
            continue

        print()

        try:
            command[1]()

        except KeyboardInterrupt:
            print("\nOperation cancelled.")

        except SystemExit:

            pass

        input("\nPress Enter to return to the menu...")


if __name__ == "__main__":
    main()