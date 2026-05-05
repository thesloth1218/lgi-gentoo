import argparse
import sys

from lgi.ansible_runner import AnsibleRunnerError, package_runner, run_outside_playbook
from lgi.bootstrap import BootstrapError, bootstrap_first_run
from lgi.dialog_runner import DialogCancelled, DialogError, run_dialog_installer
from lgi.kconfig_runner import (
    KconfigConfigError,
    generate_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Larry's Gentoo Installer")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "dialog", "bootstrap", "generate", "install", "package-runner"),
        help="Run the dialog flow, bootstrap dependencies, generate outputs, run install playbook, or package the runner.",
    )
    args = parser.parse_args()

    try:
        if args.command in ("run", "dialog"):
            bootstrap_first_run(ensure_dialog=True, ensure_ansible=True)
            vars_path, make_path = run_dialog_installer()
        elif args.command == "bootstrap":
            report = bootstrap_first_run(ensure_dialog=True, ensure_ansible=True)
            print(f"Runtime dir: {report.runtime_dir}")
            print(f"dialog: {report.dialog_path}")
            print(f"ansible-playbook: {report.ansible_playbook}")
            for action in report.actions:
                print(f"- {action}")
            return 0
        elif args.command == "generate":
            vars_path, make_path = generate_outputs()
            print(f"Wrote {vars_path}")
            print(f"Wrote {make_path}")
            return 0
        elif args.command == "install":
            bootstrap_first_run(ensure_dialog=False, ensure_ansible=True)
            return run_outside_playbook()
        else:
            bootstrap_first_run(ensure_dialog=False, ensure_ansible=True)
            package_path = package_runner()
            print(f"Wrote {package_path}")
            return 0
    except DialogCancelled as exc:
        print(exc, file=sys.stderr)
        return 130
    except (DialogError, KconfigConfigError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except AnsibleRunnerError as exc:
        print(exc, file=sys.stderr)
        return 1
    except BootstrapError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Wrote {vars_path}")
    print(f"Wrote {make_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
