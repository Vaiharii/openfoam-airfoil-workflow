"""Mesh quality parsing and automatic tuning helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from pathlib import Path
from typing import Any

from .config import WorkflowConfig


@dataclass
class MeshCheckResult:
    log_path: str
    cells: int | None = None
    points: int | None = None
    faces: int | None = None
    failed_checks: int | None = None
    max_aspect_ratio: float | None = None
    max_non_orthogonality: float | None = None
    average_non_orthogonality: float | None = None
    max_skewness: float | None = None
    highly_skew_faces: int | None = None
    error_locations: list[tuple[float, float, float]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_check_mesh_log(log_path: Path) -> MeshCheckResult:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = MeshCheckResult(log_path=str(log_path))
    result.points = _int_match(text, r"^\s*points:\s*(\d+)", re.MULTILINE)
    result.faces = _int_match(text, r"^\s*faces:\s*(\d+)", re.MULTILINE)
    result.cells = _int_match(text, r"^\s*cells:\s*(\d+)", re.MULTILINE)
    result.max_aspect_ratio = _float_match(text, r"Max aspect ratio =\s*([0-9.eE+-]+)")
    result.max_non_orthogonality = _float_match(text, r"Mesh non-orthogonality Max:\s*([0-9.eE+-]+)")
    result.average_non_orthogonality = _float_match(text, r"Mesh non-orthogonality Max:[^\n]*average:\s*([0-9.eE+-]+)")
    result.max_skewness = _float_match(text, r"Max skewness =\s*([0-9.eE+-]+)")
    result.highly_skew_faces = _int_match(text, r"Max skewness =\s*[0-9.eE+-]+,\s*(\d+)\s+highly skew faces")
    result.error_locations = _extract_error_locations_from_text(text)

    failed = _int_match(text, r"Failed\s+(\d+)\s+mesh checks")
    if failed is None and re.search(r"\bMesh OK\b", text):
        failed = 0
    result.failed_checks = failed
    return result


def mesh_check_is_acceptable(cfg: WorkflowConfig, result: MeshCheckResult | None) -> bool:
    if result is None:
        return False
    min_cells = cfg.get_int("mesh_auto", "min_cells", fallback=0)
    require_zero_failed = cfg.get_bool("mesh_auto", "require_zero_failed_checks", fallback=True)
    if result.cells is None or result.cells < min_cells:
        return False
    if require_zero_failed and result.failed_checks != 0:
        return False
    return True


def mesh_check_reason(cfg: WorkflowConfig, result: MeshCheckResult | None) -> str:
    if result is None:
        return "No checkMesh result was available."
    reasons: list[str] = []
    min_cells = cfg.get_int("mesh_auto", "min_cells", fallback=0)
    if result.cells is None:
        reasons.append("cell count could not be parsed")
    elif result.cells < min_cells:
        reasons.append(f"{result.cells} cells < target {min_cells}")
    if cfg.get_bool("mesh_auto", "require_zero_failed_checks", fallback=True) and result.failed_checks != 0:
        reasons.append(f"{result.failed_checks} failed checkMesh checks")
    return "; ".join(reasons) if reasons else "mesh accepted"


def adjust_mesh_parameters(
    cfg: WorkflowConfig,
    result: MeshCheckResult | None,
    attempt: int,
    case_dir: Path | None = None,
    stl_analysis: Any | None = None,
) -> list[str]:
    """Mutate the in-memory config with conservative next-attempt mesh changes."""

    notes: list[str] = []
    min_cells = cfg.get_int("mesh_auto", "min_cells", fallback=1_000_000)
    current_cells = result.cells if result and result.cells else None
    if current_cells is None or current_cells < min_cells:
        growth_limit = cfg.get_float("mesh_auto", "max_cell_growth_per_attempt", fallback=1.35)
        if current_cells and current_cells > 0:
            growth = math.sqrt(min_cells / current_cells)
            growth = max(1.08, min(growth, growth_limit))
        else:
            growth = growth_limit
        for key in ("cells_x", "cells_y"):
            old = cfg.get_int("domain", key)
            new = max(old + 1, int(math.ceil(old * growth)))
            _set_int(cfg, "domain", key, new)
            if new != old:
                notes.append(f"[domain] {key}: {old} -> {new}")
        min_z = cfg.get_int("mesh_auto", "min_cells_z", fallback=4)
        old_z = cfg.get_int("domain", "cells_z")
        new_z = max(old_z, min_z)
        _set_int(cfg, "domain", "cells_z", new_z)
        if new_z != old_z:
            notes.append(f"[domain] cells_z: {old_z} -> {new_z}")

        max_surface = cfg.get_int("mesh_auto", "max_surface_level", fallback=9)
        for key in ("surface_level_min", "surface_level_max", "feature_level"):
            old = cfg.get_int("snappy", key)
            new = min(old + 1, max_surface)
            _set_int(cfg, "snappy", key, new)
            if new != old:
                notes.append(f"[snappy] {key}: {old} -> {new}")
        notes.extend(_raise_distance_levels(cfg))

    if result and result.failed_checks and result.failed_checks > 0:
        notes.extend(_add_local_refinement_from_errors(cfg, result, attempt, case_dir, stl_analysis))
        old_between = cfg.get_int("snappy", "n_cells_between_levels", fallback=3)
        new_between = min(old_between + 1, cfg.get_int("mesh_auto", "max_cells_between_levels", fallback=6))
        _set_int(cfg, "snappy", "n_cells_between_levels", new_between)
        if new_between != old_between:
            notes.append(f"[snappy] n_cells_between_levels: {old_between} -> {new_between}")
        for section, key in (("snap", "n_smooth_patch"), ("snap", "n_solve_iter"), ("snap", "n_relax_iter")):
            old = cfg.get_int(section, key, fallback=_snap_default(key))
            increment = 2 if key == "n_smooth_patch" else 10
            new = min(old + increment, cfg.get_int("mesh_auto", f"max_{key}", fallback=old + increment))
            _set_int(cfg, section, key, new)
            if new != old:
                notes.append(f"[{section}] {key}: {old} -> {new}")

    global_factor = cfg.get_float("mesh_auto", "max_global_cell_factor", fallback=3.0)
    target_global = int(math.ceil(min_cells * global_factor))
    old_global = cfg.get_int("snappy", "max_global_cells", fallback=target_global)
    new_global = max(old_global, target_global)
    _set_int(cfg, "snappy", "max_global_cells", new_global)
    if new_global != old_global:
        notes.append(f"[snappy] max_global_cells: {old_global} -> {new_global}")
    old_local = cfg.get_int("snappy", "max_local_cells", fallback=max(1, new_global // 2))
    new_local = max(old_local, max(1, new_global // 2))
    _set_int(cfg, "snappy", "max_local_cells", new_local)
    if new_local != old_local:
        notes.append(f"[snappy] max_local_cells: {old_local} -> {new_local}")

    if not notes:
        notes.append(f"No obvious automatic mesh change available after attempt {attempt}.")
    return notes


def _add_local_refinement_from_errors(
    cfg: WorkflowConfig,
    result: MeshCheckResult,
    attempt: int,
    case_dir: Path | None,
    stl_analysis: Any | None,
) -> list[str]:
    if not cfg.get_bool("local_refinement", "enabled", fallback=True):
        return []
    locations = list(result.error_locations or [])
    if case_dir is not None:
        locations.extend(_extract_error_locations_from_case(case_dir))
    locations = _dedupe_points(locations)
    if not locations:
        return []

    max_boxes = cfg.get_int("local_refinement", "max_boxes", fallback=16)
    max_new = cfg.get_int("local_refinement", "max_new_boxes_per_attempt", fallback=4)
    existing = _parse_local_refinement_boxes(cfg.get("local_refinement", "boxes", fallback=""))
    remaining = max(0, max_boxes - len(existing))
    if remaining <= 0:
        return []

    chord = float(getattr(stl_analysis, "chord", cfg.get_float("geometry", "chord", fallback=1.0)))
    local_edge = float(getattr(stl_analysis, "min_edge", 0.0) or getattr(stl_analysis, "mean_edge", 0.0) or 0.0)
    radius = max(
        chord * cfg.get_float("local_refinement", "box_radius_chords", fallback=0.04),
        local_edge * cfg.get_float("local_refinement", "box_radius_edge_factor", fallback=8.0),
    )
    level = min(
        cfg.get_int("local_refinement", "max_level", fallback=9),
        max(cfg.get_int("snappy", "surface_level_max", fallback=6) + 1, cfg.get_int("local_refinement", "min_level", fallback=7)),
    )

    new_boxes: list[dict[str, Any]] = []
    for point in locations:
        if len(new_boxes) >= min(max_new, remaining):
            break
        if _point_is_inside_existing_box(point, existing, padding=0.25 * radius):
            continue
        name = f"errorBox_a{attempt:02d}_{len(existing) + len(new_boxes) + 1:02d}"
        new_boxes.append(
            {
                "name": name,
                "min": (point[0] - radius, point[1] - radius, point[2] - radius),
                "max": (point[0] + radius, point[1] + radius, point[2] + radius),
                "level": level,
            }
        )

    if not new_boxes:
        return []
    combined = existing + new_boxes
    if not cfg.parser.has_section("local_refinement"):
        cfg.parser.add_section("local_refinement")
    cfg.parser.set("local_refinement", "boxes", _format_local_refinement_boxes(combined))
    return [
        f"[local_refinement] added {len(new_boxes)} local box(es) around checkMesh error coordinates "
        f"(radius={radius:g}, level={level})"
    ]


def _extract_error_locations_from_case(case_dir: Path) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    patterns = (
        "*skew*.vtk",
        "*nonOrtho*.vtk",
        "*concave*.vtk",
        "*illegal*.vtk",
        "*wrong*.vtk",
        "*error*.vtk",
    )
    for pattern in patterns:
        for path in case_dir.rglob(pattern):
            if path.is_file():
                points.extend(_extract_vtk_points(path))
    return points


def _extract_vtk_points(path: Path) -> list[tuple[float, float, float]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"POINTS\s+(\d+)\s+\w+\s+(.+?)(?:\n[A-Z_]+\s|\Z)", text, re.DOTALL)
    if not match:
        return []
    count = int(match.group(1))
    values = [float(value) for value in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", match.group(2))]
    points: list[tuple[float, float, float]] = []
    for index in range(0, min(len(values), count * 3), 3):
        chunk = values[index:index + 3]
        if len(chunk) == 3:
            points.append((chunk[0], chunk[1], chunk[2]))
    return points


def _extract_error_locations_from_text(text: str) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    keywords = ("skew", "non-orth", "concave", "wrong", "illegal", "error", "failed", "bad")
    for line in text.splitlines():
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        for match in re.finditer(
            r"\(\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\)",
            line,
        ):
            points.append((float(match.group(1)), float(match.group(2)), float(match.group(3))))
    return _dedupe_points(points)


def _dedupe_points(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    seen: set[tuple[float, float, float]] = set()
    output: list[tuple[float, float, float]] = []
    for point in points:
        key = (round(point[0], 8), round(point[1], 8), round(point[2], 8))
        if key in seen:
            continue
        seen.add(key)
        output.append(point)
    return output


def _parse_local_refinement_boxes(raw: str) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    for item in raw.split(";"):
        stripped = item.strip()
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) != 4:
            continue
        try:
            minimum = tuple(float(value) for value in parts[1].split())
            maximum = tuple(float(value) for value in parts[2].split())
            level = int(parts[3])
        except ValueError:
            continue
        if len(minimum) != 3 or len(maximum) != 3:
            continue
        boxes.append({"name": parts[0], "min": minimum, "max": maximum, "level": level})
    return boxes


def _format_local_refinement_boxes(boxes: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{box['name']}|{_format_point(box['min'])}|{_format_point(box['max'])}|{box['level']}"
        for box in boxes
    )


def _format_point(point: tuple[float, float, float]) -> str:
    return " ".join(f"{value:.12g}" for value in point)


def _point_is_inside_existing_box(
    point: tuple[float, float, float],
    boxes: list[dict[str, Any]],
    padding: float = 0.0,
) -> bool:
    for box in boxes:
        if all(box["min"][index] - padding <= point[index] <= box["max"][index] + padding for index in range(3)):
            return True
    return False


def _float_match(text: str, pattern: str, flags: int = 0) -> float | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _int_match(text: str, pattern: str, flags: int = 0) -> int | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _set_int(cfg: WorkflowConfig, section: str, option: str, value: int) -> None:
    if not cfg.parser.has_section(section):
        cfg.parser.add_section(section)
    cfg.parser.set(section, option, str(int(value)))


def _snap_default(key: str) -> int:
    return {
        "n_smooth_patch": 3,
        "n_solve_iter": 30,
        "n_relax_iter": 5,
    }[key]


def _raise_distance_levels(cfg: WorkflowConfig) -> list[str]:
    if not cfg.get_bool("distance_refinement", "enabled", fallback=False):
        return []
    raw = cfg.get("distance_refinement", "levels", fallback="")
    parsed = _parse_distance_levels(raw)
    if not parsed:
        return []
    max_level = cfg.get_int("mesh_auto", "max_distance_level", fallback=9)
    raised = [(distance, min(level + 1, max_level)) for distance, level in parsed]
    if raised == parsed:
        return []
    cfg.parser.set(
        "distance_refinement",
        "levels",
        "; ".join(f"{distance:g} {level}" for distance, level in raised),
    )
    return ["[distance_refinement] levels raised by 1 near the airfoil"]


def _parse_distance_levels(raw: str) -> list[tuple[float, int]]:
    levels: list[tuple[float, int]] = []
    for match in re.finditer(r"\(?\s*([0-9.eE+-]+)\s*[:, ]\s*([0-9]+)\s*\)?", raw):
        levels.append((float(match.group(1)), int(match.group(2))))
    return levels
