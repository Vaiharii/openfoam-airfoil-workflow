# Parameters

The workflow is configured through INI files:

- `parameters_geometry.ini`: airfoil family/code and STL generation options.
- `parameters_mesh.ini`: base case, domain, distance refinement, mesh commands,
  `checkMesh` criteria, and automatic mesh retry settings.
- `parameters_sampling.ini`: study name and parameter sweep.
- `parameters_runs.ini`: local/cluster execution options.
- `parameters_post.ini`: post-processing outputs and OpenFOAM function objects.

All paths are relative to the project root unless they are absolute.

Run `python main.py --validate` after editing these files. It checks that the
selected airfoil exists, the domain is consistent, physical values are positive,
the `snappyHexMesh` location is inside the background mesh, and distance
refinement/checkMesh settings are coherent.

For hands-off meshing, keep `[mesh_auto] estimate_from_stl = true`. The workflow
reads the exact STL, estimates initial mesh parameters, runs `checkMesh`, then
adapts globally and locally from the reported errors. Set
`[mesh_auto] max_attempts = 0` for an unbounded adaptive loop.
