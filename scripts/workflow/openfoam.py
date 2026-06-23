"""OpenFOAM dictionary generation."""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any

from .config import WorkflowConfig
from .files import ensure_dir, write_executable, write_json


CMU = 0.09


def _num(value: Any) -> str:
    return f"{float(value):.12g}"


def _vec(values: tuple[float, float, float] | list[float]) -> str:
    return "(" + " ".join(_num(value) for value in values) + ")"


def _bool(value: bool) -> str:
    return "true" if value else "false"


def canonical_turbulence_model(model: Any) -> str:
    key = str(model).strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "laminar": "laminar",
        "none": "laminar",
        "komegasst": "kOmegaSST",
        "sst": "kOmegaSST",
        "kepsilon": "kEpsilon",
        "realizablekepsilon": "realizableKE",
        "spalartallmaras": "SpalartAllmaras",
        "sa": "SpalartAllmaras",
    }
    return aliases.get(key, str(model).strip())


def enrich_sample(sample: dict[str, Any], cfg: WorkflowConfig) -> dict[str, Any]:
    chord = cfg.get_float("geometry", "chord")
    span = cfg.get_float("geometry", "span")
    alpha = float(sample["alpha_deg"])
    u_inf = float(sample["u_inf"])
    reynolds = float(sample["reynolds"])
    intensity = float(sample["turbulence_intensity"])
    length_scale = float(sample["turbulence_length_scale"])
    rho = float(sample["rho"])
    model = canonical_turbulence_model(sample["turbulence_model"])

    if chord <= 0:
        raise ValueError("Chord must be strictly positive.")
    if span <= 0:
        raise ValueError("Span must be strictly positive.")
    if u_inf <= 0:
        raise ValueError("u_inf must be strictly positive.")
    if reynolds <= 0:
        raise ValueError("reynolds must be strictly positive.")
    if intensity < 0:
        raise ValueError("turbulence_intensity must be positive or zero.")
    if length_scale <= 0:
        raise ValueError("turbulence_length_scale must be strictly positive.")
    if rho <= 0:
        raise ValueError("rho must be strictly positive.")

    if str(sample["nu"]).strip().lower() == "auto":
        nu = u_inf * chord / reynolds
    else:
        nu = float(sample["nu"])
    if nu <= 0:
        raise ValueError("nu must be strictly positive or auto.")

    alpha_rad = math.radians(alpha)
    ux = u_inf * math.cos(alpha_rad)
    uy = u_inf * math.sin(alpha_rad)
    k = max(1.5 * (u_inf * intensity) ** 2, 1.0e-12)
    omega = max(math.sqrt(k) / (CMU**0.25 * length_scale), 1.0e-12)
    epsilon = max((CMU**0.75) * (k**1.5) / length_scale, 1.0e-12)
    nu_tilda = max(3.0 * nu, 1.0e-12)
    drag_dir = (math.cos(alpha_rad), math.sin(alpha_rad), 0.0)
    lift_dir = (-math.sin(alpha_rad), math.cos(alpha_rad), 0.0)

    ref_len_raw = cfg.get("reference", "reference_length", fallback="auto")
    ref_area_raw = cfg.get("reference", "reference_area", fallback="auto")
    reference_length = chord if ref_len_raw.lower() == "auto" else float(ref_len_raw)
    reference_area = chord * span if ref_area_raw.lower() == "auto" else float(ref_area_raw)

    enriched = dict(sample)
    enriched.update(
        {
            "alpha_deg": alpha,
            "u_inf": u_inf,
            "reynolds": reynolds,
            "turbulence_intensity": intensity,
            "turbulence_length_scale": length_scale,
            "rho": rho,
            "nu": nu,
            "turbulence_model": model,
            "u_x": ux,
            "u_y": uy,
            "u_z": 0.0,
            "k": k,
            "omega": omega,
            "epsilon": epsilon,
            "nu_tilda": nu_tilda,
            "drag_dir_x": drag_dir[0],
            "drag_dir_y": drag_dir[1],
            "drag_dir_z": drag_dir[2],
            "lift_dir_x": lift_dir[0],
            "lift_dir_y": lift_dir[1],
            "lift_dir_z": lift_dir[2],
            "reference_length": reference_length,
            "reference_area": reference_area,
        }
    )
    return enriched


