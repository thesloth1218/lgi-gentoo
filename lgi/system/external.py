import curses
import subprocess
from typing import Sequence


def run_interactive_tool(stdscr, args: Sequence[str], *, dry_run: bool = True) -> str:
    command = " ".join(args)
    curses.endwin()
    try:
        if dry_run:
            print(f"[dry-run] Would run interactive tool: {command}")
            print("Press Enter to return to the installer.")
            input()
            return f"Dry-run skipped: {command}"

        completed = subprocess.run(list(args), check=False)
        return f"{command} exited with status {completed.returncode}."
    finally:
        stdscr.clear()
        stdscr.refresh()
        curses.doupdate()
