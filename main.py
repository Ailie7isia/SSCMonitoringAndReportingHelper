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
    print(" SecurityScorecard Monitoring and Reporting Helper")
    print("=" * 45)
    print()


def print_menu() -> None:
    for key, (name, _) in MENU.items():
        print(f"{key}. {name}")

    print("0. Exit")
    print()


def main() -> None:

    while True:

        # Refresh menu every iteration.
        print_banner()
        print_menu()

        try:
            # Remove accidental whitespace from user input.
            choice = input("Select an option: ").strip()

        # Handle program termination from the console gracefully.
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return

        # User selected Exit.
        if choice == "0":
            print("Goodbye.")
            return

        # Retrieve the selected command from the MENU dictionary.
        command = MENU.get(choice)

        # Handle invalid menu selections.
        if command is None:
            print("\nInvalid option.\n")
            continue

        print()

        try:
            command[1]()

        # Prevent Ctrl+C inside a command from terminating the toolkit.
        # Instead, return safely to the main menu.
        except KeyboardInterrupt:
            print("\nOperation cancelled.")

        except SystemExit:

            pass

        input("\nPress Enter to return to the menu...")


if __name__ == "__main__":
    main()