def _foam_header(class_name: str, object_name: str, location: str) -> str:
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| OpenFOAM airfoil workflow                                                   |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    location    "{location}";
    object      {object_name};
}}
// ************************************************************************* //

"""


def _field_file(
    name: str,
    field_class: str,
    dimensions: str,
    internal_field: str,
    boundary: str,
) -> str:
    return (
        _foam_header(field_class, name, "0")
        + f"""dimensions      {dimensions};

internalField   {internal_field};

boundaryField
{{
{boundary}
}}

// ************************************************************************* //
"""
    )


def _scalar_boundary(inlet_value: float, wall: str) -> str:
    return f"""    inlet
    {{
        type            fixedValue;
        value           uniform {_num(inlet_value)};
    }}
    outlet
    {{
        type            zeroGradient;
    }}
    topAndBottom
    {{
        type            fixedValue;
        value           uniform {_num(inlet_value)};
    }}
    front
    {{
        type            symmetryPlane;
    }}
    back
    {{
        type            symmetryPlane;
    }}
    airfoil
    {{
{wall}
    }}
"""


def _zero_gradient_wall() -> str:
    return """        type            zeroGradient;"""


def _fixed_wall(value: float) -> str:
    return f"""        type            fixedValue;
        value           uniform {_num(value)};"""


def _wall_function(name: str, value: float) -> str:
    return f"""        type            {name};
        value           uniform {_num(value)};"""


def _u_file(sample: dict[str, Any]) -> str:
    velocity = _vec([sample["u_x"], sample["u_y"], sample["u_z"]])
    boundary = f"""    inlet
    {{
        type            fixedValue;
        value           uniform {velocity};
    }}
    outlet
    {{
        type            zeroGradient;
    }}
    topAndBottom
    {{
        type            fixedValue;
        value           uniform {velocity};
    }}
    front
    {{
        type            symmetryPlane;
    }}
    back
    {{
        type            symmetryPlane;
    }}
    airfoil
    {{
        type            noSlip;
    }}
"""
    return _field_file("U", "volVectorField", "[0 1 -1 0 0 0 0]", f"uniform {velocity}", boundary)


def _p_file() -> str:
    boundary = """    inlet
    {
        type            zeroGradient;
    }
    outlet
    {
        type            fixedValue;
        value           uniform 0;
    }
    topAndBottom
    {
        type            zeroGradient;
    }
    front
    {
        type            symmetryPlane;
    }
    back
    {
        type            symmetryPlane;
    }
    airfoil
    {
        type            zeroGradient;
    }
"""
    return _field_file("p", "volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0", boundary)


def _nut_file() -> str:
    boundary = """    inlet
    {
        type            calculated;
        value           uniform 0;
    }
    outlet
    {
        type            calculated;
        value           uniform 0;
    }
    topAndBottom
    {
        type            calculated;
        value           uniform 0;
    }
    front
    {
        type            symmetryPlane;
    }
    back
    {
        type            symmetryPlane;
    }
    airfoil
    {
        type            nutkWallFunction;
        value           uniform 0;
    }
"""
    return _field_file("nut", "volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0", boundary)


def _k_file(sample: dict[str, Any]) -> str:
    value = float(sample["k"])
    return _field_file(
        "k",
        "volScalarField",
        "[0 2 -2 0 0 0 0]",
        f"uniform {_num(value)}",
        _scalar_boundary(value, _wall_function("kqRWallFunction", value)),
    )


def _omega_file(sample: dict[str, Any]) -> str:
    value = float(sample["omega"])
    return _field_file(
        "omega",
        "volScalarField",
        "[0 0 -1 0 0 0 0]",
        f"uniform {_num(value)}",
        _scalar_boundary(value, _wall_function("omegaWallFunction", value)),
    )


def _epsilon_file(sample: dict[str, Any]) -> str:
    value = float(sample["epsilon"])
    return _field_file(
        "epsilon",
        "volScalarField",
        "[0 2 -3 0 0 0 0]",
        f"uniform {_num(value)}",
        _scalar_boundary(value, _wall_function("epsilonWallFunction", value)),
    )


def _nu_tilda_file(sample: dict[str, Any]) -> str:
    value = float(sample["nu_tilda"])
    return _field_file(
        "nuTilda",
        "volScalarField",
        "[0 2 -1 0 0 0 0]",
        f"uniform {_num(value)}",
        _scalar_boundary(value, _fixed_wall(0.0)),
    )


def _transport_properties(sample: dict[str, Any]) -> str:
    return (
        _foam_header("dictionary", "transportProperties", "constant")
        + f"""transportModel  Newtonian;

