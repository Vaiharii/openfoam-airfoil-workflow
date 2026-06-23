# OpenFOAM Airfoil Workflow

Automated Python workflow for CFD campaigns on NACA airfoils with OpenFOAM.

The workflow reads the INI files in `parameters/`, selects an airfoil, creates
the STL, prepares OpenFOAM cases, optionally launches meshing and simulations,
then collects post-processing outputs into `results/`.

The current database contains NACA 4-digit profiles. The code is structured for
future `naca5`, `naca6`, or custom `.dat` profile sources.

## Quick Start

Install the Python dependency used by the STL generator:

```bash
pip install -r requirements.txt
```

Prepare the full campaign without executing OpenFOAM:

```bash
python main.py --all
```

Validate parameters and input files without generating cases:

```bash
python main.py --validate
```

This creates:

```text
airfoils/generated/geometry.stl
runs/<study>/_mesh_reference/
runs/<study>/case_000/
runs/<study>/case_001/
runs/<study>/sampling.csv
results/<study>/summary.csv
```

Run selected stages:

```bash
python main.py --geometry
python main.py --mesh
python main.py --sample
python main.py --run
python main.py --post
```

Force regeneration:

```bash
python main.py --all --force
```

Execute OpenFOAM commands regardless of the INI execution flags:

```bash
python main.py --mesh --execute-openfoam
python main.py --run --execute-openfoam
```

## Parameters

All user-facing configuration lives in `parameters/`.

| File | Purpose |
| --- | --- |
| `parameters_geometry.ini` | Airfoil family/code, chord, span, STL output. |
| `parameters_mesh.ini` | Base case, domain size, `snappyHexMesh` controls, mesh commands. |
| `parameters_sampling.ini` | Study name and sampled values: alpha, velocity, Reynolds, turbulence model, etc. |
| `parameters_runs.ini` | Execution mode: `prepare_only`, `local`, or `slurm`; CPUs; solver; time controls. |
| `parameters_post.ini` | Requested function objects and post-processing outputs. |

Most lists are comma-separated. Mesh commands are semicolon-separated.

Example alpha sweep:

```ini
[sampling]
alpha_deg = -4, 0, 4, 8, 12
u_inf = 20.0
reynolds = 1000000
turbulence_model = kOmegaSST
```

## Execution Modes

`prepare_only` is the safe default. It writes cases and scripts but does not call
OpenFOAM.

For local execution, set:

```ini
[execution]
mode = local
execute = true
n_processors = 4
parallel = auto
max_workers = 1

[mesh]
execute = true
```

With `n_processors > 1`, simulation scripts use:

```text
decomposePar -force
mpirun -np <n_processors> simpleFoam -parallel
reconstructPar
```

For a cluster, set:

```ini
[execution]
mode = slurm
execute = true

[slurm]
submit = true
partition = your_partition
time = 02:00:00
```

The workflow writes `submit.slurm` in each case directory and can submit it with
`sbatch`.

## Workflow Stages

1. Geometry
   - Reads the selected `.dat` profile from `airfoils/database/<family>/`.
   - Writes `airfoils/generated/geometry.stl`.
   - Optionally writes a named STL such as `naca4412.stl`.
   - Copies the canonical STL into `constant/triSurface/geometry.stl`.

2. Mesh
   - Copies `base_cases/simpleFoam_airfoil` into
     `runs/<study>/_mesh_reference`.
   - Writes OpenFOAM dictionaries for `blockMesh`, `surfaceFeatureExtract`,
     `snappyHexMesh`, `checkMesh`, fields, turbulence and function objects.
   - Uses `snappyHexMesh` distance refinement around the airfoil and runs
     `checkMesh -allTopology -allGeometry -writeSets vtk`.
   - When `[mesh_auto] enabled = true`, rejects meshes below the configured
     cell target or with failed mesh checks, adjusts obvious refinement/snap
     parameters, and retries. Attempts are recorded in
     `runs/<study>/_mesh_reference/mesh_attempts.json`.
   - When `[mesh_auto] estimate_from_stl = true`, the exact STL is read before
     meshing. The workflow estimates the background domain, base cell counts,
     `locationInMesh`, surface levels, and distance refinement distances from
     the STL bounds and edge sizes.
   - With `[local_refinement] enabled = true`, checkMesh error coordinates or
     VTK error sets are converted into local `searchableBox` refinement regions
     for the next attempt. This lets the mesh adapt to skewness/non-orthogonality
     issues instead of only refining globally.
   - Runs mesh commands only when execution is enabled.

3. Sampling and case generation
   - Builds a Cartesian product of sampled parameters.
   - Creates `case_000`, `case_001`, ...
   - Writes per-case `0/`, `constant/`, `system/`, `Allrun`, `Allrun.mesh`,
     and `case_parameters.json`.
   - Writes `sampling.csv`, `sampling.txt`, and `campaign.json`.

4. Run
   - Prepares local or SLURM execution scripts.
   - Optionally launches `simpleFoam`.
   - Supports MPI decomposition and multiple local case workers.

5. Post
   - Reads available `forceCoeffs`, `yPlus`, residual files, and solver logs.
   - Writes `results/<study>/summary.csv`, `case_status.csv`, and
     `post_report.md`.
   - Missing solver outputs are handled gracefully, so prepared-only campaigns
     still produce a useful status table.

## Restart Markers

Generated folders use marker files to avoid repeating expensive steps.

| Marker | Meaning |
| --- | --- |
| `.meshprepared` | Reference mesh case was prepared but not meshed. |
| `.meshdone` | Mesh commands completed successfully. |
| `.samplingdone` | Case directories and sampling files were generated. |
| `.runprepared` | Run scripts were prepared but simulations were not launched. |
| `.runsdone` | Local simulations completed successfully. |
| `.postdone` | Post-processing completed. |

The workflow stores configuration fingerprints in generated campaign, mesh, and
result metadata. If relevant parameters change, stale prepared outputs are
regenerated instead of being silently reused.

Use `--force` when you intentionally want to regenerate outputs regardless of
marker state.

## Airfoil Families

Current supported database layout:

```text
airfoils/database/naca4/naca4412.dat
airfoils/database/naca5/naca23012.dat
airfoils/database/naca6/naca63xxx.dat
```

Only `naca4` is populated today. For future families, add the coordinate files
under the matching folder and set `family` and `code` in
`parameters_geometry.ini`.

For an arbitrary profile:

```ini
[airfoil]
source = custom
custom_dat_path = path/to/profile.dat
```

The STL generator accepts any two-column airfoil coordinate file.
