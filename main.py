"""Application launcher.

The graphical Monitoring Helper is the default experience. Pass ``--cli``
to keep using the original menu-driven interface from a terminal.
"""

from __future__ import annotations

import sys


def run_cli() -> None:
    from Commands.portfolio_cycle import main as portfolio_cycle
    from Commands.reports_download import main as reports_download
    from Commands.scores_export import main as scores_export

    menu = {
        "1": ("Portfolio Cycle", portfolio_cycle),
        "2": ("Download Reports", reports_download),
        "3": ("Update Score History", scores_export),
    }
    while True:
        print("\n" + "=" * 52)
        print(" SecurityScorecard Monitoring and Reporting Helper")
        print("=" * 52)
        for key, (name, _) in menu.items():
            print(f"{key}. {name}")
        print("0. Exit\n")
        try:
            choice = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return
        if choice == "0":
            print("Goodbye.")
            return
        command = menu.get(choice)
        if command is None:
            print("\nInvalid option.")
            continue
        try:
            command[1]()
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
        except SystemExit:
            # Commands report their own failure details; return to the menu.
            pass
        input("\nPress Enter to return to the menu...")


def main() -> None:
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        run_cli()
        return
    from gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
