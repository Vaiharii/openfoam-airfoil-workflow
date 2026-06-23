"""Workflow validation before case generation or execution."""

from __future__ import annotations

from dataclasses import dataclass

from .airfoil import airfoil_name, resolve_airfoil_dat
from .config import WorkflowConfig
from .openfoam import canonical_turbulence_model


@dataclass
class ValidationReport:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_workflow(cfg: WorkflowConfig) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    _check_positive_float(cfg, "geometry", "chord", errors)
    _check_positive_float(cfg, "geometry", "span", errors)
    _check_positive_int(cfg, "domain", "cells_x", errors)
    _check_positive_int(cfg, "domain", "cells_y", errors)
    _check_positive_int(cfg, "domain", "cells_z", errors)
    _check_positive_int(cfg, "execution", "n_processors", errors)
    _check_positive_int(cfg, "execution", "max_workers", errors)

    _check_bounds(cfg, "domain", "x_min", "x_max", errors)
    _check_bounds(cfg, "domain", "y_min", "y_max", errors)
    _check_bounds(cfg, "domain", "z_min", "z_max", errors)

    mode = cfg.get("execution", "mode", fallback="prepare_only").lower()
    if mode not in {"prepare_only", "local", "slurm"}:
        errors.append("[execution] mode must be one of: prepare_only, local, slurm.")

    try:
        template_dir = cfg.get_path("base_case", "template_dir")
        assert template_dir is not None
        if not template_dir.is_dir():
            errors.append(f"Base case template does not exist: {template_dir}")
    except Exception as exc:
        errors.append(str(exc))

    try:
        dat_path = resolve_airfoil_dat(cfg)
        if dat_path.stat().st_size == 0:
            errors.append(f"Airfoil DAT is empty: {dat_path}")
    except Exception as exc:
        errors.append(str(exc))

    try:
        name = airfoil_name(cfg)
        family = cfg.get("airfoil", "family").lower()
        if family == "naca4" and not name.removeprefix("naca").isdigit():
            warnings.append(f"NACA4 name is unusual: {name}")
    except Exception as exc:
        errors.append(str(exc))

    commands = cfg.get_list("mesh", "commands", cast=str)
    if not commands:
        errors.append("[mesh] commands must contain at least one OpenFOAM command.")
    joined_commands = " ; ".join(commands)
    if "checkMesh" not in joined_commands:
        warnings.append("[mesh] commands does not include checkMesh.")
    elif "-allTopology" not in joined_commands or "-allGeometry" not in joined_commands:
        warnings.append("[mesh] checkMesh should use -allTopology -allGeometry for strict mesh validation.")

    if cfg.get_bool("mesh_auto", "enabled", fallback=False):
        _check_non_negative_int(cfg, "mesh_auto", "max_attempts", errors)
        _check_positive_int(cfg, "mesh_auto", "min_cells", errors)
        if cfg.get_int("mesh_auto", "min_cells", fallback=0) < 1_000_000:
            warnings.append("[mesh_auto] min_cells is below the requested 1,000,000-cell target.")
        if cfg.get_int("mesh_auto", "max_attempts", fallback=1) == 0:
            warnings.append("[mesh_auto] max_attempts=0 enables unbounded adaptive meshing attempts.")

    try:
        loc = cfg.get_vector("snappy", "location_in_mesh")
        chord = cfg.get_float("geometry", "chord")
        x_min = cfg.get_float("domain", "x_min") * chord
        x_max = cfg.get_float("domain", "x_max") * chord
        y_min = cfg.get_float("domain", "y_min") * chord
        y_max = cfg.get_float("domain", "y_max") * chord
        z_min = cfg.get_float("domain", "z_min") * chord
        z_max = cfg.get_float("domain", "z_max") * chord
        if not (x_min < loc[0] < x_max and y_min < loc[1] < y_max and z_min < loc[2] < z_max):
            errors.append("[snappy] location_in_mesh must be strictly inside the background domain.")
    except Exception as exc:
        errors.append(str(exc))

    _validate_distance_refinement(cfg, errors, warnings)
    _validate_sampling(cfg, errors, warnings)
    return ValidationReport(errors=errors, warnings=warnings)


def validate_or_raise(cfg: WorkflowConfig) -> None:
    report = validate_workflow(cfg)
    for warning in report.warnings:
        print(f"[validate] warning: {warning}")
    if report.errors:
        joined = "\n".join(f"- {error}" for error in report.errors)
        raise ValueError(f"Invalid workflow configuration:\n{joined}")


