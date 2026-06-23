# simpleFoam_airfoil base case

This directory is the clean OpenFOAM template used by the workflow.

The Python workflow writes the final dictionaries into copied cases under
`runs/<study>/`, so this template stays intentionally minimal and reusable.
The selected STL is copied into:

```text
constant/triSurface/geometry.stl
```

Patch convention:

- `inlet`
- `outlet`
- `topAndBottom`
- `front`
- `back`
- `airfoil`
