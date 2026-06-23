"""OpenFOAM command execution helpers."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import WorkflowConfig
from .files import ensure_dir


@dataclass
class CommandResult:
    command: str
    returncode: int
    log_path: Path


class CommandRunner:
    def __init__(self, cfg: WorkflowConfig, dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run

    def run(self, command: str, cwd: Path, log_name: str) -> CommandResult:
        log_path = cwd / log_name
        ensure_dir(cwd)
        prefix = self.cfg.get("execution", "shell_prefix", fallback="")
        full_command = f"{prefix} {command}".strip()
        if self.dry_run:
            log_path.write_text(f"DRY RUN: {full_command}\n", encoding="utf-8")
            print(f"[dry-run] {cwd}: {full_command}")
            return CommandResult(full_command, 0, log_path)

        print(f"[run] {cwd}: {full_command}")
        process = subprocess.run(
            full_command,
            cwd=str(cwd),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_path.write_text(process.stdout or "", encoding="utf-8", errors="replace")
        return CommandResult(full_command, process.returncode, log_path)