def print_validation_report(report: ValidationReport) -> None:
    if report.ok:
        print("[validate] Configuration OK")
    if report.warnings:
        print("[validate] Warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")
    if report.errors:
        print("[validate] Errors:")
        for error in report.errors:
            print(f"  - {error}")


def _check_positive_float(cfg: WorkflowConfig, section: str, option: str, errors: list[str]) -> None:
    try:
        if cfg.get_float(section, option) <= 0:
            errors.append(f"[{section}] {option} must be > 0.")
    except Exception as exc:
        errors.append(str(exc))


def _check_positive_int(cfg: WorkflowConfig, section: str, option: str, errors: list[str]) -> None:
    try:
        if cfg.get_int(section, option) <= 0:
            errors.append(f"[{section}] {option} must be > 0.")
    except Exception as exc:
        errors.append(str(exc))


def _check_non_negative_int(cfg: WorkflowConfig, section: str, option: str, errors: list[str]) -> None:
    try:
        if cfg.get_int(section, option) < 0:
            errors.append(f"[{section}] {option} must be >= 0.")
    except Exception as exc:
        errors.append(str(exc))


def _check_bounds(
    cfg: WorkflowConfig,
    section: str,
    lower: str,
    upper: str,
    errors: list[str],
) -> None:
    try:
        if cfg.get_float(section, lower) >= cfg.get_float(section, upper):
            errors.append(f"[{section}] {lower} must be lower than {upper}.")
    except Exception as exc:
        errors.append(str(exc))


def _validate_sampling(cfg: WorkflowConfig, errors: list[str], warnings: list[str]) -> None:
    for key in ("alpha_deg", "u_inf", "reynolds", "turbulence_intensity", "turbulence_length_scale", "rho"):
        values = cfg.get_list("sampling", key)
        if not values:
            errors.append(f"[sampling] {key} must not be empty.")
            continue
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                errors.append(f"[sampling] {key} contains a non-numeric value: {value}")
                continue
            if key in {"u_inf", "reynolds", "turbulence_length_scale", "rho"} and number <= 0:
                errors.append(f"[sampling] {key} values must be > 0.")
            if key == "turbulence_intensity" and number < 0:
                errors.append("[sampling] turbulence_intensity values must be >= 0.")

    models = cfg.get_list("sampling", "turbulence_model", cast=str)
    if not models:
        errors.append("[sampling] turbulence_model must not be empty.")
    known = {"laminar", "kOmegaSST", "kEpsilon", "realizableKE", "SpalartAllmaras"}
    for model in models:
        canonical = canonical_turbulence_model(model)
        if canonical not in known:
            warnings.append(f"Turbulence model is not in the built-in alias list: {model}")

    for value in cfg.get_list("sampling", "nu"):
        if str(value).strip().lower() == "auto":
            continue
        try:
            if float(value) <= 0:
                errors.append("[sampling] nu values must be > 0 or auto.")
        except (TypeError, ValueError):
            errors.append(f"[sampling] nu contains an invalid value: {value}")


def _validate_distance_refinement(cfg: WorkflowConfig, errors: list[str], warnings: list[str]) -> None:
    if not cfg.get_bool("distance_refinement", "enabled", fallback=False):
        warnings.append("[distance_refinement] disabled; airfoil refinement will use only surface levels.")
        return
    raw_levels = cfg.get("distance_refinement", "levels", fallback="")
    levels: list[tuple[float, int]] = []
    for item in raw_levels.replace(",", ";").split(";"):
        parts = item.strip().replace(":", " ").split()
        if not parts:
            continue
        if len(parts) != 2:
            errors.append(f"[distance_refinement] invalid level entry: {item.strip()}")
            continue
        try:
            distance = float(parts[0])
            level = int(parts[1])
        except ValueError:
            errors.append(f"[distance_refinement] invalid level entry: {item.strip()}")
            continue
        if distance <= 0:
            errors.append("[distance_refinement] distances must be > 0.")
        if level < 0:
            errors.append("[distance_refinement] refinement levels must be >= 0.")
        levels.append((distance, level))
    if not levels:
        errors.append("[distance_refinement] levels must contain at least one distance/level pair.")
        return
    distances = [distance for distance, _ in levels]
    if distances != sorted(distances):
        warnings.append("[distance_refinement] distances should be sorted from near-wall to far-field.")
