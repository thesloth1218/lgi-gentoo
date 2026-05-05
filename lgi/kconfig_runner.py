from pathlib import Path

from lgi.config import DiskConfig, InstallerConfig, KernelConfig, SystemConfig, default_make_opts
from lgi.output.writers import OutputWriter


ROOT = Path(__file__).resolve().parent.parent
KCONFIG_PATH = ROOT / "Kconfig"
CONFIG_PATH = ROOT / ".config"


class KconfigConfigError(RuntimeError):
    pass


def generate_outputs() -> tuple[Path, Path]:
    config = load_installer_config()
    writer = OutputWriter()
    return writer.write_vars_yml(config), writer.write_make_conf(config)


def load_installer_config(config_path: Path = CONFIG_PATH) -> InstallerConfig:
    if not config_path.exists():
        raise KconfigConfigError(
            f"{config_path} does not exist. Run `python3 main.py`, save the menuconfig choices, and exit."
        )

    values = _read_dot_config(config_path)

    disk = DiskConfig(
        target_disk=_string(values, "LGI_TARGET_DISK", "") or None,
        root_partition=_string(values, "LGI_ROOT_PARTITION", "") or None,
        efi_partition=_string(values, "LGI_EFI_PARTITION", "") or None,
        diskmgmt=_string(values, "LGI_DISKMGMT", "manual"),
        partition_scheme="manual" if _enabled(values, "LGI_DISK_MANUAL") else "auto",
        filesystem=_filesystem(values),
        is_uefi=_enabled(values, "LGI_IS_UEFI"),
        boot_mode=_string(values, "LGI_BOOT_MODE", "uefi" if _enabled(values, "LGI_IS_UEFI") else "bios"),
        partition_table=_string(values, "LGI_PARTITION_TABLE", "gpt" if _enabled(values, "LGI_IS_UEFI") else "mbr"),
        layout=_parse_layout(_string(values, "LGI_AUTO_LAYOUT", "")),
    )
    if disk.partition_scheme == "auto":
        disk.notes.append("Automatic partition suggestion requested. No partitioning has been performed.")

    kernel = KernelConfig(
        menuconfig_requested=_enabled(values, "LGI_RUN_KERNEL_MENUCONFIG"),
        use_binary_kernel=_enabled(values, "LGI_KERNEL_USE_BINARY") or not _enabled(values, "LGI_KERNEL_USE_MANUAL"),
        kernel_package=_string(values, "LGI_KERNEL_PACKAGE", "sys-kernel/gentoo-kernel-bin"),
        config_source=_string(values, "LGI_KERNEL_CONFIG_SOURCE", "") or None,
        source_version=_string(values, "LGI_KERNEL_SOURCE_VERSION", "7.0.1"),
        genpatches_version=_string(values, "LGI_KERNEL_GENPATCHES_VERSION", "2"),
        include_experimental_patches=_enabled(values, "LGI_KERNEL_EXPERIMENTAL_PATCHES"),
        saved_config_path=_string(values, "LGI_KERNEL_CONFIG_PATH", "") or None,
    )

    init_system = "systemd" if _enabled(values, "LGI_INIT_SYSTEMD") else "openrc"
    system = SystemConfig(
        hostname=_string(values, "LGI_HOSTNAME", "gentoo"),
        root_password=_string(values, "LGI_ROOT_PASSWORD", "") or None,
        timezone=_string(values, "LGI_TIMEZONE", "UTC"),
        locale=_string(values, "LGI_LOCALE", "en_US.UTF-8 UTF-8"),
        keymap=_string(values, "LGI_KEYMAP", "us"),
        init_system=init_system,
        profile="default/linux/amd64/23.0/systemd" if init_system == "systemd" else "default/linux/amd64/23.0",
        make_opts=_string(values, "LGI_MAKEOPTS", default_make_opts()),
        common_flags=_string(values, "LGI_COMMON_FLAGS", "-O2 -march=native -pipe"),
        video_cards=_string(values, "LGI_VIDEO_CARDS", "intel").split(),
        accept_license=_string(values, "LGI_ACCEPT_LICENSE", "*"),
        grub_platforms=_string(values, "LGI_GRUB_PLATFORMS", "efi-64" if disk.is_uefi else "").split(),
        make_conf_source=_string(values, "LGI_MAKE_CONF_SOURCE", "") or None,
        make_conf_path=_string(values, "LGI_MAKE_CONF_PATH", "") or None,
        network_manager=_string(values, "LGI_NETWORK_MANAGER", "dhcpcd"),
    )

    return InstallerConfig(disk=disk, kernel=kernel, system=system, dry_run=_enabled(values, "LGI_DRY_RUN", default=True))


def _read_dot_config(config_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            _store_config_value(values, key.removeprefix("CONFIG_"), _unquote(value))
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            name = line.removeprefix("# CONFIG_").removesuffix(" is not set")
            _store_config_value(values, name, "n")
    return values


def _store_config_value(values: dict[str, str], name: str, value: str) -> None:
    values[name] = value
    if name.startswith("GHOST_"):
        values.setdefault(f"LGI_{name.removeprefix('GHOST_')}", value)


def _enabled(values: dict[str, str], name: str, *, default: bool = False) -> bool:
    if name not in values:
        return default
    return values.get(name) == "y"


def _string(values: dict[str, str], name: str, default: str) -> str:
    return values.get(name) or default


def _filesystem(values: dict[str, str]) -> str:
    if _enabled(values, "LGI_FS_XFS"):
        return "xfs"
    if _enabled(values, "LGI_FS_BTRFS"):
        return "btrfs"
    return "ext4"


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_layout(value: str) -> list[dict]:
    layout = []
    for row in value.split(";"):
        if not row:
            continue
        name, mountpoint, size, filesystem, flags = (row.split(":") + ["", "", "", "", ""])[:5]
        layout.append(
            {
                "name": name,
                "mountpoint": mountpoint,
                "size": size,
                "filesystem": filesystem,
                "flags": [flag for flag in flags.split(",") if flag],
            }
        )
    return layout
