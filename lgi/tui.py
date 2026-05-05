from lgi.dialog_runner import run_dialog_installer


class TuiApp:
    """Compatibility wrapper for callers that still import TuiApp."""

    def __init__(self, stdscr=None) -> None:
        self.stdscr = stdscr

    def run(self) -> int:
        run_dialog_installer()
        return 0
