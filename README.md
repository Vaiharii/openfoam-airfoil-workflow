# OpenFOAM Airfoil Workflow

Automated Python workflow for CFD studies of airfoil geometries using OpenFOAM.

This project aims to automate the generation, meshing and execution of CFD simulations for airfoil profiles. Starting from a reference OpenFOAM case, the workflow selects a geometry, inserts it into the case, generates the mesh, creates a set of simulation cases from a sampling definition, launches the computations and prepares the structure for future post-processing.

The workflow is designed for reproducible parametric studies, turbulence model comparisons and future uncertainty quantification campaigns.

---

## 1. Project objective

The objective is to build a robust and reproducible CFD pipeline for airfoil studies.

The current workflow supports:

* selection of an airfoil geometry;
* automatic insertion of the STL geometry into a base OpenFOAM case;
* mesh generation from the base case;
* duplication of the meshed case into several simulation samples;
* automatic creation of a sampling database;
* execution of the generated simulations;
* use of marker files to avoid repeating completed steps.

Post-processing is not yet implemented and will be added later.

---

## 2. General workflow

The workflow follows the sequence:

```text
Base OpenFOAM case
        ↓
Geometry selection
        ↓
STL copied as geometry.stl
        ↓
Mesh generation
        ↓
Reference meshed case
        ↓
Sampling generation
        ↓
Case generation in runs/
        ↓
Simulation execution
        ↓
Post-processing
```

The important idea is that the base case acts as a clean template. The selected geometry is inserted into this case, the mesh is generated once, and the resulting meshed case is then copied and modified according to the requested samples.

---

## 3. Directory structure

```text
openfoam-airfoil-workflow/

├── airfoils/
│   ├── database/
│   └── generated/
│
├── base_cases/
│   └── simpleFoam/
│
├── parameters/
│   ├── parameters_geometry.ini
│   ├── parameters_mesh.ini
│   ├── parameters_sampling.ini
│   ├── parameters_runs.ini
│   └── parameters_post.ini
│
├── runs/
│   └── study_name/
│       ├── case_000/
│       ├── case_001/
│       ├── case_002/
│       ├── sampling.csv
│       └── sampling.txt
│
├── results/
│   └── study_name/
│
├── scripts/
│   ├── geometry/
│   ├── mesh/
│   ├── sampling/
│   ├── cases/
│   ├── runs/
│   ├── post/
│   └── utils/
│
├── main.py
└── README.md
```

---

## 4. Geometry handling

The selected airfoil geometry must be available as an STL file.

During the workflow, the geometry is copied into the OpenFOAM case under:

```text
constant/triSurface/geometry.stl
```

All geometries are renamed internally as:

```text
geometry.stl
```

This avoids hard-coding the airfoil name inside OpenFOAM dictionaries such as:

```text
snappyHexMeshDict
surfaceFeatureExtractDict
```

This also makes the base case reusable for different profiles without manually editing the OpenFOAM setup.

---

## 5. Mesh generation

The mesh is generated from the base case after insertion of the selected geometry.

Typical OpenFOAM commands are:

```bash
blockMesh
surfaceFeatureExtract
snappyHexMesh -overwrite
checkMesh
```

After successful mesh generation, the marker file:

```text
.meshdone
```

is created inside the meshed reference case.

This file indicates that the mesh generation step has already been completed.

---

## 6. Sampling and case generation

Once the reference mesh is available, the workflow creates the requested number of simulation cases.

Each generated case is copied into:

```text
runs/study_name/
```

with the structure:

```text
runs/study_name/

├── case_000/
├── case_001/
├── case_002/
└── ...
```

Each case corresponds to one sample of the study.

The variable parameters may include, for example:

* angle of attack;
* inlet velocity;
* Reynolds number;
* turbulence model;
* turbulence intensity;
* numerical schemes;
* mesh settings;
* physical properties.

The workflow also creates two summary files.

### sampling.csv

Machine-readable file containing all generated samples and their parameter values.

Example:

```csv
case,airfoil,alpha,Uinf,Re,turbulence_model
case_000,naca4412,0,20,1000000,kOmegaSST
case_001,naca4412,2,20,1000000,kOmegaSST
case_002,naca4412,4,20,1000000,kOmegaSST
```

### sampling.txt

Human-readable file describing the study.

It summarizes:

* selected geometry;
* base case;
* solver;
* turbulence model;
* number of samples;
* variable parameters;
* parameter ranges;
* date of generation.

After the sampling and case generation stage is completed, the marker file:

```text
.samplingdone
```

is created.

---

## 7. Simulation execution

The generated cases can then be executed automatically.

Depending on the configuration, simulations may be launched:

* sequentially;
* locally in parallel;
* on an HPC cluster;
* through a job scheduler such as SLURM.

After all simulations have been completed, the marker file:

```text
.runsdone
```

is created.

This indicates that the simulation campaign has finished.

---

## 8. Marker files

Marker files are used to make the workflow restartable.

| Marker file     | Meaning                                               |
| --------------- | ----------------------------------------------------- |
| `.meshdone`     | The reference mesh has been generated successfully    |
| `.samplingdone` | The simulation cases have been generated successfully |
| `.runsdone`     | The simulations have been executed successfully       |
| `.postdone`     | The post-processing has been completed                |

The marker files allow the workflow to restart from the last completed stage without repeating expensive operations.

---

## 9. Recommended execution logic

A typical execution order is:

```bash
python main.py --mesh
python main.py --sample
python main.py --run
python main.py --post
```

or, once the workflow is mature:

```bash
python main.py --all
```

The workflow should always check whether a marker file already exists before running a step.

For example:

```text
if .meshdone exists:
    skip mesh generation
else:
    generate mesh
```

This makes the pipeline safer, faster and easier to restart.

---

## 10. Current status

The current version focuses on the first stages of the workflow:

* base case preparation;
* STL geometry insertion;
* mesh generation;
* sample generation;
* case duplication;
* simulation launch.

The post-processing stage is planned but not yet implemented.

---

## 11. Planned post-processing features

Future developments will include:

* automatic extraction of lift, drag and moment coefficients;
* computation of aerodynamic polars;
* pressure coefficient distributions;
* wall quantities such as y+;
* convergence analysis;
* residual extraction;
* force coefficient histories;
* automatic database generation;
* comparison between airfoils;
* uncertainty quantification;
* Sobol sensitivity analysis;
* automatic figure generation.

---

## 12. Long-term objective

The long-term objective is to develop a reusable CFD automation framework for airfoil studies.

Although the first applications focus on NACA profiles, the structure is intended to support any STL-based airfoil geometry.

The project is therefore not limited to NACA profiles. It is designed as a general OpenFOAM-based workflow for automated aerodynamic studies.
