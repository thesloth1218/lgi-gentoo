import os
from dataclasses import dataclass, field
from typing import List, Optional


def default_make_opts() -> str:
    if hasattr(os, "sched_getaffinity"):
        try:
            return f"-j{max(1, len(os.sched_getaffinity(0)))}"
        except OSError:
            pass
    return f"-j{max(1, os.cpu_count() or 1)}"


@dataclass
class DiskConfig:
    target_disk: Optional[str] = None
    root_partition: Optional[str] = None
    efi_partition: Optional[str] = None
    diskmgmt: str = "manual"
    partition_table: str = "gpt"
    boot_mode: str = "uefi"
    partition_scheme: str = "manual"
    filesystem: str = "ext4"
    swap_size: str = "4G"
    bootloader: str = "grub"
    is_uefi: bool = False
    layout: List[dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class KernelConfig:
    kernel_package: str = "sys-kernel/gentoo-kernel-bin"
    use_binary_kernel: bool = True
    menuconfig_requested: bool = False
    config_source: Optional[str] = None
    source_version: str = "7.0.1"
    genpatches_version: str = "2"
    include_experimental_patches: bool = False
    saved_config_path: Optional[str] = None
    extra_options: List[str] = field(default_factory=list)


@dataclass
class SystemConfig:
    hostname: str = "gentoo-lgi"
    root_password: Optional[str] = None
    timezone: str = "UTC"
    locale: str = "en_US.UTF-8 UTF-8"
    keymap: str = "us"
    init_system: str = "openrc"
    profile: str = "default/linux/amd64/23.0"
    make_opts: str = field(default_factory=default_make_opts)
    common_flags: str = "-O2 -march=native -pipe"
    video_cards: List[str] = field(default_factory=lambda: ["intel"])
    accept_license: str = "*"
    grub_platforms: List[str] = field(default_factory=list)
    make_conf_source: Optional[str] = None
    make_conf_path: Optional[str] = None
    network_manager: str = "dhcpcd"


@dataclass
class InstallerConfig:
    disk: DiskConfig = field(default_factory=DiskConfig)
    kernel: KernelConfig = field(default_factory=KernelConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    dry_run: bool = True
