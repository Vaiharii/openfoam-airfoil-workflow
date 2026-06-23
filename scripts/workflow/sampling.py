"""Sampling generation for airfoil studies."""

from __future__ import annotations

import csv
import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import WorkflowConfig
from .files import ensure_dir, write_json
from .openfoam import enrich_sample


SAMPLE_KEYS = (
    "alpha_deg",
    "u_inf",
    "reynolds",
    "turbulence_model",
    "turbulence_intensity",
    "turbulence_length_scale",
    "rho",
    "nu",
)


def generate_samples(cfg: WorkflowConfig) -> list[dict[str, Any]]:
    values = {key: cfg.get_list("sampling", key) for key in SAMPLE_KEYS}
    missing = [key for key, items in values.items() if not items]
    if missing:
        raise ValueError("Missing sampling values for: " + ", ".join(missing))

    prefix = cfg.get("study", "case_prefix", fallback="case_")
    combinations = itertools.product(*(values[key] for key in SAMPLE_KEYS))
    samples = []
    width = 3
    for index, combo in enumerate(combinations):
        sample = dict(zip(SAMPLE_KEYS, combo, strict=True))
        sample["case_id"] = f"{prefix}{index:0{width}d}"
        samples.append(enrich_sample(sample, cfg))
    return samples


def write_sampling_files(
    study_dir: Path,
    samples: list[dict[str, Any]],
    cfg: WorkflowConfig,
    geometry: dict[str, Any],
    config_fingerprint: str,
) -> None:
    ensure_dir(study_dir)
    fieldnames = sorted({key for sample in samples for key in sample.keys()})
    with (study_dir / "sampling.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample)

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "Airfoil CFD sampling",
        "====================",
        "",
        f"Generated UTC: {now}",
        f"Study: {cfg.study_name}",
        f"Airfoil: {geometry['airfoil_name']}",
        f"Family: {geometry['family']}",
        f"Source DAT: {geometry['dat_path']}",
        f"Canonical STL: {geometry['canonical_stl']}",
        f"Base case: {cfg.get('base_case', 'template_dir')}",
        f"Number of cases: {len(samples)}",
        "",
        "Cases:",
    ]
    for sample in samples:
        lines.append(
            "- {case_id}: alpha={alpha_deg} deg, U={u_inf} m/s, Re={reynolds}, "
            "model={turbulence_model}, nu={nu}".format(**sample)
        )
    (study_dir / "sampling.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_json(
        study_dir / "campaign.json",
        {
            "generated_utc": now,
            "study": cfg.study_name,
            "config_fingerprint": config_fingerprint,
            "geometry": geometry,
            "samples": samples,
        },
    )


def read_sampling_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
