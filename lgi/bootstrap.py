import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lgi.ansible_runner import BUNDLED_ANSIBLE, ROOT, ansible_environment


RUNTIME_DIR = Path("/tmp/lgi-gentoo")
BUILD_SCRIPT = ROOT / "ansible" / "scripts" / "build_ansible_bundle.sh"


class BootstrapError(RuntimeError):
    pass


@dataclass
class BootstrapReport:
    runtime_dir: Path
    dialog_path: str | None = None
    ansible_playbook: str | None = None
    bundled_ansible_ready: bool = False
    actions: list[str] = field(default_factory=list)


def bootstrap_first_run(
    *,
    ensure_dialog: bool = True,
    ensure_ansible: bool = True,
    auto_build_ansible: bool = True,
) -> BootstrapReport:
    report = BootstrapReport(runtime_dir=RUNTIME_DIR)
    _ensure_runtime_dirs(report)
    _ensure_project_files()
    if ensure_dialog:
        report.dialog_path = _require_tool("dialog")

    if ensure_ansible:
        report.ansible_playbook = _ensure_ansible(auto_build=auto_build_ansible, report=report)
        report.bundled_ansible_ready = BUNDLED_ANSIBLE.exists()

    return report


def _ensure_runtime_dirs(report: BootstrapReport) -> None:
    for path in (
        RUNTIME_DIR,
        RUNTIME_DIR / "ansible-local-tmp",
        RUNTIME_DIR / "ansible-remote-tmp",
    ):
        path.mkdir(parents=True, exist_ok=True)
    report.actions.append(f"runtime directories ready under {RUNTIME_DIR}")


def _ensure_project_files() -> None:
    required = [
        ROOT / "main.py",
        ROOT / "lgi",
        ROOT / "ansible" / "ansible.cfg",
        ROOT / "ansible" / "inventory" / "local.ini",
        ROOT / "ansible" / "playbooks" / "outside.yml",
        ROOT / "ansible" / "scripts" / "run_chroot_phase.sh",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise BootstrapError("Missing required installer files:\n" + "\n".join(missing))


def _require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BootstrapError(
            f"Missing required tool: {name}\n"
            f"Install `{name}` on the live environment, then run `python3 main.py` again."
        )
    return found


def _ensure_ansible(*, auto_build: bool, report: BootstrapReport) -> str:
    if BUNDLED_ANSIBLE.exists():
        report.actions.append(f"bundled Ansible ready at {BUNDLED_ANSIBLE}")
        return _validated_ansible(str(BUNDLED_ANSIBLE))

    system_ansible = shutil.which("ansible-playbook")
    if not auto_build:
        if system_ansible:
            report.actions.append(f"using system ansible-playbook at {system_ansible}")
            return _validated_ansible(system_ansible)
        raise BootstrapError(
            "ansible-playbook was not found and bundled Ansible is not built.\n"
            "Run `python3 main.py bootstrap` or `ansible/scripts/build_ansible_bundle.sh` first."
        )

    _ensure_venv_available()
    if not BUILD_SCRIPT.exists():
        raise BootstrapError(f"Missing Ansible bundle build script: {BUILD_SCRIPT}")

    print("LGI bootstrap: building bundled Ansible environment for live CD and chroot use.", file=sys.stderr)
    result = subprocess.run(["sh", str(BUILD_SCRIPT)], cwd=ROOT, check=False)
    if result.returncode != 0:
        raise BootstrapError(
            "Could not build bundled Ansible environment.\n"
            "The live environment needs network access and Python venv support, or the runner package must already include .lgi-ansible."
        )
    if not BUNDLED_ANSIBLE.exists():
        raise BootstrapError(f"Ansible bundle build finished, but {BUNDLED_ANSIBLE} was not created.")

    report.actions.append(f"built bundled Ansible at {BUNDLED_ANSIBLE}")
    return _validated_ansible(str(BUNDLED_ANSIBLE))


def _ensure_venv_available() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "venv", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise BootstrapError(
            "Python venv support is not available, so LGI cannot build bundled Ansible here.\n"
            "Build the runner on another machine with `python3 main.py package-runner` and transfer the tarball."
        )


def _validated_ansible(ansible_playbook: str) -> str:
    result = subprocess.run(
        [ansible_playbook, "--version"],
        cwd=ROOT,
        env=ansible_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BootstrapError(
            "ansible-playbook exists but could not start with LGI's runtime environment.\n"
            f"{result.stderr.strip()}"
        )
    return ansible_playbook
