from lgi.config import InstallerConfig


def review_config_screen(stdscr, config: InstallerConfig) -> str:
    return "Review generated output after running `python3 main.py generate`."