nu              [0 2 -1 0 0 0 0] {_num(sample["nu"])};

// ************************************************************************* //
"""
    )


def _turbulence_properties(sample: dict[str, Any]) -> str:
    model = sample["turbulence_model"]
    if model == "laminar":
        body = "simulationType  laminar;\n"
    else:
        body = f"""simulationType  RAS;

RAS
{{
    RASModel        {model};
    turbulence      on;
    printCoeffs     on;
}}
"""
    return _foam_header("dictionary", "turbulenceProperties", "constant") + body + "\n// ************************************************************************* //\n"


def _block_mesh_dict(cfg: WorkflowConfig) -> str:
    chord = cfg.get_float("geometry", "chord")
    x0 = cfg.get_float("domain", "x_min") * chord
    x1 = cfg.get_float("domain", "x_max") * chord
    y0 = cfg.get_float("domain", "y_min") * chord
    y1 = cfg.get_float("domain", "y_max") * chord
    z0 = cfg.get_float("domain", "z_min") * chord
    z1 = cfg.get_float("domain", "z_max") * chord
    nx = cfg.get_int("domain", "cells_x")
    ny = cfg.get_int("domain", "cells_y")
    nz = cfg.get_int("domain", "cells_z")
    return (
        _foam_header("dictionary", "blockMeshDict", "system")
        + f"""scale   1;

vertices
(
    ({_num(x0)} {_num(y0)} {_num(z0)})
    ({_num(x1)} {_num(y0)} {_num(z0)})
    ({_num(x1)} {_num(y1)} {_num(z0)})
    ({_num(x0)} {_num(y1)} {_num(z0)})
    ({_num(x0)} {_num(y0)} {_num(z1)})
    ({_num(x1)} {_num(y0)} {_num(z1)})
    ({_num(x1)} {_num(y1)} {_num(z1)})
    ({_num(x0)} {_num(y1)} {_num(z1)})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    inlet
    {{
        type patch;
        faces ((0 4 7 3));
    }}
    outlet
    {{
        type patch;
        faces ((1 2 6 5));
    }}
    topAndBottom
    {{
        type patch;
        faces ((3 7 6 2) (0 1 5 4));
    }}
    front
    {{
        type symmetryPlane;
        faces ((0 3 2 1));
    }}
    back
    {{
        type symmetryPlane;
        faces ((4 5 6 7));
    }}
);

mergePatchPairs
(
);

// ************************************************************************* //
"""
    )


def _surface_feature_extract_dict() -> str:
    return (
        _foam_header("dictionary", "surfaceFeatureExtractDict", "system")
        + """geometry.stl
{
    extractionMethod    extractFromSurface;
    extractFromSurfaceCoeffs
    {
        includedAngle   150;
    }
    writeObj            yes;
}

