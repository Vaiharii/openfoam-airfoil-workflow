#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
author: @vpagnacco

description:

"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

AIRFOILS_DIR = ROOT / "airfoils"
BASE_CASES_DIR = ROOT / "base_cases"
GEOMETRIES_DIR = ROOT / "geometries"
PARAMETERS_DIR = ROOT / "parameters"
RESULTS_DIR = ROOT / "results"
RUNS_DIR = ROOT / "runs"