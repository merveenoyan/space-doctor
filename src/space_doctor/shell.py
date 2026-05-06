from __future__ import annotations

import subprocess
from pathlib import Path

from .models import CommandResult


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            timeout=timeout,
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError as exc:
        return CommandResult(command=command, returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Command timed out after {timeout}s",
        )
