# OpenFOAM -- Airfoil -- Workflow

A reproducible and automated OpenFOAM workflow for aerodynamic studies of NACA airfoils.

This repository provides a Python-based framework to generate, run and post-process parametric CFD simulations with OpenFOAM. The main objective is to perform aerodynamic analyses in a fully reproducible and scalable manner.

---

## Features

* Automatic case generation
* Parametric angle-of-attack studies
* Parallel execution
* Automatic post-processing
* Lift and drag coefficient extraction
* Database generation
* Figure generation
* Reproducible workflow architecture

---

## Workflow

```text
Parameters
    ↓
Case generation
    ↓
Mesh generation
    ↓
OpenFOAM simulations
    ↓
Post-processing
    ↓
Database
    ↓
Figures
```

---

## Technologies

* OpenFOAM
* Python
* NumPy
* Pandas
* Matplotlib

---

## Repository structure

```text
openfoam-airfoil-workflow/
│
├── airfoils/
├── base_case/
├── parameters/
├── scripts/
├── runs/
├── results/
├── figures/
├── README.md
├── requirements.txt
└── .gitignore
```

---

## Applications

Typical applications include:

* Lift and drag polar computation
* Parametric studies
* Sensitivity analysis
* Design exploration
* Automated CFD campaigns

---

## Example outputs

* Lift coefficient (C_l)
* Drag coefficient (C_d)
* Aerodynamic efficiency (C_l/C_d)
* Polar curves

---

## Future developments

Planned extensions include:

* Reynolds number studies
* Different turbulence models
* Mesh sensitivity studies
* Uncertainty quantification
* Surrogate models
* Optimization
* Database management
* Automated report generation
* HPC execution support

---

## Requirements

* OpenFOAM
* Python ≥ 3.10
* NumPy
* Pandas
* Matplotlib

---

## Philosophy

The purpose of this repository is not only to perform CFD simulations, but to provide a reusable and reproducible workflow architecture for engineering studies.

The same philosophy can be extended to:

* OpenFOAM
* SU2
* Code_Aster
* CalculiX
* Elmer
* FEniCS

---

## License

MIT License.
