#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
date: 06-21-2026
author: @vpagnacco

description:
    Read an airfoil coordinate file in .dat format and generate an
    extruded STL geometry suitable for OpenFOAM meshing.

    The script is intentionally generic. It can be used for NACA profiles,
    Selig profiles, Clark-Y profiles, or any airfoil described by a list
    of 2D coordinates.

dependencies:
    numpy
    numpy-stl
"""

from pathlib import Path

import numpy as np
from stl import mesh

def read_airfoil_dat(path: Path | str) -> np.ndarray:
    """
    Read an airfoil .dat file and extract the 2D coordinates.

    The function ignores all non-numerical lines. This makes it compatible
    with common airfoil coordinate files containing headers or metadata.

    Only lines containing two valid floating-point numbers are kept.

    Parameters
    ----------
    path : Path | str
        Path to the airfoil .dat file.

    Returns
    -------
    np.ndarray
        Array of shape (n_points, 2), where each row contains the
        x and y coordinates of one airfoil point.

    Raises
    ------
    FileNotFoundError
        If the input file does not exist.

    ValueError
        If fewer than three valid points are found.
    """
    path = Path(path)
    print()
    print("=" * 80)
    print("READ AIRFOIL DAT")
    print("=" * 80)
    print(f"Input file : {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Airfoil file not found: {path}")
    points = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            parts = line.strip().replace(",", ".").split()
            if len(parts) != 2:
                continue
            try:
                x = float(parts[0])
                y = float(parts[1])
            except ValueError:
                continue
            points.append((x, y))
    points = np.asarray(points, dtype=float)
    if len(points) < 3:
        raise ValueError(
            f"At least three valid points are required to define an airfoil. "
            f"Only {len(points)} valid point(s) found in {path}."
        )
    print(f"Number of points found : {len(points)}")
    print("Done.")
    return points

def remove_duplicate_closing_point(points: np.ndarray) -> np.ndarray:
    """
    Remove the last point if it is identical to the first one.

    STL generation closes the contour automatically by connecting the last
    point to the first point. Therefore, keeping an already repeated closing
    point may create a degenerate zero-area face.

    Parameters
    ----------
    points : np.ndarray
        Array of shape (n_points, 2) containing the airfoil coordinates.

    Returns
    -------
    np.ndarray
        Airfoil coordinates without a duplicated closing point.
    """
    print()
    print("=" * 80)
    print("REMOVE DUPLICATE CLOSING POINT")
    print("=" * 80)
    if np.allclose(points[0], points[-1]):
        print("Duplicate point detected.")
        print("Removing last point.")
        return points[:-1]
    print("No duplicate point found.")
    return points

def scale_airfoil(points: np.ndarray, chord: float = 1.0) -> np.ndarray:
    """
    Scale the airfoil coordinates using the desired chord length.

    Most airfoil .dat files are normalized with a chord equal to 1.
    This function converts the normalized coordinates into dimensional
    coordinates.

    Parameters
    ----------
    points : np.ndarray
        Array of shape (n_points, 2) containing normalized airfoil
        coordinates.

    chord : float, default=1.0
        Chord length in meters.

    Returns
    -------
    np.ndarray
        Scaled airfoil coordinates.

    Raises
    ------
    ValueError
        If the chord length is not strictly positive.
    """
    if chord <= 0:
        raise ValueError(f"Chord must be strictly positive. Got chord={chord}.")
    print()
    print("=" * 80)
    print("SCALE AIRFOIL")
    print("=" * 80)
    print(f"Chord = {chord} m")
    print()
    print("Before scaling:")
    print(f"x_min = {points[:,0].min()}")
    print(f"x_max = {points[:,0].max()}")
    scaled_points = points * chord
    print()
    print("After scaling:")
    print(f"x_min = {scaled_points[:,0].min()}")
    print(f"x_max = {scaled_points[:,0].max()}")
    print("Done.")
    return scaled_points

def build_front_and_back_faces(
    points: np.ndarray,
    span: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build the front and back 3D point clouds of the extruded airfoil.

    The 2D airfoil is assumed to lie in the (x, y) plane. The extrusion is
    performed along the z direction.

    Parameters
    ----------
    points : np.ndarray
        Array of shape (n_points, 2) containing the 2D airfoil coordinates.

    span : float
        Extrusion length in meters.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Two arrays of shape (n_points, 3):

        - front: airfoil points at z = 0
        - back: airfoil points at z = span

    Raises
    ------
    ValueError
        If the span is not strictly positive.
    """
    print()
    print("=" * 80)
    print("BUILD FRONT AND BACK FACES")
    print("=" * 80)
    print(f"Span = {span} m")
    print(f"Number of points = {len(points)}")
    if span <= 0:
        raise ValueError(f"Span must be strictly positive. Got span={span}.")
    n_points = len(points)
    front = np.column_stack((points[:, 0], points[:, 1], np.full(n_points, -span/2)))
    back = np.column_stack((points[:, 0], points[:, 1], np.full(n_points, span/2)))
    print(f"Front plane z = {-span/2}")
    print(f"Back plane z = {span/2}")
    print("Done.")
    return front, back

def create_lateral_triangles(
    front: np.ndarray,
    back: np.ndarray,
) -> list[list[np.ndarray]]:
    """
    Create the lateral triangles of the extruded airfoil.

    Each segment of the 2D contour generates a quadrilateral surface after
    extrusion. This quadrilateral is split into two triangles.

    Parameters
    ----------
    front : np.ndarray
        Array of shape (n_points, 3) containing the front airfoil section.

    back : np.ndarray
        Array of shape (n_points, 3) containing the back airfoil section.

    Returns
    -------
    list[list[np.ndarray]]
        List of triangular faces. Each triangle is represented by three
        3D points.
    """
    print()
    print("=" * 80)
    print("CREATE LATERAL TRIANGLES")
    print("=" * 80)
    n_points = len(front)
    triangles = []
    for i in range(n_points):
        j = (i + 1) % n_points
        triangles.append([front[i], front[j], back[j]])
        triangles.append([front[i], back[j], back[i]])
    print(f"Number of lateral triangles : {len(triangles)}")
    print("Done.")
    return triangles

