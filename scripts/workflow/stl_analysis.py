"""STL geometry analysis for mesh auto-configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import struct
from pathlib import Path
from typing import Iterable


@dataclass
class StlAnalysis:
    path: str
    triangle_count: int
    vertex_count: int
    unique_vertex_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    center: tuple[float, float, float]
    chord: float
    thickness: float
    span: float
    min_edge: float
    mean_edge: float
    max_edge: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def analyze_stl(path: Path) -> StlAnalysis:
    vertices = _read_stl_vertices(path)
    if len(vertices) < 3:
        raise ValueError(f"STL does not contain enough vertices: {path}")
    xs = [point[0] for point in vertices]
    ys = [point[1] for point in vertices]
    zs = [point[2] for point in vertices]
    bounds_min = (min(xs), min(ys), min(zs))
    bounds_max = (max(xs), max(ys), max(zs))
    edges = _edge_lengths(vertices)
    unique_vertices = {
        (round(point[0], 12), round(point[1], 12), round(point[2], 12))
        for point in vertices
    }
    return StlAnalysis(
        path=str(path),
        triangle_count=len(vertices) // 3,
        vertex_count=len(vertices),
        unique_vertex_count=len(unique_vertices),
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        center=(
            0.5 * (bounds_min[0] + bounds_max[0]),
            0.5 * (bounds_min[1] + bounds_max[1]),
            0.5 * (bounds_min[2] + bounds_max[2]),
        ),
        chord=max(bounds_max[0] - bounds_min[0], 1.0e-12),
        thickness=max(bounds_max[1] - bounds_min[1], 1.0e-12),
        span=max(bounds_max[2] - bounds_min[2], 1.0e-12),
        min_edge=min(edges) if edges else 0.0,
        mean_edge=sum(edges) / len(edges) if edges else 0.0,
        max_edge=max(edges) if edges else 0.0,
    )


def apply_stl_mesh_estimate(cfg, analysis: StlAnalysis) -> list[str]:
    """Set initial mesh parameters from the exact STL geometry."""

    notes: list[str] = []
    chord = analysis.chord
    x0, y0, z0 = analysis.bounds_min
    x1, y1, z1 = analysis.bounds_max
    upstream = cfg.get_float("mesh_estimation", "upstream_chords", fallback=5.0)
    downstream = cfg.get_float("mesh_estimation", "downstream_chords", fallback=10.0)
    normal = cfg.get_float("mesh_estimation", "normal_chords", fallback=5.0)
    z_padding = cfg.get_float("mesh_estimation", "span_padding_fraction", fallback=0.5)

    _set_float(cfg, "domain", "x_min", (x0 - upstream * chord) / chord, notes)
    _set_float(cfg, "domain", "x_max", (x1 + downstream * chord) / chord, notes)
    _set_float(cfg, "domain", "y_min", (y0 - normal * chord) / chord, notes)
    _set_float(cfg, "domain", "y_max", (y1 + normal * chord) / chord, notes)
    _set_float(cfg, "domain", "z_min", (z0 - z_padding * analysis.span) / chord, notes)
    _set_float(cfg, "domain", "z_max", (z1 + z_padding * analysis.span) / chord, notes)

    x_density = cfg.get_float("mesh_estimation", "base_cells_per_chord_x", fallback=15.0)
    y_density = cfg.get_float("mesh_estimation", "base_cells_per_chord_y", fallback=15.0)
    z_density = cfg.get_float("mesh_estimation", "base_cells_per_span", fallback=4.0)
    domain_x = (x1 + downstream * chord) - (x0 - upstream * chord)
    domain_y = (y1 + normal * chord) - (y0 - normal * chord)
    domain_z = analysis.span * (1.0 + 2.0 * z_padding)
    _set_int(cfg, "domain", "cells_x", max(20, math.ceil(domain_x / chord * x_density)), notes)
    _set_int(cfg, "domain", "cells_y", max(20, math.ceil(domain_y / chord * y_density)), notes)
    _set_int(cfg, "domain", "cells_z", max(2, math.ceil(domain_z / analysis.span * z_density)), notes)

    location = (
        x1 + cfg.get_float("mesh_estimation", "location_downstream_chords", fallback=3.0) * chord,
        analysis.center[1],
        analysis.center[2],
    )
    _set_raw(cfg, "snappy", "location_in_mesh", " ".join(_num(value) for value in location), notes)

    local_edge = analysis.min_edge if analysis.min_edge > 0 else analysis.mean_edge
    first_distance = max(
        cfg.get_float("mesh_estimation", "near_distance_chords", fallback=0.02) * chord,
        local_edge * cfg.get_float("mesh_estimation", "near_distance_edge_factor", fallback=2.5),
    )
    distance_multipliers = cfg.get("mesh_estimation", "distance_multipliers", fallback="1, 4, 12, 36")
    levels_raw = cfg.get("mesh_estimation", "distance_levels", fallback="8, 7, 6, 5")
    multipliers = [float(item.strip()) for item in distance_multipliers.replace(";", ",").split(",") if item.strip()]
    levels = [int(item.strip()) for item in levels_raw.replace(";", ",").split(",") if item.strip()]
    pairs = [
        (first_distance * multiplier, levels[min(index, len(levels) - 1)])
        for index, multiplier in enumerate(multipliers)
    ]
    if pairs:
        _set_raw(
            cfg,
            "distance_refinement",
            "levels",
            "; ".join(f"{distance:g} {level}" for distance, level in pairs),
            notes,
        )
        _set_raw(cfg, "distance_refinement", "enabled", "true", notes)

    base_surface_level = cfg.get_int("mesh_estimation", "surface_level", fallback=6)
    _set_int(cfg, "snappy", "surface_level_min", max(1, base_surface_level - 1), notes)
    _set_int(cfg, "snappy", "surface_level_max", base_surface_level, notes)
    _set_int(cfg, "snappy", "feature_level", base_surface_level, notes)

    min_cells = cfg.get_int("mesh_auto", "min_cells", fallback=1_000_000)
    global_factor = cfg.get_float("mesh_auto", "max_global_cell_factor", fallback=6.0)
    _set_int(cfg, "snappy", "max_global_cells", max(cfg.get_int("snappy", "max_global_cells", fallback=0), math.ceil(min_cells * global_factor)), notes)
    _set_int(cfg, "snappy", "max_local_cells", max(cfg.get_int("snappy", "max_local_cells", fallback=0), math.ceil(min_cells * global_factor / 2)), notes)
    return notes


def _read_stl_vertices(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    if _looks_like_binary_stl(data):
        return _read_binary_stl_vertices(data)
    return _read_ascii_stl_vertices(path)


def _looks_like_binary_stl(data: bytes) -> bool:
    if len(data) < 84:
        return False
    triangle_count = struct.unpack("<I", data[80:84])[0]
    return 84 + triangle_count * 50 == len(data)


def _read_binary_stl_vertices(data: bytes) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    triangle_count = struct.unpack("<I", data[80:84])[0]
    offset = 84
    for _ in range(triangle_count):
        offset += 12
        for _ in range(3):
            vertices.append(struct.unpack("<fff", data[offset:offset + 12]))
            offset += 12
        offset += 2
    return vertices


def _read_ascii_stl_vertices(path: Path) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped.startswith("vertex "):
            continue
        parts = stripped.split()
        if len(parts) != 4:
            continue
        vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return vertices


def _edge_lengths(vertices: list[tuple[float, float, float]]) -> list[float]:
    edges: list[float] = []
    for index in range(0, len(vertices), 3):
        tri = vertices[index:index + 3]
        if len(tri) < 3:
            continue
        edges.extend((_distance(tri[0], tri[1]), _distance(tri[1], tri[2]), _distance(tri[2], tri[0])))
    return edges


def _distance(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(a)
    bv = tuple(b)
    return math.sqrt(sum((av[index] - bv[index]) ** 2 for index in range(3)))


def _set_int(cfg, section: str, option: str, value: int, notes: list[str]) -> None:
    _set_raw(cfg, section, option, str(int(value)), notes)


def _set_float(cfg, section: str, option: str, value: float, notes: list[str]) -> None:
    _set_raw(cfg, section, option, _num(value), notes)


def _set_raw(cfg, section: str, option: str, value: str, notes: list[str]) -> None:
    if not cfg.parser.has_section(section):
        cfg.parser.add_section(section)
    old = cfg.parser.get(section, option).strip() if cfg.parser.has_option(section, option) else None
    if old == value:
        return
    cfg.parser.set(section, option, value)
    notes.append(f"[{section}] {option}: {old if old is not None else '<unset>'} -> {value}")


def _num(value: float) -> str:
    return f"{float(value):.12g}"
