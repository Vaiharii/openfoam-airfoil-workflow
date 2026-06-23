"""Best-effort post-processing for generated OpenFOAM cases."""

from __future__ import annotations

import csv
import math
import re
import shutil
from pathlib import Path
from typing import Any

from .files import ensure_dir
from .sampling import read_sampling_csv


def _numeric_time_dirs(case_dir: Path, include_initial: bool = False) -> list[float]:
    times: list[float] = []
    for path in case_dir.iterdir() if case_dir.exists() else []:
        if not path.is_dir():
            continue
        try:
            value = float(path.name)
        except ValueError:
            continue
        if math.isfinite(value) and (include_initial or value > 0):
            times.append(value)
    return sorted(times)


def _latest_numeric_row(path: Path) -> tuple[list[str], list[str]] | None:
    header: list[str] = []
    latest: list[str] | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            possible = stripped.lstrip("#").split()
            if possible and possible[0].lower() == "time":
                header = possible
            continue
        parts = stripped.split()
        try:
            [float(part) for part in parts]
        except ValueError:
            continue
        latest = parts
    if latest is None:
        return None
    return header, latest


def _latest_force_coefficients(case_dir: Path) -> dict[str, Any]:
    files = sorted(case_dir.glob("postProcessing/forceCoeffs*/*/coefficient.dat"))
    if not files:
        return {}
    path = max(files, key=lambda item: item.stat().st_mtime)
    parsed = _latest_numeric_row(path)
    if parsed is None:
        return {"force_coefficients_file": str(path)}
    header, row = parsed
    output: dict[str, Any] = {"force_coefficients_file": str(path)}
    if header and len(header) == len(row):
        for key, value in zip(header, row, strict=False):
            output[f"force_{key}"] = value
    else:
        for index, value in enumerate(row):
            output[f"force_col_{index}"] = value
    return output


def _latest_y_plus(case_dir: Path) -> dict[str, Any]:
    files = sorted(case_dir.glob("postProcessing/yPlus*/*/yPlus.dat"))
    if not files:
        return {}
    path = max(files, key=lambda item: item.stat().st_mtime)
    latest: list[str] | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 5:
            continue
        try:
            float(parts[0])
            float(parts[2])
            float(parts[3])
            float(parts[4])
        except ValueError:
            continue
        latest = parts
    if latest is None:
        return {"yplus_file": str(path)}
    return {
        "yplus_file": str(path),
        "yplus_Time": latest[0],
        "yplus_patch": latest[1],
        "yplus_min": latest[2],
        "yplus_max": latest[3],
        "yplus_average": latest[4],
    }


def _latest_residuals(case_dir: Path) -> dict[str, Any]:
    files = sorted(case_dir.glob("postProcessing/residuals*/*/residuals.dat"))
    if not files:
        return {}
    path = max(files, key=lambda item: item.stat().st_mtime)
    parsed = _latest_numeric_row(path)
    if parsed is None:
        return {"residuals_file": str(path)}
    header, row = parsed
    output: dict[str, Any] = {"residuals_file": str(path)}
    if header and len(header) == len(row):
        for key, value in zip(header, row, strict=False):
            output[f"residual_{key}"] = value
    else:
        for index, value in enumerate(row):
            output[f"residual_col_{index}"] = value
    return output


def _solver_log_status(case_dir: Path) -> dict[str, Any]:
    logs = sorted(case_dir.glob("log.run.*"))
    if not logs:
        return {}
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in logs)
    output: dict[str, Any] = {
        "run_log_files": ";".join(str(path) for path in logs),
        "run_fatal_error_count": len(
            re.findall(r"FOAM FATAL|Segmentation fault|Divergence detected|Floating point exception$", text, re.MULTILINE)
        ),
        "run_bounding_count": len(re.findall(r"^\s*bounding\s+", text, re.MULTILINE)),
        "run_simple_converged": bool(re.search(r"SIMPLE solution converged in\s+\d+\s+iterations", text)),
        "run_finalised": bool(re.search(r"Finalising parallel run|^End\s*$", text, re.MULTILINE)),
    }
    times = [float(match.group(1)) for match in re.finditer(r"^Time =\s*([0-9.eE+-]+)", text, re.MULTILINE)]
    if times:
        output["run_latest_time"] = times[-1]
    convergence = re.search(r"SIMPLE solution converged in\s+(\d+)\s+iterations", text)
    if convergence:
        output["run_converged_iterations"] = convergence.group(1)
    residuals: dict[str, tuple[str, str]] = {}
    for match in re.finditer(
        r"Solving for\s+([^,]+),\s+Initial residual =\s*([0-9.eE+-]+),\s+Final residual =\s*([0-9.eE+-]+)",
        text,
    ):
        residuals[match.group(1).strip()] = (match.group(2), match.group(3))
    for field, (initial, final) in residuals.items():
        safe_field = field.replace(" ", "_")
        output[f"log_residual_{safe_field}_initial"] = initial
        output[f"log_residual_{safe_field}_final"] = final
    return output


def postprocess(study_dir: Path, results_dir: Path) -> dict[str, Any]:
    ensure_dir(results_dir)
    sampling_path = study_dir / "sampling.csv"
    if not sampling_path.is_file():
        raise FileNotFoundError(f"Cannot post-process without {sampling_path}")

    samples = read_sampling_csv(sampling_path)
    summary_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for sample in samples:
        case_id = sample["case_id"]
        case_dir = study_dir / case_id
        times = _numeric_time_dirs(case_dir)
        status = "missing"
        if (case_dir / ".casedone").exists():
            status = "completed"
        elif (case_dir / ".casefailed").exists():
            status = "failed"
        elif case_dir.exists():
            status = "prepared"

        row: dict[str, Any] = dict(sample)
        row["case_status"] = status
        row["latest_time"] = times[-1] if times else ""
        row.update(_latest_force_coefficients(case_dir))
        row.update(_latest_y_plus(case_dir))
        row.update(_latest_residuals(case_dir))
        row.update(_solver_log_status(case_dir))
        if row["latest_time"] == "":
            for key in ("run_latest_time", "force_Time", "yplus_Time"):
                if key in row and row[key] != "":
                    row["latest_time"] = row[key]
                    break
        summary_rows.append(row)
        status_rows.append(
            {
                "case_id": case_id,
                "status": status,
                "case_dir": str(case_dir),
                "latest_time": row["latest_time"],
            }
        )

    _write_csv(results_dir / "summary.csv", summary_rows)
    _write_csv(results_dir / "case_status.csv", status_rows)
    shutil.copy2(sampling_path, results_dir / "sampling.csv")
    sampling_txt = study_dir / "sampling.txt"
    if sampling_txt.exists():
        shutil.copy2(sampling_txt, results_dir / "sampling.txt")

    completed = sum(1 for row in status_rows if row["status"] == "completed")
    failed = sum(1 for row in status_rows if row["status"] == "failed")
    prepared = sum(1 for row in status_rows if row["status"] == "prepared")
    report = [
        "# Post-processing report",
        "",
        f"Study: {study_dir.name}",
        f"Cases: {len(status_rows)}",
        f"Completed: {completed}",
        f"Failed: {failed}",
        f"Prepared/no run marker: {prepared}",
        "",
        "Files:",
        "- summary.csv",
        "- case_status.csv",
        "- sampling.csv",
    ]
    (results_dir / "post_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    return {
        "results_dir": str(results_dir),
        "cases": len(status_rows),
        "completed": completed,
        "failed": failed,
        "prepared": prepared,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
