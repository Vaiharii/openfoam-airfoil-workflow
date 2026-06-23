# Base cases

OpenFOAM templates live here. The default template is
`simpleFoam_airfoil`, a reusable incompressible RANS airfoil case.

Generated study cases are written under `runs/`; the workflow may copy the
selected `geometry.stl` into the template's `constant/triSurface/` folder for
convenience, but the heavy mesh and solver outputs should stay out of this
directory.