// ************************************************************************* //
"""
    )


def _distance_refinement_levels(cfg: WorkflowConfig) -> list[tuple[float, int]]:
    raw = cfg.get("distance_refinement", "levels", fallback="")
    levels: list[tuple[float, int]] = []
    for item in raw.replace(",", ";").split(";"):
        parts = item.strip().replace(":", " ").split()
        if len(parts) != 2:
            continue
        levels.append((float(parts[0]), int(parts[1])))
    return levels


def _local_refinement_boxes(cfg: WorkflowConfig) -> list[dict[str, Any]]:
    raw = cfg.get("local_refinement", "boxes", fallback="")
    boxes: list[dict[str, Any]] = []
    for index, item in enumerate(raw.split(";"), start=1):
        stripped = item.strip()
        if not stripped:
            continue
        if "|" in stripped:
            parts = [part.strip() for part in stripped.split("|")]
            if len(parts) != 4:
                continue
            name = parts[0]
            minimum = [float(value) for value in parts[1].split()]
            maximum = [float(value) for value in parts[2].split()]
            level = int(parts[3])
        else:
            parts = stripped.split()
            if len(parts) != 8:
                continue
            name = parts[0]
            minimum = [float(value) for value in parts[1:4]]
            maximum = [float(value) for value in parts[4:7]]
            level = int(parts[7])
        if len(minimum) != 3 or len(maximum) != 3:
            continue
        boxes.append(
            {
                "name": _foam_name(name or f"localRefinementBox{index:02d}"),
                "min": tuple(minimum),
                "max": tuple(maximum),
                "level": level,
            }
        )
    return boxes


def _foam_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip())
    if not name:
        return "localRefinementBox"
    if name[0].isdigit():
        return f"box_{name}"
    return name


def _extra_geometry(cfg: WorkflowConfig) -> str:
    boxes = _local_refinement_boxes(cfg)
    if not boxes:
        return ""
    chunks = []
    for box in boxes:
        chunks.append(
            f"""    {box["name"]}
    {{
        type searchableBox;
        min {_vec(list(box["min"]))};
        max {_vec(list(box["max"]))};
    }}"""
        )
    return "\n".join(chunks) + "\n"


def _refinement_regions(cfg: WorkflowConfig, patch: str) -> str:
    entries: list[str] = []
    if cfg.get_bool("distance_refinement", "enabled", fallback=False):
        levels = _distance_refinement_levels(cfg)
        if levels:
            level_lines = "\n".join(f"                ({_num(distance)} {level})" for distance, level in levels)
            entries.append(
                f"""        {patch}
        {{
            mode distance;
            levels
            (
{level_lines}
            );
        }}"""
            )
    for box in _local_refinement_boxes(cfg):
        entries.append(
            f"""        {box["name"]}
        {{
            mode inside;
            levels ((1e15 {box["level"]}));
        }}"""
        )
    if not entries:
        return "    refinementRegions { }\n"
    return """    refinementRegions
    {
""" + "\n".join(entries) + """
    }
"""


def _layer_entries(cfg: WorkflowConfig, patch: str) -> str:
    if not cfg.get_bool("snappy", "add_layers", fallback=False):
        return "    layers { }\n"
    return f"""    layers
    {{
        {patch}
        {{
            nSurfaceLayers {cfg.get_int("layers", "n_surface_layers", fallback=3)};
        }}
    }}
"""


def _snappy_hex_mesh_dict(cfg: WorkflowConfig) -> str:
    patch = cfg.get("snappy", "airfoil_patch")
    loc = cfg.get_vector("snappy", "location_in_mesh")
    extra_geometry = _extra_geometry(cfg)
    refinement_regions = _refinement_regions(cfg, patch)
    layer_entries = _layer_entries(cfg, patch)
    return (
        _foam_header("dictionary", "snappyHexMeshDict", "system")
        + f"""castellatedMesh {_bool(cfg.get_bool("snappy", "castellated_mesh"))};
snap            {_bool(cfg.get_bool("snappy", "snap"))};
addLayers       {_bool(cfg.get_bool("snappy", "add_layers"))};

geometry
{{
    geometry.stl
    {{
        type triSurfaceMesh;
        name {patch};
    }}
{extra_geometry.rstrip()}
}}

