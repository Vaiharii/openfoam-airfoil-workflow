#!/usr/bin/env python3
"""Command-line entry point for the OpenFOAM airfoil workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.workflow.config import WorkflowConfig
from scripts.workflow.pipeline import AirfoilWorkflow
from scripts.workflow.validation import print_validation_report, validate_or_raise, validate_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, mesh, run, and post-process OpenFOAM airfoil cases."
    )
    parser.add_argument("--all", action="store_true", help="Run every workflow stage.")
    parser.add_argument("--geometry", action="store_true", help="Generate/select STL geometry.")
    parser.add_argument("--mesh", action="store_true", help="Prepare and optionally run meshing.")
    parser.add_argument(
        "--sample",
        "--cases",
        dest="sample",
        action="store_true",
        help="Create the sampled case directories in runs/.",
    )
    parser.add_argument("--run", action="store_true", help="Run or prepare simulations.")
    parser.add_argument("--post", action="store_true", help="Post-process available outputs.")
    parser.add_argument("--validate", action="store_true", help="Validate parameters and inputs, then exit.")
    parser.add_argument(
        "--config-dir",
        default="parameters",
        help="Directory containing parameters_*.ini files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print/write planned actions without executing OpenFOAM commands.",
    )
    parser.add_argument(
        "--execute-openfoam",
        action="store_true",
        help="Override INI execution flags and run OpenFOAM commands.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate workflow outputs even when marker files exist.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    selected = [args.geometry, args.mesh, args.sample, args.run, args.post, args.validate]
    if args.all or not any(selected):
        args.geometry = args.mesh = args.sample = args.run = args.post = True

    root = Path(__file__).resolve().parent
    cfg = WorkflowConfig.load(root=root, parameter_dir=root / args.config_dir)
    if args.validate:
        report = validate_workflow(cfg)
        print_validation_report(report)
        return 0 if report.ok else 2

    validate_or_raise(cfg)
    workflow = AirfoilWorkflow(
        cfg=cfg,
        dry_run=args.dry_run,
        force=args.force,
        execute_openfoam=True if args.execute_openfoam else None,
    )

    if args.geometry:
        workflow.geometry()
    if args.mesh:
        workflow.mesh()
    if args.sample:
        workflow.sample()
    if args.run:
        workflow.run()
    if args.post:
        workflow.post()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
