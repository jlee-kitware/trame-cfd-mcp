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

    # Compute per-cell area
    n_cells = inp.GetNumberOfCells()
    areas = np.zeros(n_cells)
    for i in range(n_cells):
        cell = inp.GetCell(i)
        if hasattr(cell, 'ComputeArea'):
            areas[i] = cell.ComputeArea()
        else:
            pts = vtk_to_numpy(cell.GetPoints().GetData())
            if len(pts) >= 3:
                v1 = pts[1] - pts[0]
                v2 = pts[2] - pts[0]
                areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))

    # If pressure is point data, average to cells
    if not use_cell_pressure:
        cell_pressure = np.zeros(n_cells)
        for i in range(n_cells):
            cell = inp.GetCell(i)
            ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
            cell_pressure[i] = np.mean(pressure[ids])
        pressure = cell_pressure

    # Force = sum(p * normal * area) over all cells
    force_density = pressure[:, np.newaxis] * normals * areas[:, np.newaxis]
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
    _add_scalar(tbl, "total_surface_area",   float(areas.sum()))
