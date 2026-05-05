import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from lgi.ansible_runner import AnsibleRunnerError, run_outside_playbook
from lgi.config import DiskConfig, InstallerConfig, KernelConfig, SystemConfig
from lgi.kconfig_runner import CONFIG_PATH, generate_outputs
from lgi.system.inspect import SystemInspector


class DialogError(RuntimeError):
    pass


class DialogCancelled(RuntimeError):
    pass


class DialogInstaller:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        is_uefi = SystemInspector().is_uefi()
        self.config = InstallerConfig(
            disk=DiskConfig(
                diskmgmt="manual",
                partition_scheme="manual",
                filesystem="ext4",
                is_uefi=is_uefi,
                boot_mode="uefi" if is_uefi else "bios",
                partition_table="gpt" if is_uefi else "mbr",
            ),
            kernel=KernelConfig(menuconfig_requested=False),
            system=SystemConfig(
                hostname="gentoo",
                timezone="UTC",
                locale="en_US.UTF-8 UTF-8",
                grub_platforms=["efi-64"] if is_uefi else [],
            ),
            dry_run=True,
        )

    def run(self) -> tuple[Path, Path]:
        _require_dialog()
        while True:
            action = self._main_menu()
            if action == "disk":
                self._disk_menu()
            elif action == "filesystem":
                self._filesystem_menu()
            elif action == "init":
                self._init_menu()
            elif action == "system":
                self._system_form()
            elif action == "makeconf":
                self._make_conf_menu()
            elif action == "kernel":
                self._kernel_menu()
            elif action == "review":
                self._review()
            elif action == "dryrun":
                self.config.dry_run = not self.config.dry_run
            elif action == "install":
                result = self._confirm_and_install()
                if result:
                    return result
            elif action == "quit":
                raise DialogCancelled("Installer exited without saving.")

    def write_config(self) -> Path:
        self.config_path.write_text(_config_text(self.config), encoding="utf-8")
        return self.config_path

    def _main_menu(self) -> str:
        return _dialog(
            [
                "--title",
                "Larry's Gentoo Installer",
                "--cancel-label",
                "Quit",
                "--menu",
                "Configure the installer. Destructive steps are dry-run by default.",
                "20",
                "76",
                "11",
                "disk",
                "Disk setup mode",
                "filesystem",
                "Filesystem",
                "init",
                "Init system",
                "system",
                "System basics, root password, locale/time",
                "makeconf",
                "make.conf flags and VIDEO_CARDS",
                "kernel",
                "Kernel options",
                "review",
                "Review current selections",
                "install",
                "Review, save, and run install",
                "dryrun",
                "[*] Dry-run mode" if self.config.dry_run else "[ ] Dry-run mode",
                "quit",
                "Quit without saving",
            ],
            cancel_value="quit",
        )

    def _disk_menu(self) -> None:
        value = _dialog(
            [
                "--title",
                "Disk setup mode",
                "--radiolist",
                "Choose how disk setup should be handled.",
                "14",
                "72",
                "2",
                "manual",
                "Manual partitioning with cfdisk",
                _on(self.config.disk.partition_scheme == "manual"),
                "auto",
                "Automatic partition suggestion",
                _on(self.config.disk.partition_scheme == "auto"),
            ],
            cancel_value="",
        )
        if not value:
            return
        self.config.disk.partition_scheme = value
        self.config.disk.diskmgmt = value
        self.config.disk.boot_mode = "uefi" if self.config.disk.is_uefi else "bios"
        self.config.disk.partition_table = "gpt" if self.config.disk.is_uefi else "mbr"
        self.config.disk.notes = []
        self.config.disk.layout = []
        if value == "auto":
            self.config.disk.notes.append(
                "Automatic partitioning selected. Choose Filesystem next to set the disk and partition targets."
            )
        else:
            self.config.disk.notes.append(
                "Manual partitioning selected. Choose Filesystem next to open cfdisk and set partition targets."
            )

    def _target_disk_form(self, prompt: str | None = None) -> bool:
        target = _dialog(
            [
                "--title",
                "Target disk",
                "--inputbox",
                prompt or "Enter the target disk, e.g. /dev/sda or /dev/nvme0n1:",
                "9",
                "78",
                self.config.disk.target_disk or "",
            ],
            cancel_value="",
        )
        if target:
            self.config.disk.target_disk = target.strip()
            return True
        return False

    def _validate_target_disk_path(self) -> bool:
        target = self.config.disk.target_disk
        if not target:
            return False
        if not target.startswith("/dev/"):
            _dialog_msgbox(
                "Invalid target disk",
                "The target disk must be an absolute /dev path, for example /dev/sda or /dev/nvme0n1.",
                height="8",
                width="76",
            )
            self.config.disk.target_disk = None
            return False
        if not _is_block_device(Path(target)):
            _dialog_msgbox(
                "Invalid target disk",
                f"{target} is not a block device visible from the live environment.",
                height="8",
                width="76",
            )
            self.config.disk.target_disk = None
            return False
        return True

    def _manual_disk_setup(self) -> None:
        if not self.config.disk.target_disk:
            return
        if shutil.which("cfdisk") is None:
            _dialog_msgbox("cfdisk missing", "cfdisk was not found in this live environment.", height="8", width="68")
            return
        warning = (
            "LGI will leave the TUI and start cfdisk for manual partitioning.\n\n"
            f"Target disk: {self.config.disk.target_disk}\n\n"
            "cfdisk only writes changes after you choose Write inside cfdisk."
        )
        if not _dialog_yesno("Manual partitioning", warning, default_yes=False):
            return
        subprocess.run(["clear"], check=False)
        completed = subprocess.run(["cfdisk", self.config.disk.target_disk], check=False)
        input(f"\ncfdisk exited with status {completed.returncode}. Press Enter to return to LGI.")
        layout_text, partitions = _partition_layout_text(self.config.disk.target_disk)
        _dialog_textbox("Current partition layout", layout_text, height="22", width="90")
        self._apply_partition_suggestions(partitions)
        if self.config.disk.is_uefi and not _has_efi_system_partition(partitions):
            reopen = _dialog_yesno(
                "EFI system partition not found",
                "UEFI boot is detected, but lsblk did not report an EFI System Partition on this disk.\n\n"
                "Recommended: reopen cfdisk and create a FAT32 EFI System Partition.\n\n"
                "Reopen cfdisk now?",
                default_yes=True,
            )
            if reopen:
                self._manual_disk_setup()
                return
        self._partition_mapping_form(hypothetical=False)

    def _apply_partition_suggestions(self, partitions: list[dict]) -> None:
        root_candidates = [part for part in partitions if part.get("type") == "part" and not _is_efi_partition_info(part)]
        efi_candidates = [part for part in partitions if _is_efi_partition_info(part)]
        if not self.config.disk.root_partition and root_candidates:
            self.config.disk.root_partition = root_candidates[-1].get("path")
        if self.config.disk.is_uefi and not self.config.disk.efi_partition and efi_candidates:
            self.config.disk.efi_partition = efi_candidates[0].get("path")

    def _partition_mapping_form(self, *, hypothetical: bool) -> None:
        title = "Partition targets"
        if hypothetical:
            prompt = "These targets are based on the selected disk and will exist after automatic partitioning. Edit if needed."
        else:
            prompt = "Set the partitions LGI should format and mount during install."
        fields = [
            "--title",
            title,
            "--form",
            prompt,
            "13",
            "82",
            "3",
            "Root (/):",
            "1",
            "1",
            self.config.disk.root_partition or "",
            "1",
            "16",
            "42",
            "128",
        ]
        if self.config.disk.is_uefi:
            fields.extend(
                [
                    "EFI (/efi):",
                    "2",
                    "1",
                    self.config.disk.efi_partition or "",
                    "2",
                    "16",
                    "42",
                    "128",
                ]
            )
        output = _dialog(fields, cancel_value="")
        if not output:
            return
        values = output.splitlines()
        if values:
            self.config.disk.root_partition = values[0] or self.config.disk.root_partition
        if self.config.disk.is_uefi and len(values) > 1:
            self.config.disk.efi_partition = values[1] or self.config.disk.efi_partition

    def _filesystem_menu(self) -> None:
        current = self.config.disk.filesystem
        value = _dialog(
            [
                "--title",
                "Filesystem",
                "--radiolist",
                "Choose the target root filesystem.",
                "15",
                "72",
                "3",
                "ext4",
                "ext4",
                _on(current == "ext4"),
                "xfs",
                "xfs",
                _on(current == "xfs"),
                "btrfs",
                "btrfs",
                _on(current == "btrfs"),
            ],
            cancel_value="",
        )
        if not value:
            return
        self.config.disk.filesystem = value
        self._configure_partition_targets_after_filesystem()

    def _configure_partition_targets_after_filesystem(self) -> None:
        if self.config.disk.diskmgmt == "auto":
            if not self.config.disk.target_disk:
                self._target_disk_form("Enter the target disk for automatic partitioning, e.g. /dev/sda or /dev/nvme0n1:")
            if not self._validate_target_disk_path():
                return
            self._refresh_auto_partition_defaults()
            self.config.disk.layout = _recommended_disk_layout(self.config.disk)
            self._partition_mapping_form(hypothetical=True)
        else:
            if not self.config.disk.target_disk:
                self._target_disk_form("Enter the disk to partition manually with cfdisk, e.g. /dev/sda or /dev/nvme0n1:")
            if not self._validate_target_disk_path():
                return
            self._manual_disk_setup()

    def _refresh_auto_partition_defaults(self) -> None:
        root_partition, efi_partition = _default_install_partitions(self.config.disk)
        if not self.config.disk.root_partition:
            self.config.disk.root_partition = root_partition
        if self.config.disk.is_uefi:
            if not self.config.disk.efi_partition:
                self.config.disk.efi_partition = efi_partition
        else:
            self.config.disk.efi_partition = None

    def _init_menu(self) -> None:
        current = self.config.system.init_system
        value = _dialog(
            [
                "--title",
                "Init system",
                "--radiolist",
                "Choose the init system.",
                "14",
                "72",
                "2",
                "openrc",
                "OpenRC",
                _on(current == "openrc"),
                "systemd",
                "systemd",
                _on(current == "systemd"),
            ],
            cancel_value="",
        )
        if not value:
            return
        self.config.system.init_system = value
        self.config.system.profile = "default/linux/amd64/23.0/systemd" if value == "systemd" else "default/linux/amd64/23.0"

    def _system_form(self) -> None:
        output = _dialog(
            [
                "--title",
                "System basics",
                "--form",
                "Edit basic system settings.",
                "18",
                "76",
                "5",
                "Hostname:",
                "1",
                "1",
                self.config.system.hostname,
                "1",
                "18",
                "40",
                "128",
                "Timezone:",
                "2",
                "1",
                self.config.system.timezone,
                "2",
                "18",
                "40",
                "128",
                "Locale:",
                "3",
                "1",
                self.config.system.locale,
                "3",
                "18",
                "40",
                "128",
                "Keymap:",
                "4",
                "1",
                self.config.system.keymap,
                "4",
                "18",
                "40",
                "128",
            ],
            cancel_value="",
        )
        if not output:
            return
        values = output.splitlines()
        if len(values) >= 4:
            self.config.system.hostname = values[0] or self.config.system.hostname
            self.config.system.timezone = values[1] or self.config.system.timezone
            self.config.system.locale = values[2] or self.config.system.locale
            self.config.system.keymap = values[3] or self.config.system.keymap
        self._root_password_form()

    def _root_password_form(self) -> None:
        password = _dialog_password("Root password", "Enter the target system root password:")
        if not password:
            return
        confirm = _dialog_password("Root password", "Confirm the target system root password:")
        if password != confirm:
            _dialog_msgbox("Root password", "Passwords did not match. Root password was not changed.", height="8", width="68")
            return
        self.config.system.root_password = password

    def _make_conf_menu(self) -> None:
        while True:
            import_label = (
                "[*] Use imported make.conf"
                if self.config.system.make_conf_path
                else "[ ] Use imported make.conf"
            )
            action = _dialog(
                [
                    "--title",
                    "make.conf",
                    "--cancel-label",
                    "Back",
                    "--menu",
                    "Configure generated make.conf or import a premade file.",
                    "18",
                    "76",
                    "5",
                    "flags",
                    "COMMON_FLAGS, MAKEOPTS, VIDEO_CARDS",
                    "import",
                    import_label,
                    "clear",
                    "Clear imported make.conf",
                    "back",
                    "Back",
                ],
                cancel_value="back",
            )
            if action == "flags":
                self._make_conf_form()
            elif action == "import":
                self._import_make_conf()
            elif action == "clear":
                self.config.system.make_conf_source = None
                self.config.system.make_conf_path = None
            else:
                return

    def _make_conf_form(self) -> None:
        output = _dialog(
            [
                "--title",
                "make.conf flags",
                "--form",
                "Defaults are conservative for a native Gentoo install.",
                "16",
                "78",
                "4",
                "COMMON_FLAGS:",
                "1",
                "1",
                self.config.system.common_flags,
                "1",
                "20",
                "48",
                "160",
                "MAKEOPTS:",
                "2",
                "1",
                self.config.system.make_opts,
                "2",
                "20",
                "48",
                "80",
                "VIDEO_CARDS:",
                "3",
                "1",
                " ".join(self.config.system.video_cards),
                "3",
                "20",
                "48",
                "160",
            ],
            cancel_value="",
        )
        if not output:
            return
        values = output.splitlines()
        if len(values) >= 3:
            self.config.system.common_flags = values[0] or self.config.system.common_flags
            self.config.system.make_opts = values[1] or self.config.system.make_opts
            self.config.system.video_cards = (values[2] or " ".join(self.config.system.video_cards)).split()

    def _import_make_conf(self) -> None:
        source_text = _dialog(
            [
                "--title",
                "Import make.conf",
                "--inputbox",
                "Enter a local path or http(s) URL for a premade make.conf:",
                "9",
                "72",
                self.config.system.make_conf_source or self.config.system.make_conf_path or "",
            ],
            cancel_value="",
        )
        if not source_text:
            return
        destination = Path("/tmp/lgi-gentoo/make.conf")
        try:
            _fetch_text_file(source_text, destination)
            _validate_make_conf(destination)
        except DialogError as exc:
            _dialog_msgbox("Import failed", str(exc), height="12", width="76")
            return
        self.config.system.make_conf_source = source_text
        self.config.system.make_conf_path = str(destination)
        _dialog_msgbox("make.conf imported", f"Copied make.conf to:\n{destination}", height="8", width="72")

    def _kernel_menu(self) -> None:
        while True:
            imported_label = (
                "[*] Use imported kernel .config"
                if self.config.kernel.saved_config_path
                else "[ ] Use imported kernel .config"
            )
            binary_label = (
                "[*] Use gentoo-kernel-bin"
                if self.config.kernel.use_binary_kernel
                else "[ ] Use gentoo-kernel-bin"
            )
            action = _dialog(
                [
                    "--title",
                    "Kernel options",
                    "--cancel-label",
                    "Back",
                    "--menu",
                    "Choose a binary kernel or provide a premade kernel .config.",
                    "18",
                    "76",
                    "4",
                    "binary",
                    binary_label,
                    "import",
                    imported_label,
                    "clear",
                    "Clear imported kernel .config",
                    "back",
                    "Back",
                ],
                cancel_value="back",
            )
            if action == "binary":
                self._use_binary_kernel()
            elif action == "import":
                self._import_kernel_config()
            elif action == "clear":
                self._use_binary_kernel()
            else:
                return

    def _kernel_settings_form(self) -> None:
        output = _dialog(
            [
                "--title",
                "Gentoo kernel source settings",
                "--form",
                "Use Gentoo genpatches tarballs plus the matching upstream Linux tarball.",
                "17",
                "78",
                "4",
                "Kernel version:",
                "1",
                "1",
                self.config.kernel.source_version,
                "1",
                "22",
                "24",
                "32",
                "Genpatches rev:",
                "2",
                "1",
                self.config.kernel.genpatches_version,
                "2",
                "22",
                "24",
                "16",
            ],
            cancel_value="",
        )
        if not output:
            return
        values = output.splitlines()
        if len(values) >= 2:
            self.config.kernel.source_version = values[0] or self.config.kernel.source_version
            self.config.kernel.genpatches_version = values[1] or self.config.kernel.genpatches_version
        self.config.kernel.include_experimental_patches = _dialog_yesno(
            "Gentoo kernel source settings",
            "Include Gentoo experimental genpatches too?",
            default_yes=self.config.kernel.include_experimental_patches,
        )

    def _import_kernel_config(self) -> None:
        source_text = _dialog(
            [
                "--title",
                "Import kernel .config",
                "--inputbox",
                "Enter a local path or http(s) URL for an existing kernel .config:",
                "9",
                "72",
                self.config.kernel.config_source or self.config.kernel.saved_config_path or "",
            ],
            cancel_value="",
        )
        if not source_text:
            return
        destination = Path("/tmp/lgi-gentoo/kernel.config")
        try:
            _fetch_kernel_config(source_text, destination)
            _validate_kernel_config(destination)
        except DialogError as exc:
            _dialog_msgbox("Import failed", str(exc), height="12", width="76")
            return
        self.config.kernel.config_source = source_text
        self.config.kernel.saved_config_path = str(destination)
        self.config.kernel.menuconfig_requested = False
        self.config.kernel.use_binary_kernel = False
        self.config.kernel.kernel_package = "sys-kernel/gentoo-sources"
        _dialog_msgbox(
            "Kernel .config imported",
            f"Copied kernel config to:\n{destination}\n\nKernel menuconfig during install has been disabled.",
            height="10",
            width="72",
        )

    def _use_binary_kernel(self) -> None:
        self.config.kernel.use_binary_kernel = True
        self.config.kernel.kernel_package = "sys-kernel/gentoo-kernel-bin"
        self.config.kernel.menuconfig_requested = False
        self.config.kernel.config_source = None
        self.config.kernel.saved_config_path = None

    def _review(self) -> None:
        _dialog_msgbox("Review current selections", _review_text(self.config), height="22", width="78")
        while True:
            action = _dialog(
                [
                    "--title",
                    "Review actions",
                    "--cancel-label",
                    "Back",
                    "--menu",
                    "Make final disk target changes before install.",
                    "13",
                    "72",
                    "4",
                    "targets",
                    "Edit root and EFI partition targets",
                    "disk",
                    "Change target disk",
                    "cfdisk",
                    "Reopen cfdisk for manual mode",
                    "back",
                    "Back",
                ],
                cancel_value="back",
            )
            if action == "targets":
                self._partition_mapping_form(hypothetical=self.config.disk.diskmgmt == "auto")
            elif action == "disk":
                self._target_disk_form()
                if self.config.disk.diskmgmt == "auto":
                    self.config.disk.root_partition = None
                    self.config.disk.efi_partition = None
                    self._refresh_auto_partition_defaults()
                    self.config.disk.layout = _recommended_disk_layout(self.config.disk)
                    self._partition_mapping_form(hypothetical=True)
            elif action == "cfdisk" and self.config.disk.diskmgmt == "manual":
                self._manual_disk_setup()
            else:
                return

    def _confirm_and_install(self) -> tuple[Path, Path] | None:
        errors = self._validation_errors()
        if errors:
            _dialog_msgbox("Validation failed", "\n".join(errors), height="16", width="78")
            return None
        self.write_config()
        vars_path, make_path = generate_outputs()
        _dialog_msgbox("Final review", _review_text(self.config), height="24", width="80")

        warning_target = self.config.disk.target_disk or "(manual/pre-mounted disk)"
        if not self._confirm_install_warning(warning_target):
            return None

        subprocess.run(["clear"], check=False)
        print("LGI is running the outside Ansible playbook.")
        print(f"vars: {vars_path}")
        print(f"make.conf: {make_path}")
        print()
        try:
            returncode = run_outside_playbook()
        except AnsibleRunnerError as exc:
            _dialog_msgbox("Ansible failed to start", str(exc), height="10", width="76")
            return vars_path, make_path

        if returncode == 0:
            _dialog_msgbox("Install phase complete", "Ansible outside playbook completed successfully.", height="8", width="70")
        else:
            _dialog_msgbox(
                "Install phase failed",
                f"Ansible outside playbook exited with status {returncode}.\nReview the terminal output above.",
                height="9",
                width="76",
            )
        return vars_path, make_path

    def _confirm_install_warning(self, warning_target: str) -> bool:
        if not self.config.dry_run and self.config.disk.diskmgmt == "auto":
            warning = (
                "DESTRUCTIVE INSTALL WARNING\n\n"
                "Dry-run mode is OFF and automatic disk management is selected.\n\n"
                f"LGI will partition and format: {warning_target}\n\n"
                "ALL EXISTING DATA ON THAT DISK WILL BE DESTROYED.\n\n"
                "To continue, type the exact target disk path."
            )
            typed = _dialog(
                [
                    "--title",
                    "Destructive disk confirmation",
                    "--inputbox",
                    warning,
                    "15",
                    "78",
                    "",
                ],
                cancel_value="",
            )
            if typed != warning_target:
                _dialog_msgbox(
                    "Install cancelled",
                    "The typed disk path did not match. No install actions were started.",
                    height="8",
                    width="72",
                )
                return False
            return _dialog_yesno(
                "Final destructive confirmation",
                f"Last confirmation:\n\nPartition and format {warning_target} now?",
                default_yes=False,
            )

        warning = (
            "LGI is about to leave the TUI and run the outside Ansible playbook.\n\n"
            f"Disk mode: {self.config.disk.diskmgmt}\n"
            f"Target disk: {warning_target}\n"
            f"Dry-run: {self.config.dry_run}\n\n"
            "Dry-run mode skips destructive tasks. If dry-run is off, review the config carefully before continuing."
        )
        return _dialog_yesno("Install warning", warning, default_yes=False)

    def _validation_errors(self) -> list[str]:
        errors = []
        hostname = self.config.system.hostname.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", hostname):
            errors.append("Hostname must be 1-63 chars and contain only letters, numbers, and hyphens.")
        if not self.config.system.timezone.strip():
            errors.append("Timezone cannot be empty.")
        if not self.config.system.locale.strip():
            errors.append("Locale cannot be empty.")
        if not self.config.system.keymap.strip():
            errors.append("Keymap cannot be empty.")
        if not re.fullmatch(r"-j[1-9][0-9]*", self.config.system.make_opts.strip()):
            errors.append("MAKEOPTS must look like -jN, for example -j8.")
        if not self.config.system.video_cards:
            errors.append("At least one VIDEO_CARDS value is required.")
        if not self.config.dry_run and not self.config.system.root_password:
            errors.append("Root password is required before running a real install.")
        if self.config.disk.diskmgmt == "auto":
            target = self.config.disk.target_disk
            if not target:
                errors.append("Automatic disk management requires a target disk.")
            elif not target.startswith("/dev/"):
                errors.append("Target disk must be an absolute /dev path.")
            elif not self.config.dry_run and not _is_block_device(Path(target)):
                errors.append(f"Target disk is not a block device: {target}")
        if not self.config.disk.root_partition:
            errors.append("Root partition is required.")
        elif not self.config.disk.root_partition.startswith("/dev/"):
            errors.append("Root partition must be an absolute /dev path.")
        elif not self.config.dry_run and self.config.disk.diskmgmt == "manual" and not _is_block_device(Path(self.config.disk.root_partition)):
            errors.append(f"Root partition is not a block device: {self.config.disk.root_partition}")
        if self.config.disk.is_uefi:
            if not self.config.disk.efi_partition:
                errors.append("UEFI installs require an EFI partition mounted at /efi.")
            elif not self.config.disk.efi_partition.startswith("/dev/"):
                errors.append("EFI partition must be an absolute /dev path.")
            elif not self.config.dry_run and self.config.disk.diskmgmt == "manual" and not _is_block_device(Path(self.config.disk.efi_partition)):
                errors.append(f"EFI partition is not a block device: {self.config.disk.efi_partition}")
            if self.config.disk.diskmgmt == "manual" and not self.config.dry_run and self.config.disk.target_disk:
                _layout_text, partitions = _partition_layout_text(self.config.disk.target_disk)
                if partitions and not _has_efi_system_partition(partitions):
                    errors.append("UEFI manual disk mode did not detect an EFI System Partition on the selected disk.")
        if self.config.system.make_conf_path and not Path(self.config.system.make_conf_path).exists():
            errors.append(f"Imported make.conf no longer exists: {self.config.system.make_conf_path}")
        if self.config.kernel.saved_config_path and not Path(self.config.kernel.saved_config_path).exists():
            errors.append(f"Imported kernel .config no longer exists: {self.config.kernel.saved_config_path}")
        if not self.config.kernel.use_binary_kernel and not self.config.kernel.saved_config_path:
            errors.append("Manual kernel mode requires an imported kernel .config.")
        return errors