castellatedMeshControls
{{
    maxLocalCells       {cfg.get_int("snappy", "max_local_cells")};
    maxGlobalCells      {cfg.get_int("snappy", "max_global_cells")};
    minRefinementCells  {cfg.get_int("snappy", "min_refinement_cells")};
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels {cfg.get_int("snappy", "n_cells_between_levels")};

    features
    (
        {{
            file "geometry.eMesh";
            level {cfg.get_int("snappy", "feature_level")};
        }}
    );

    refinementSurfaces
    {{
        {patch}
        {{
            level ({cfg.get_int("snappy", "surface_level_min")} {cfg.get_int("snappy", "surface_level_max")});
            patchInfo
            {{
                type wall;
            }}
        }}
    }}

    resolveFeatureAngle 30;
{refinement_regions.rstrip()}
    locationInMesh {_vec(list(loc))};
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch        {cfg.get_int("snap", "n_smooth_patch", fallback=3)};
    tolerance           {_num(cfg.get_float("snap", "tolerance", fallback=2.0))};
    nSolveIter          {cfg.get_int("snap", "n_solve_iter", fallback=30)};
    nRelaxIter          {cfg.get_int("snap", "n_relax_iter", fallback=5)};
    nFeatureSnapIter    {cfg.get_int("snap", "n_feature_snap_iter", fallback=10)};
    implicitFeatureSnap {_bool(cfg.get_bool("snap", "implicit_feature_snap", fallback=False))};
    explicitFeatureSnap {_bool(cfg.get_bool("snap", "explicit_feature_snap", fallback=True))};
    multiRegionFeatureSnap {_bool(cfg.get_bool("snap", "multi_region_feature_snap", fallback=False))};
}}

addLayersControls
{{
    relativeSizes       {_bool(cfg.get_bool("layers", "relative_sizes", fallback=True))};
{layer_entries.rstrip()}
    expansionRatio      {_num(cfg.get_float("layers", "expansion_ratio", fallback=1.2))};
    finalLayerThickness {_num(cfg.get_float("layers", "final_layer_thickness", fallback=0.3))};
    minThickness        {_num(cfg.get_float("layers", "min_thickness", fallback=0.1))};
    nGrow               {cfg.get_int("layers", "n_grow", fallback=0)};
    featureAngle        {_num(cfg.get_float("layers", "feature_angle", fallback=60))};
    nRelaxIter          {cfg.get_int("layers", "n_relax_iter", fallback=5)};
    nSmoothSurfaceNormals {cfg.get_int("layers", "n_smooth_surface_normals", fallback=1)};
    nSmoothNormals      {cfg.get_int("layers", "n_smooth_normals", fallback=3)};
    nSmoothThickness    {cfg.get_int("layers", "n_smooth_thickness", fallback=10)};
    maxFaceThicknessRatio {_num(cfg.get_float("layers", "max_face_thickness_ratio", fallback=0.5))};
    maxThicknessToMedialRatio {_num(cfg.get_float("layers", "max_thickness_to_medial_ratio", fallback=0.3))};
    minMedianAxisAngle  {_num(cfg.get_float("layers", "min_median_axis_angle", fallback=90))};
    nBufferCellsNoExtrude {cfg.get_int("layers", "n_buffer_cells_no_extrude", fallback=0)};
    nLayerIter          {cfg.get_int("layers", "n_layer_iter", fallback=50)};
}}

meshQualityControls
{{
    #include "meshQualityDict"
}}

debug           0;
mergeTolerance 1e-6;

// ************************************************************************* //
"""
    )


def _mesh_quality_dict() -> str:
    return (
        _foam_header("dictionary", "meshQualityDict", "system")
        + """maxNonOrtho         65;
maxBoundarySkewness 20;
maxInternalSkewness 4;
maxConcave          80;
minFlatness         0.5;
minVol              1e-13;
minTetQuality       1e-30;
minArea             -1;
minTwist            0.02;
minDeterminant      0.001;
minFaceWeight       0.02;
minVolRatio         0.01;
minTriangleTwist    -1;
nSmoothScale        4;
errorReduction      0.75;

// ************************************************************************* //
"""
    )


def _fv_schemes() -> str:
    return (
        _foam_header("dictionary", "fvSchemes", "system")
        + """ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
}

divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,k)      bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div(phi,nuTilda) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}

wallDist
{
    method          meshWave;
}

