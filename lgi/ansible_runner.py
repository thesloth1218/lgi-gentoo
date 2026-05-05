import os
import shutil
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = ROOT / "ansible"
VARS_PATH = Path("/tmp/lgi-gentoo/vars.yml")
OUTSIDE_PLAYBOOK = ANSIBLE_DIR / "playbooks" / "outside.yml"
LOCAL_INVENTORY = ANSIBLE_DIR / "inventory" / "local.ini"
BUNDLED_ANSIBLE = ROOT / ".lgi-ansible" / "bin" / "ansible-playbook"
DEFAULT_PACKAGE = Path("/tmp/lgi-gentoo/lgi-gentoo-runner.tar.gz")


class AnsibleRunnerError(RuntimeError):
    pass


def run_outside_playbook(extra_args: list[str] | None = None) -> int:
    ansible_playbook = _ansible_playbook()
    if not VARS_PATH.exists():
        raise AnsibleRunnerError(f"{VARS_PATH} does not exist. Run `python3 main.py generate` first.")
    package_runner()

    command = [
        ansible_playbook,
        "-i",
        str(LOCAL_INVENTORY),
        str(OUTSIDE_PLAYBOOK),
    ]
    command.extend(_verbosity_args(extra_args))
    if extra_args:
        command.extend(extra_args)

    env = ansible_environment()
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def ansible_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ANSIBLE_DIR / "ansible.cfg")
    env.setdefault("ANSIBLE_LOCAL_TEMP", "/tmp/lgi-gentoo/ansible-local-tmp")
    env.setdefault("ANSIBLE_REMOTE_TEMP", "/tmp/lgi-gentoo/ansible-remote-tmp")
    env.setdefault("TMPDIR", "/tmp/lgi-gentoo")
    env.setdefault("ANSIBLE_STDOUT_CALLBACK", "default")
    env.setdefault("ANSIBLE_DISPLAY_ARGS_TO_STDOUT", "True")
    env.setdefault("ANSIBLE_LOAD_CALLBACK_PLUGINS", "True")
    return env


def _verbosity_args(extra_args: list[str] | None) -> list[str]:
    if extra_args and any(arg == "-v" or arg.startswith("-vv") or arg == "--verbose" for arg in extra_args):
        return []
    return ["-v"]


def package_runner(output_path: Path = DEFAULT_PACKAGE) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    include = [
        "ansible",
        "lgi",
        "main.py",
        "pyproject.toml",
        "Kconfig",
        "README.md",
    ]
    if (ROOT / ".lgi-ansible").exists():
        include.append(".lgi-ansible")

    with tarfile.open(output_path, "w:gz") as archive:
        for item in include:
            path = ROOT / item
            if path.exists():
                archive.add(path, arcname=f"lgi-gentoo/{item}", filter=_package_filter)
    return output_path


def _ansible_playbook() -> str:
    if BUNDLED_ANSIBLE.exists():
        return str(BUNDLED_ANSIBLE)

    found = shutil.which("ansible-playbook")
    if found:
        return found

    raise AnsibleRunnerError(
        "ansible-playbook was not found. Build a bundled environment with "
        "`ansible/scripts/build_ansible_bundle.sh` or install ansible-core."
    )


def _package_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if "__pycache__" in parts or info.name.endswith(".pyc"):
        return None
    return info
