import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False


class CommandRunner:
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        allow_when_dry_run: bool = False,
    ) -> CommandResult:
        cmd = list(args)
        if self.dry_run and not allow_when_dry_run:
            return CommandResult(args=cmd, returncode=0, dry_run=True)

        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=capture_output,
            text=text,
        )
        result = CommandResult(
            args=cmd,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            dry_run=False,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result