// ************************************************************************* //
"""
    )


def _fv_solution() -> str:
    return (
        _foam_header("dictionary", "fvSolution", "system")
        + """solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-7;
        relTol          0.1;
        smoother        GaussSeidel;
    }

    "(U|k|epsilon|omega|nuTilda)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0.1;
    }
}

SIMPLE
{
    consistent          yes;
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p               1e-4;
        U               1e-5;
        "(k|epsilon|omega|nuTilda)" 1e-5;
    }
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
        "(k|epsilon|omega|nuTilda)" 0.7;
    }
}

// ************************************************************************* //
"""
    )


def _force_functions(sample: dict[str, Any], cfg: WorkflowConfig) -> str:
    functions: list[str] = []
    if cfg.get_bool("functions", "force_coefficients", fallback=True):
        cor = cfg.get_vector("reference", "center_of_rotation")
        axis = cfg.get_vector("reference", "pitch_axis")
        drag_dir = (sample["drag_dir_x"], sample["drag_dir_y"], sample["drag_dir_z"])
        lift_dir = (sample["lift_dir_x"], sample["lift_dir_y"], sample["lift_dir_z"])
        functions.append(
            f"""    forceCoeffs
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        writeControl    timeStep;
        writeInterval   1;
        patches         (airfoil);
        rho             rhoInf;
        rhoInf          {_num(sample["rho"])};
        CofR            {_vec(list(cor))};
        liftDir         {_vec(list(lift_dir))};
        dragDir         {_vec(list(drag_dir))};
        pitchAxis       {_vec(list(axis))};
        magUInf         {_num(sample["u_inf"])};
        lRef            {_num(sample["reference_length"])};
        Aref            {_num(sample["reference_area"])};
    }}"""
        )
    if cfg.get_bool("functions", "residuals", fallback=True):
        functions.append(
            """    residuals
    {
        type            residuals;
        libs            ("libutilityFunctionObjects.so");
        writeControl    timeStep;
        writeInterval   1;
        fields          (p U k omega epsilon nuTilda);
    }"""
        )
    if cfg.get_bool("functions", "y_plus", fallback=True):
        functions.append(
            """    yPlus
    {
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
    }"""
        )
    if not functions:
        return "functions\n{\n}\n"
    return "functions\n{\n" + "\n\n".join(functions) + "\n}\n"


def _control_dict(sample: dict[str, Any], cfg: WorkflowConfig) -> str:
    solver = cfg.get("execution", "solver", fallback="simpleFoam")
    return (
        _foam_header("dictionary", "controlDict", "system")
        + f"""application     {solver};

startFrom       startTime;
startTime       {cfg.get("control", "start_time", fallback="0")};
stopAt          endTime;
endTime         {cfg.get("control", "end_time", fallback="1000")};
deltaT          {cfg.get("control", "delta_t", fallback="1")};
writeControl    timeStep;
writeInterval   {cfg.get("control", "write_interval", fallback="100")};
purgeWrite      {cfg.get("control", "purge_write", fallback="0")};
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

{_force_functions(sample, cfg)}

// ************************************************************************* //
"""
    )


def _decompose_par_dict(cfg: WorkflowConfig) -> str:
    n_processors = cfg.get_int("execution", "n_processors", fallback=1)
    return (
        _foam_header("dictionary", "decomposeParDict", "system")
        + f"""numberOfSubdomains {n_processors};

method          scotch;

simpleCoeffs
{{
    n               ({n_processors} 1 1);
    delta           0.001;
}}

distributed     no;
roots           ();

