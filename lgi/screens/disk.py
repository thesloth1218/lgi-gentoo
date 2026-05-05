from lgi.config import InstallerConfig
from lgi.system.inspect import SystemInspector


def disk_setup_screen(stdscr, config: InstallerConfig, inspector: SystemInspector) -> str:
    return "Disk setup is configured through Kconfig menuconfig."
