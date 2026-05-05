from lgi.config import InstallerConfig


def init_system_screen(stdscr, config: InstallerConfig) -> str:
    return "Init system is configured through Kconfig menuconfig."


def system_basics_screen(stdscr, config: InstallerConfig) -> str:
    return "System basics are configured through Kconfig menuconfig."
