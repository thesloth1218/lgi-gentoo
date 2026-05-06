from pathlib import Path
import re

from lgi.config import InstallerConfig


class OutputWriter:
    def __init__(self, output_dir: str | Path = "/tmp/lgi-gentoo") -> None:
        self.output_dir = Path(output_dir)

    def write_vars_yml(self, config: InstallerConfig) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "vars.yml"
        path.write_text(_vars_yml(config), encoding="utf-8")
        return path

    def write_make_conf(self, config: InstallerConfig) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "make.conf"
        path.write_text(_make_conf(config), encoding="utf-8")
        return path


def _vars_yml(config: InstallerConfig) -> str:
    disk = config.disk
    kernel = config.kernel
    system = config.system
    return "\n".join(
        [
            "---",
            f"dry_run: {_yaml_bool(config.dry_run)}",
            "disk:",
            f"  diskmgmt: {_yaml_value(disk.diskmgmt)}",
            f"  target_disk: {_yaml_value(disk.target_disk)}",
            f"  root_partition: {_yaml_value(disk.root_partition)}",
            f"  efi_partition: {_yaml_value(disk.efi_partition)}",
            f"  boot_mode: {_yaml_value(disk.boot_mode)}",
            f"  partition_table: {_yaml_value(disk.partition_table)}",
            f"  partition_scheme: {_yaml_value(disk.partition_scheme)}",
            f"  filesystem: {_yaml_value(disk.filesystem)}",
            f"  swap_size: {_yaml_value(disk.swap_size)}",
            f"  bootloader: {_yaml_value(disk.bootloader)}",
            f"  is_uefi: {_yaml_bool(disk.is_uefi)}",
            "  layout:",
            *[_yaml_layout_item(item) for item in disk.layout],
            "  notes:",
            *[f"    - {_yaml_value(note)}" for note in disk.notes],
            "kernel:",
            f"  kernel_package: {_yaml_value(kernel.kernel_package)}",
            f"  use_binary_kernel: {_yaml_bool(kernel.use_binary_kernel)}",
            f"  use_manual_kernel: {_yaml_bool(not kernel.use_binary_kernel)}",
            f"  menuconfig_requested: {_yaml_bool(kernel.menuconfig_requested)}",
            f"  config_source: {_yaml_value(kernel.config_source)}",
            f"  source_version: {_yaml_value(kernel.source_version)}",
            f"  genpatches_version: {_yaml_value(kernel.genpatches_version)}",
            f"  include_experimental_patches: {_yaml_bool(kernel.include_experimental_patches)}",
            f"  saved_config_path: {_yaml_value(kernel.saved_config_path)}",
            "  extra_options:",
            *[f"    - {_yaml_value(option)}" for option in kernel.extra_options],
            "system:",
            f"  hostname: {_yaml_value(system.hostname)}",
            f"  root_password: {_yaml_value(system.root_password)}",
            f"  timezone: {_yaml_value(system.timezone)}",
            f"  locale: {_yaml_value(system.locale)}",
            f"  keymap: {_yaml_value(system.keymap)}",
            f"  init_system: {_yaml_value(system.init_system)}",
            f"  profile: {_yaml_value(system.profile)}",
            f"  stage3_variant: {_yaml_value('systemd' if system.init_system == 'systemd' else 'openrc')}",
            f"  make_opts: {_yaml_value(system.make_opts)}",
            f"  common_flags: {_yaml_value(system.common_flags)}",
            "  video_cards:",
            *[f"    - {_yaml_value(card)}" for card in system.video_cards],
            f"  accept_license: {_yaml_value(system.accept_license)}",
            "  grub_platforms:",
            *[f"    - {_yaml_value(platform)}" for platform in system.grub_platforms],
            f"  make_conf_source: {_yaml_value(system.make_conf_source)}",
            f"  make_conf_path: {_yaml_value(system.make_conf_path)}",
            f"  network_manager: {_yaml_value(system.network_manager)}",
            "",
        ]
    )


def _make_conf(config: InstallerConfig) -> str:
    if config.system.make_conf_path:
        source = Path(config.system.make_conf_path)
        if source.exists():
            return _augment_make_conf(source.read_text(encoding="utf-8"), config)
    return _augment_make_conf(
        "\n".join(
            [
                f'MAKEOPTS="{config.system.make_opts}"',
                f'COMMON_FLAGS="{config.system.common_flags}"',
                'CFLAGS="${COMMON_FLAGS}"',
                'CXXFLAGS="${COMMON_FLAGS}"',
                'FCFLAGS="${COMMON_FLAGS}"',
                'FFLAGS="${COMMON_FLAGS}"',
                f'VIDEO_CARDS="{" ".join(config.system.video_cards)}"',
                "",
            ]
        ),
        config,
    )


def _augment_make_conf(text: str, config: InstallerConfig) -> str:
    lines = text.rstrip().splitlines()
    _ensure_make_conf_var(lines, "ACCEPT_LICENSE", config.system.accept_license)
    grub_platforms = config.system.grub_platforms or (["efi-64"] if config.disk.is_uefi else ["pc"])
    _ensure_make_conf_var(lines, "GRUB_PLATFORMS", " ".join(grub_platforms))
    return "\n".join(lines + [""])


def _ensure_make_conf_var(lines: list[str], name: str, value: str) -> None:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    if any(pattern.match(line) for line in lines):
        return
    lines.append(f'{name}="{value}"')


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def _yaml_value(value: object) -> str:
    if value is None:
        return "null"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_layout_item(item: dict) -> str:
    flags = item.get("flags", [])
    lines = [
        f"    - name: {_yaml_value(item.get('name'))}",
        f"      mountpoint: {_yaml_value(item.get('mountpoint'))}",
        f"      size: {_yaml_value(item.get('size'))}",
        f"      filesystem: {_yaml_value(item.get('filesystem'))}",
    ]
    if flags:
        lines.append("      flags:")
        lines.extend(f"        - {_yaml_value(flag)}" for flag in flags)
    else:
        lines.append("      flags: []")
    return "\n".join(lines)