def run_dialog_installer() -> tuple[Path, Path]:
    return DialogInstaller().run()


def _dialog(args: list[str], *, cancel_value: str | None = None) -> str:
    command = ["dialog", "--clear", "--stdout", *args]
    result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE)
    if result.returncode == 0:
        return result.stdout.strip()
    if cancel_value is not None and result.returncode in (1, 255):
        return cancel_value
    raise DialogCancelled("Dialog was cancelled.")


def _dialog_yesno(title: str, text: str, *, default_yes: bool = True) -> bool:
    args = ["--title", title]
    if not default_yes:
        args.append("--defaultno")
    args.extend(["--yesno", text, "8", "60"])
    result = subprocess.run(["dialog", "--clear", *args], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise DialogCancelled("Dialog was cancelled.")


def _dialog_password(title: str, text: str) -> str:
    return _dialog(["--title", title, "--insecure", "--passwordbox", text, "9", "72"], cancel_value="")


def _dialog_msgbox(title: str, text: str, *, height: str = "12", width: str = "70") -> None:
    subprocess.run(["dialog", "--clear", "--title", title, "--msgbox", text, height, width], check=False)


def _dialog_textbox(title: str, text: str, *, height: str = "20", width: str = "86") -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        subprocess.run(["dialog", "--clear", "--title", title, "--textbox", path, height, width], check=False)
    finally:
        Path(path).unlink(missing_ok=True)


def _require_dialog() -> None:
    if shutil.which("dialog") is None:
        raise DialogError("Missing system dependency: dialog. Install the dialog package and run `python3 main.py` again.")


def _config_text(config: InstallerConfig) -> str:
    lines = [
        "",
        "#",
        "# Larry's Gentoo Installer",
        "#",
        _bool_symbol("LGI_DISK_MANUAL", config.disk.partition_scheme == "manual"),
        _bool_symbol("LGI_DRY_RUN", config.dry_run),
        _bool_symbol("LGI_DISK_AUTO", config.disk.partition_scheme == "auto"),
        _bool_symbol("LGI_IS_UEFI", config.disk.is_uefi),
        f'CONFIG_LGI_DISKMGMT="{_escape(config.disk.diskmgmt)}"',
        f'CONFIG_LGI_TARGET_DISK="{_escape(config.disk.target_disk or "")}"',
        f'CONFIG_LGI_ROOT_PARTITION="{_escape(config.disk.root_partition or "")}"',
        f'CONFIG_LGI_EFI_PARTITION="{_escape(config.disk.efi_partition or "")}"',
        f'CONFIG_LGI_BOOT_MODE="{_escape(config.disk.boot_mode)}"',
        f'CONFIG_LGI_PARTITION_TABLE="{_escape(config.disk.partition_table)}"',
        f'CONFIG_LGI_AUTO_LAYOUT="{_escape(_layout_config_value(config.disk.layout))}"',
        _bool_symbol("LGI_FS_EXT4", config.disk.filesystem == "ext4"),
        _bool_symbol("LGI_FS_XFS", config.disk.filesystem == "xfs"),
        _bool_symbol("LGI_FS_BTRFS", config.disk.filesystem == "btrfs"),
        _bool_symbol("LGI_INIT_OPENRC", config.system.init_system == "openrc"),
        _bool_symbol("LGI_INIT_SYSTEMD", config.system.init_system == "systemd"),
        f'CONFIG_LGI_HOSTNAME="{_escape(config.system.hostname)}"',
        f'CONFIG_LGI_ROOT_PASSWORD="{_escape(config.system.root_password or "")}"',
        f'CONFIG_LGI_TIMEZONE="{_escape(config.system.timezone)}"',
        f'CONFIG_LGI_LOCALE="{_escape(config.system.locale)}"',
        f'CONFIG_LGI_KEYMAP="{_escape(config.system.keymap)}"',
        f'CONFIG_LGI_NETWORK_MANAGER="{_escape(config.system.network_manager)}"',
        f'CONFIG_LGI_COMMON_FLAGS="{_escape(config.system.common_flags)}"',
        f'CONFIG_LGI_MAKEOPTS="{_escape(config.system.make_opts)}"',
        f'CONFIG_LGI_VIDEO_CARDS="{_escape(" ".join(config.system.video_cards))}"',
        f'CONFIG_LGI_ACCEPT_LICENSE="{_escape(config.system.accept_license)}"',
        f'CONFIG_LGI_GRUB_PLATFORMS="{_escape(" ".join(config.system.grub_platforms))}"',
        f'CONFIG_LGI_MAKE_CONF_SOURCE="{_escape(config.system.make_conf_source or "")}"',
        f'CONFIG_LGI_MAKE_CONF_PATH="{_escape(config.system.make_conf_path or "")}"',
        _bool_symbol("LGI_RUN_KERNEL_MENUCONFIG", config.kernel.menuconfig_requested),
        _bool_symbol("LGI_KERNEL_USE_BINARY", config.kernel.use_binary_kernel),
        _bool_symbol("LGI_KERNEL_USE_MANUAL", not config.kernel.use_binary_kernel),
        f'CONFIG_LGI_KERNEL_PACKAGE="{_escape(config.kernel.kernel_package)}"',
        f'CONFIG_LGI_KERNEL_CONFIG_SOURCE="{_escape(config.kernel.config_source or "")}"',
        f'CONFIG_LGI_KERNEL_SOURCE_VERSION="{_escape(config.kernel.source_version)}"',
        f'CONFIG_LGI_KERNEL_GENPATCHES_VERSION="{_escape(config.kernel.genpatches_version)}"',
        _bool_symbol("LGI_KERNEL_EXPERIMENTAL_PATCHES", config.kernel.include_experimental_patches),
        f'CONFIG_LGI_KERNEL_CONFIG_PATH="{_escape(config.kernel.saved_config_path or "")}"',
        "# end of Larry's Gentoo Installer",
        "",
    ]
    return "\n".join(lines)


def _bool_symbol(name: str, enabled: bool) -> str:
    if enabled:
        return f"CONFIG_{name}=y"
    return f"# CONFIG_{name} is not set"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _fetch_kernel_config(source: str, destination: Path) -> None:
    _fetch_text_file(source, destination)


def _fetch_text_file(source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "https://")):
        _download_url(source, destination)
        return

    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise DialogError(f"File does not exist:\n{source_path}")
    shutil.copy2(source_path, destination)