def create_cap_triangles(
    face: np.ndarray,
    reverse: bool = False,
) -> list[list[np.ndarray]]:
    """
    Create triangular cap faces for one side of the extruded airfoil.

    The cap is generated using a simple fan triangulation from the geometric
    center of the section.

    This method is sufficient for standard airfoil profiles such as NACA
    sections. For strongly concave or complex geometries, a more robust
    triangulation method should be used.

    Parameters
    ----------
    face : np.ndarray
        Array of shape (n_points, 3) containing one airfoil section.

    reverse : bool, default=False
        If True, reverse the orientation of the generated triangles.
        This is useful to obtain opposite normal directions for the front
        and back caps.

    Returns
    -------
    list[list[np.ndarray]]
        List of triangular faces.
    """
    print()
    print("=" * 80)
    print("CREATE CAP TRIANGLES")
    print("=" * 80)
    print(f"Reverse orientation : {reverse}")
    n_points = len(face)
    center = np.mean(face, axis=0)
    triangles = []
    for i in range(n_points):
        j = (i + 1) % n_points
        if reverse:
            triangles.append([center, face[j], face[i]])
        else:
            triangles.append([center, face[i], face[j]])
    print(f"Number of cap triangles : {len(triangles)}")
    print("Done.")
    return triangles

def write_stl(
    triangles: list[list[np.ndarray]],
    output_path: Path | str,
) -> None:
    """
    Write a list of triangular faces to an STL file.

    Parameters
    ----------
    triangles : list[list[np.ndarray]]
        List of triangular faces. Each triangle must contain three
        3D points.

    output_path : Path | str
        Path of the output STL file.

    Returns
    -------
    None
        The STL mesh is written to disk.

    Raises
    ------
    ValueError
        If no triangle is provided.
    """
    print()
    print("=" * 80)
    print("WRITE STL")
    print("=" * 80)
    print(f"Output path : {output_path}")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(triangles) == 0:
        raise ValueError("Cannot write an STL file without triangles.")
    stl_mesh = mesh.Mesh(np.zeros(len(triangles), dtype=mesh.Mesh.dtype))
    for i, triangle in enumerate(triangles):
        stl_mesh.vectors[i] = np.asarray(triangle, dtype=float)
    print(f"Number of triangles : {len(triangles)}")
    print("Saving STL...")
    stl_mesh.save(str(output_path))
    print("Done.")

def create_airfoil_stl(
    points: np.ndarray,
    output_path: Path | str,
    chord: float = 1.0,
    span: float = 0.05,
) -> None:
    """
    Create an extruded STL airfoil from 2D coordinates.

    The function performs the following operations:

    1. remove duplicated closing point if necessary;
    2. scale the profile using the chord length;
    3. create the front and back sections;
    4. generate lateral triangular faces;
    5. generate front and back cap faces;
    6. write the final STL file.

    Parameters
    ----------
    points : np.ndarray
        Array of shape (n_points, 2) containing airfoil coordinates.

    output_path : Path | str
        Path of the output STL file.

    chord : float, default=1.0
        Chord length in meters.

    span : float, default=0.05
        Extrusion length in meters.

    Returns
    -------
    None
        The STL file is written to disk.
    """
    print()
    print("#" * 80)
    print("CREATE AIRFOIL STL")
    print("#" * 80)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("points must be a 2D NumPy array with shape (n_points, 2).")
    if len(points) < 3:
        raise ValueError("At least three points are required to create an airfoil STL.")
    print("Step 1/5 : remove duplicate closing point")
    points = remove_duplicate_closing_point(points)
    print("Step 2/5 : scale airfoil")
    points = scale_airfoil(points, chord=chord)
    print("Step 3/5 : build front and back faces")
    front, back = build_front_and_back_faces(points, span=span)
    print("Step 4/5 : create triangles")
    triangles = []
    triangles.extend(create_lateral_triangles(front, back))
    triangles.extend(create_cap_triangles(front, reverse=True))
    triangles.extend(create_cap_triangles(back, reverse=False))
    print("Step 5/5 : write STL")
    write_stl(triangles, output_path)
    print()
    print("#" * 80)
    print("END OF STL CREATION")
    print("#" * 80)

def create_airfoil_stl_from_dat(
    input_path: Path | str,
    output_path: Path | str,
    chord: float = 1.0,
    span: float = 0.05,
) -> None:
    """
    Read an airfoil .dat file and generate an extruded STL geometry.

    This is the high-level function intended to be used by the workflow.

    Parameters
    ----------
    input_path : Path | str
        Path to the input .dat airfoil file.

    output_path : Path | str
        Path to the output STL file.

    chord : float, default=1.0
        Chord length in meters.

    span : float, default=0.05
        Extrusion length in meters.

    Returns
    -------
    None
        The STL file is written to disk.
    """
    points = read_airfoil_dat(input_path)
    create_airfoil_stl(
        points=points,
        output_path=output_path,
        chord=chord,
        span=span,
    )

if __name__ == "__main__":
    input_path = Path("airfoils/database/naca4/naca0012.dat")
    output_path = Path("airfoils/generated/geometry.stl")
    create_airfoil_stl_from_dat(
        input_path=input_path,
        output_path=output_path,
        chord=1,
        span=0.5,
    )