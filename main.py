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
    from Services.portfolio import prompt_option

    # (name, command, whether the command needs a --cycle argument)
    menu = {
        "1": ("Portfolio Cycle", portfolio_cycle, False),
        "2": ("Download Reports", reports_download, True),
        "3": ("Update Score History", scores_export, True),
    }
    while True:
        print("\n" + "=" * 52)
        print(" SecurityScorecard Monitoring and Reporting Helper")
        print("=" * 52)
        for key, (name, _, _) in menu.items():
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
        _, run_command, needs_cycle = command
        try:
            # The portfolio cycle command prompts for its own cycle.
            run_command(["--cycle", str(prompt_option())] if needs_cycle else [])
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
