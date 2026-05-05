import json
from pathlib import Path
from typing import Any

from lgi.system.commands import CommandRunner


class SystemInspector:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def is_uefi(self) -> bool:
        return Path("/sys/firmware/efi").exists()

    def scan_disks(self) -> list[dict[str, Any]]:
        result = self.runner.run(
            ["lsblk", "-J", "-o", "NAME,PATH,SIZE,TYPE,MODEL"],
            allow_when_dry_run=True,
        )
        if result.returncode != 0 or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        devices = data.get("blockdevices", [])
        return [device for device in devices if device.get("type") == "disk"]

    def suggest_partition_scheme(self) -> dict[str, Any]:
        scheme = "gpt-uefi" if self.is_uefi() else "gpt-bios"
        notes = [
            "Dry-run suggestion only. No partitioning has been performed.",
            "Recommended layout: ESP on UEFI systems plus root.",
        ]
        if self.is_uefi():
            notes.append("UEFI detected; include an EFI System Partition mounted at /efi.")
        else:
            notes.append("UEFI not detected; include a BIOS boot partition if using GRUB on GPT.")
        return {"scheme": scheme, "notes": notes}