// ************************************************************************* //
"""
    )


def write_case_dictionaries(case_dir: Path, cfg: WorkflowConfig, sample: dict[str, Any]) -> None:
    zero_dir = ensure_dir(case_dir / "0")
    zero_orig_dir = ensure_dir(case_dir / "0.orig")
    constant_dir = ensure_dir(case_dir / "constant")
    system_dir = ensure_dir(case_dir / "system")
    ensure_dir(constant_dir / "triSurface")

    field_files = {
        "U": _u_file(sample),
        "p": _p_file(),
        "nut": _nut_file(),
        "k": _k_file(sample),
        "omega": _omega_file(sample),
        "epsilon": _epsilon_file(sample),
        "nuTilda": _nu_tilda_file(sample),
    }
    for name, text in field_files.items():
        (zero_dir / name).write_text(text, encoding="utf-8")
        (zero_orig_dir / name).write_text(text, encoding="utf-8")

    (constant_dir / "transportProperties").write_text(_transport_properties(sample), encoding="utf-8")
    (constant_dir / "turbulenceProperties").write_text(_turbulence_properties(sample), encoding="utf-8")
    (system_dir / "blockMeshDict").write_text(_block_mesh_dict(cfg), encoding="utf-8")
    (system_dir / "surfaceFeatureExtractDict").write_text(_surface_feature_extract_dict(), encoding="utf-8")
    (system_dir / "snappyHexMeshDict").write_text(_snappy_hex_mesh_dict(cfg), encoding="utf-8")
    (system_dir / "meshQualityDict").write_text(_mesh_quality_dict(), encoding="utf-8")
    (system_dir / "fvSchemes").write_text(_fv_schemes(), encoding="utf-8")
    (system_dir / "fvSolution").write_text(_fv_solution(), encoding="utf-8")
    (system_dir / "controlDict").write_text(_control_dict(sample, cfg), encoding="utf-8")
    (system_dir / "decomposeParDict").write_text(_decompose_par_dict(cfg), encoding="utf-8")
    write_json(case_dir / "case_parameters.json", sample)


def write_allrun_mesh(case_dir: Path, cfg: WorkflowConfig) -> None:
    commands = cfg.get_list("mesh", "commands", cast=str)
    body = "#!/bin/sh\nset -eu\n\n" + "\n".join(commands) + "\n"
    write_executable(case_dir / "Allrun.mesh", body)


def solver_commands(cfg: WorkflowConfig) -> list[str]:
    solver = cfg.get("execution", "solver", fallback="simpleFoam")
    n_processors = cfg.get_int("execution", "n_processors", fallback=1)
    parallel_mode = cfg.get("execution", "parallel", fallback="auto").lower()
    use_parallel = n_processors > 1 if parallel_mode == "auto" else parallel_mode == "true"
    if not use_parallel:
        return [solver]

    commands: list[str] = []
    if cfg.get_bool("execution", "decompose", fallback=True):
        commands.append("decomposePar -force")
    commands.append(f"mpirun -np {n_processors} {solver} -parallel")
    if cfg.get_bool("execution", "reconstruct", fallback=True):
        commands.append("reconstructPar")
    return commands


def write_allrun_solver(case_dir: Path, cfg: WorkflowConfig) -> None:
    body = "#!/bin/sh\nset -eu\n\n" + "\n".join(solver_commands(cfg)) + "\n"
    write_executable(case_dir / "Allrun", body)


def write_slurm_script(case_dir: Path, cfg: WorkflowConfig, sample: dict[str, Any]) -> Path:
    n_tasks = cfg.get_int("execution", "n_processors", fallback=1)
    job_name = f"{cfg.get('slurm', 'job_name_prefix', fallback='airfoil')}_{sample['case_id']}"
    partition = cfg.get("slurm", "partition", fallback="")
    account = cfg.get("slurm", "account", fallback="")
    lines = [
        "#!/bin/sh",
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --time={cfg.get('slurm', 'time', fallback='02:00:00')}",
        f"#SBATCH --nodes={cfg.get('slurm', 'nodes', fallback='1')}",
        f"#SBATCH --ntasks-per-node={cfg.get('slurm', 'ntasks_per_node', fallback=str(n_tasks))}",
        "#SBATCH --output=slurm-%j.out",
    ]
    if partition:
        lines.append(f"#SBATCH --partition={partition}")
    if account:
        lines.append(f"#SBATCH --account={account}")
    lines.extend(["", "set -eu", "cd \"$SLURM_SUBMIT_DIR\""])
    lines.extend(solver_commands(cfg))
    path = case_dir / "submit.slurm"
    write_executable(path, "\n".join(lines) + "\n")
    return path