def _download_url(source: str, destination: Path) -> None:
    if shutil.which("wget"):
        result = subprocess.run(["wget", "-O", str(destination), source], check=False)
        if result.returncode == 0:
            return
        raise DialogError(f"wget could not download:\n{source}")
    if shutil.which("curl"):
        result = subprocess.run(["curl", "-L", "-f", "-o", str(destination), source], check=False)
        if result.returncode == 0:
            return
        raise DialogError(f"curl could not download:\n{source}")
    try:
        urllib.request.urlretrieve(source, destination)
    except Exception as exc:
        raise DialogError(f"Could not download file:\n{source}\n\n{exc}") from exc


def _validate_kernel_config(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DialogError(f"Could not read imported config:\n{path}\n\n{exc}") from exc
    if "CONFIG_" not in text:
        raise DialogError("Imported file does not look like a Linux kernel .config; no CONFIG_ entries were found.")


def _validate_make_conf(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DialogError(f"Could not read imported make.conf:\n{path}\n\n{exc}") from exc
    if "=" not in text:
        raise DialogError("Imported file does not look like make.conf; no assignments were found.")


def _is_block_device(path: Path) -> bool:
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def _default_install_partitions(disk: DiskConfig) -> tuple[str | None, str | None]:
    if not disk.target_disk:
        return None, None
    separator = "p" if disk.target_disk[-1:].isdigit() else ""
    if disk.is_uefi:
        return f"{disk.target_disk}{separator}2", f"{disk.target_disk}{separator}1"
    return f"{disk.target_disk}{separator}1", None


def _partition_layout_text(target_disk: str | None) -> tuple[str, list[dict]]:
    columns = "NAME,PATH,SIZE,TYPE,FSTYPE,PARTTYPENAME,PARTTYPE,MOUNTPOINT"
    args = ["lsblk", "-o", columns]
    if target_disk:
        args.append(target_disk)
    text_result = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    json_args = ["lsblk", "-J", "-o", columns]
    if target_disk:
        json_args.append(target_disk)
    json_result = subprocess.run(json_args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    partitions: list[dict] = []
    if json_result.returncode == 0 and json_result.stdout:
        try:
            import json

            data = json.loads(json_result.stdout)
            partitions = _flatten_partitions(data.get("blockdevices", []))
        except Exception:
            partitions = []
    output = text_result.stdout if text_result.stdout else "Could not read partition layout with lsblk."
    return output, partitions


def _flatten_partitions(devices: list[dict]) -> list[dict]:
    rows = []
    for device in devices:
        if device.get("type") == "part":
            rows.append(device)
        rows.extend(_flatten_partitions(device.get("children", []) or []))
    return rows


def _has_efi_system_partition(partitions: list[dict]) -> bool:
    return any(_is_efi_partition_info(partition) for partition in partitions)


def _is_efi_partition_info(partition: dict) -> bool:
    values = " ".join(
        str(partition.get(key, "") or "").lower()
        for key in ("parttypename", "parttype", "partflags", "fstype")
    )
    return (
        "efi system" in values
        or "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" in values
        or "esp" in values
    )


def _recommended_disk_layout(disk: DiskConfig) -> list[dict]:
    if disk.is_uefi:
        return [
            {"name": "efi", "mountpoint": "/efi", "size": "512M", "filesystem": "vfat", "flags": ["esp"]},
            {"name": "root", "mountpoint": "/", "size": "100%", "filesystem": disk.filesystem, "flags": []},
        ]
    return [
        {"name": "root", "mountpoint": "/", "size": "100%", "filesystem": disk.filesystem, "flags": ["boot"]},
    ]


def _layout_config_value(layout: list[dict]) -> str:
    rows = []
    for item in layout:
        rows.append(
            ":".join(
                [
                    str(item.get("name", "")),
                    str(item.get("mountpoint", "")),
                    str(item.get("size", "")),
                    str(item.get("filesystem", "")),
                    ",".join(item.get("flags", [])),
                ]
            )
        )
    return ";".join(rows)


def _on(value: bool) -> str:
    return "on" if value else "off"


def _review_text(config: InstallerConfig) -> str:
    return "\n".join(
        [
            f"Disk setup mode: {config.disk.partition_scheme}",
            f"Dry-run mode: {'yes' if config.dry_run else 'no'}",
            f"Target disk: {config.disk.target_disk or '(manual/pre-mounted)'}",
            f"Root partition: {config.disk.root_partition or '(not set)'}",
            f"EFI partition: {config.disk.efi_partition or '(not set)'}",
            f"UEFI detected: {'yes' if config.disk.is_uefi else 'no'}",
            f"Boot mode: {config.disk.boot_mode}",
            f"Partition table: {config.disk.partition_table}",
            f"Filesystem: {config.disk.filesystem}",
            "Auto layout:",
            *[f"  {part['name']} {part['size']} {part['filesystem']} {part['mountpoint']}" for part in config.disk.layout],
            f"Init system: {config.system.init_system}",
            f"Hostname: {config.system.hostname}",
            f"Root password set: {'yes' if config.system.root_password else 'no'}",
            f"Timezone: {config.system.timezone}",
            f"Locale: {config.system.locale}",
            f"Keymap: {config.system.keymap}",
            f"Network manager: {config.system.network_manager}",
            f"COMMON_FLAGS: {config.system.common_flags}",
            f"MAKEOPTS: {config.system.make_opts}",
            f"VIDEO_CARDS: {' '.join(config.system.video_cards)}",
            f"ACCEPT_LICENSE: {config.system.accept_license}",
            f"GRUB_PLATFORMS: {' '.join(config.system.grub_platforms) or '(none)'}",
            f"Imported make.conf: {config.system.make_conf_path or '(none)'}",
            f"Kernel package: {config.kernel.kernel_package}",
            f"Use binary kernel: {'yes' if config.kernel.use_binary_kernel else 'no'}",
            f"Kernel config source: {config.kernel.config_source or '(none)'}",
            f"Saved kernel config: {config.kernel.saved_config_path or '(not generated yet)'}",
            "",
            "Install writes .config, vars.yml, and make.conf before running Ansible.",
        ]
    )
