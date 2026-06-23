"""Airfoil selection and STL preparation."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from scripts.geometry.create_stl import create_airfoil_stl_from_dat

from .config import WorkflowConfig
from .files import ensure_dir, read_json, write_json


SUPPORTED_DATABASE_FAMILIES = {"naca4", "naca5", "naca6"}


def airfoil_name(cfg: WorkflowConfig) -> str:
    configured = cfg.get("airfoil", "name", fallback="auto")
    if configured.lower() != "auto":
        return configured.lower()
    family = cfg.get("airfoil", "family").lower()
    code = cfg.get("airfoil", "code").lower().replace("naca", "")
    if family == "naca4" and code.isdigit():
        code = code.zfill(4)
    elif family == "naca5" and code.isdigit():
        code = code.zfill(5)
    if family.startswith("naca"):
        return f"naca{code}"
    return code


def resolve_airfoil_dat(cfg: WorkflowConfig) -> Path:
    source = cfg.get("airfoil", "source", fallback="database").lower()
    if source == "custom":
        custom_path = cfg.get_path("airfoil", "custom_dat_path", allow_empty=False)
        assert custom_path is not None
        if not custom_path.is_file():
            raise FileNotFoundError(f"Custom airfoil DAT not found: {custom_path}")
        return custom_path
    if source != "database":
        raise ValueError(f"Unsupported airfoil source '{source}'. Use database or custom.")

    family = cfg.get("airfoil", "family").lower()
    if family not in SUPPORTED_DATABASE_FAMILIES:
        raise ValueError(
            f"Unsupported airfoil family '{family}'. Add a database directory or use source=custom."
        )
    name = airfoil_name(cfg)
    database_root = cfg.get_path("airfoil", "database_root")
    assert database_root is not None
    dat_path = database_root / family / f"{name}.dat"
    if not dat_path.is_file():
        raise FileNotFoundError(
            f"Airfoil DAT not found: {dat_path}. "
            "Populate the database or switch parameters_geometry.ini to source=custom."
        )
    return dat_path


def prepare_geometry(cfg: WorkflowConfig, force: bool = False) -> dict[str, Any]:
    name = airfoil_name(cfg)
    family = cfg.get("airfoil", "family").lower()
    dat_path = resolve_airfoil_dat(cfg)
    generated_dir = cfg.get_path("output", "generated_dir")
    assert generated_dir is not None
    ensure_dir(generated_dir)

    canonical_name = cfg.get("output", "canonical_stl_name", fallback="geometry.stl")
    canonical_stl = generated_dir / canonical_name
    metadata_path = generated_dir / "geometry.json"
    named_stl = generated_dir / f"{name}.stl"
    chord = cfg.get_float("geometry", "chord")
    span = cfg.get_float("geometry", "span")
    expected_metadata = {
        "airfoil_name": name,
        "family": family,
        "dat_path": str(dat_path),
        "dat_size": dat_path.stat().st_size,
        "dat_mtime_ns": dat_path.stat().st_mtime_ns,
        "chord": chord,
        "span": span,
    }

    metadata_changed = True
    if metadata_path.is_file():
        try:
            current_metadata = read_json(metadata_path)
            metadata_changed = any(
                current_metadata.get(key) != value for key, value in expected_metadata.items()
            )
        except Exception:
            metadata_changed = True

    regenerated_stl = force or metadata_changed or not canonical_stl.is_file()
    if regenerated_stl:
        create_airfoil_stl_from_dat(dat_path, canonical_stl, chord=chord, span=span)
        write_json(metadata_path, expected_metadata)

    if cfg.get_bool("output", "write_named_stl", fallback=True):
        if regenerated_stl or not named_stl.is_file():
            shutil.copy2(canonical_stl, named_stl)

    base_case_geometry = None
    if cfg.get_bool("output", "copy_to_base_case", fallback=True):
        base_case = cfg.get_path("base_case", "template_dir")
        assert base_case is not None
        base_case_geometry = base_case / "constant" / "triSurface" / "geometry.stl"
        ensure_dir(base_case_geometry.parent)
        shutil.copy2(canonical_stl, base_case_geometry)

    info = {
        "airfoil_name": name,
        "family": family,
        "dat_path": str(dat_path),
        "canonical_stl": str(canonical_stl),
        "named_stl": str(named_stl) if named_stl.exists() else "",
        "base_case_geometry": str(base_case_geometry) if base_case_geometry else "",
        "chord": chord,
        "span": span,
    }
    return info
