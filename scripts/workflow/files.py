"""Filesystem utilities for restartable generated cases."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


GENERATED_MARKERS = {
    ".meshdone",
    ".meshprepared",
    ".samplingdone",
    ".runsdone",
    ".runprepared",
    ".postdone",
    ".caseprepared",
    ".casedone",
    ".casefailed",
    ".submitted",
}


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def touch(path: Path) -> None:
    ensure_dir(path.parent)
    path.write_text("", encoding="utf-8")


def marker_exists(directory: Path, marker: str) -> bool:
    return (directory / marker).exists()


def remove_markers(directory: Path) -> None:
    for marker in GENERATED_MARKERS:
        path = directory / marker
        if path.exists():
            path.unlink()


def copytree_clean(src: Path, dst: Path, force: bool = False) -> None:
    if dst.exists():
        if force:
            shutil.rmtree(dst)
        else:
            return
    ignore = shutil.ignore_patterns(
        "processor*",
        "postProcessing",
        "log.*",
        "*.log",
        ".meshdone",
        ".meshprepared",
        ".samplingdone",
        ".runsdone",
        ".postdone",
    )
    shutil.copytree(src, dst, ignore=ignore)


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_executable(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass
