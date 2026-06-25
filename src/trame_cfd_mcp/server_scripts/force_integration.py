# Server-side force integration over surface mesh.
# Injected: PRESSURE_FIELD (str), STREAMWISE_IDX (int 0/1/2), LIFT_IDX (int 0/1/2),
#           FREESTREAM_VELOCITY (float), REFERENCE_AREA (float), DENSITY (float)
#
# Input: surface mesh with cell normals and pressure field.
# Output: vtkTable with: Fx, Fy, Fz, drag, lift, Cd, Cl, reference_area, freestream_velocity

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

inp = inputs[0].VTKObject

tbl = output

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

# Get pressure (cell or point data)
p_vtk = inp.GetCellData().GetArray(PRESSURE_FIELD)
use_cell_pressure = p_vtk is not None
if p_vtk is None:
    p_vtk = inp.GetPointData().GetArray(PRESSURE_FIELD)

normals_vtk = inp.GetCellData().GetArray("Normals")

if p_vtk is None or normals_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    normals = vtk_to_numpy(normals_vtk)       # (N_cells, 3)
    pressure = vtk_to_numpy(p_vtk)             # (N_cells,) or (N_pts,)

    # Compute per-cell area and center, then apply body mask to exclude farfield faces
    n_cells = inp.GetNumberOfCells()
    areas   = np.zeros(n_cells)
    centers = np.zeros((n_cells, 3))
    for i in range(n_cells):
        cell = inp.GetCell(i)
        pts = vtk_to_numpy(cell.GetPoints().GetData())
        centers[i] = pts.mean(axis=0)
        if hasattr(cell, 'ComputeArea'):
            areas[i] = cell.ComputeArea()
        else:
            if len(pts) >= 3:
                v1 = pts[1] - pts[0]
                v2 = pts[2] - pts[0]
                areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))

    # Exclude farfield faces (same margin strategy as force_distribution.py)
    bounds = inp.GetBounds()
    margin_frac = 0.02
    body_mask = np.ones(n_cells, dtype=bool)
    for ax in range(3):
        lo = bounds[ax * 2]     + margin_frac * (bounds[ax * 2 + 1] - bounds[ax * 2])
        hi = bounds[ax * 2 + 1] - margin_frac * (bounds[ax * 2 + 1] - bounds[ax * 2])
        body_mask &= (centers[:, ax] > lo) & (centers[:, ax] < hi)

    # If pressure is point data, average to cells
    if not use_cell_pressure:
        cell_pressure = np.zeros(n_cells)
        for i in range(n_cells):
            cell = inp.GetCell(i)
            ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
            cell_pressure[i] = np.mean(pressure[ids])
        pressure = cell_pressure

    # Apply body mask before integration
    normals  = normals[body_mask]
    pressure = pressure[body_mask]
    areas    = areas[body_mask]

    # Force = -sum(p * normal * area) — pressure acts inward, normals are outward
    force_density = -pressure[:, np.newaxis] * normals * areas[:, np.newaxis]
    F = force_density.sum(axis=0)   # [Fx, Fy, Fz]

    drag = F[STREAMWISE_IDX]
    lift = F[LIFT_IDX]

    q = 0.5 * DENSITY * FREESTREAM_VELOCITY ** 2
    Cd = drag / (q * REFERENCE_AREA) if q * REFERENCE_AREA > 0 else 0.0
    Cl = lift / (q * REFERENCE_AREA) if q * REFERENCE_AREA > 0 else 0.0

    _add_scalar(tbl, "Fx",  F[0])
    _add_scalar(tbl, "Fy",  F[1])
    _add_scalar(tbl, "Fz",  F[2])
    _add_scalar(tbl, "drag", drag)
    _add_scalar(tbl, "lift", lift)
    _add_scalar(tbl, "Cd",  Cd)
    _add_scalar(tbl, "Cl",  Cl)
    _add_scalar(tbl, "reference_area",       REFERENCE_AREA)
    _add_scalar(tbl, "freestream_velocity",  FREESTREAM_VELOCITY)
    _add_scalar(tbl, "total_surface_area",   float(areas.sum()))  # body cells only
