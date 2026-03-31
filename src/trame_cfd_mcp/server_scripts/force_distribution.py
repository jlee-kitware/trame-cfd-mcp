# Server-side force distribution computation.
# Injected: PRESSURE_FIELD (str), FORCE_IDX (int 0/1/2), DIST_IDX (int 0/1/2),
#           NUM_BINS (int)
#
# Input: surface mesh with cell normals and pressure field.
# Output: vtkTable with columns:
#   station (bin center), sectional_force, accumulated_force, num_cells
# Plus scalar KPIs: total_force, force_axis (int), dist_axis (int)

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

inp = inputs[0].VTKObject
tbl = output

def _add_col(table, name, values):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    for v in values:
        a.InsertNextValue(float(v))
    table.AddColumn(a)

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

p_vtk = inp.GetCellData().GetArray(PRESSURE_FIELD)
use_cell = p_vtk is not None
if p_vtk is None:
    p_vtk = inp.GetPointData().GetArray(PRESSURE_FIELD)
normals_vtk = inp.GetCellData().GetArray("Normals")

if p_vtk is None or normals_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    n_cells = inp.GetNumberOfCells()
    normals  = vtk_to_numpy(normals_vtk)    # (N,3)
    pressure = vtk_to_numpy(p_vtk)          # (N,) cell or (M,) point

    centers = np.zeros((n_cells, 3))
    areas   = np.zeros(n_cells)

    for i in range(n_cells):
        cell = inp.GetCell(i)
        pts = vtk_to_numpy(cell.GetPoints().GetData())
        centers[i] = pts.mean(axis=0)
        if len(pts) >= 3:
            v1 = pts[1] - pts[0]
            v2 = pts[2] - pts[0]
            areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))

    if not use_cell:
        cell_p = np.zeros(n_cells)
        for i in range(n_cells):
            cell = inp.GetCell(i)
            ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
            cell_p[i] = np.mean(pressure[ids])
        pressure = cell_p

    # Force contribution per cell along FORCE_IDX
    force_per_cell = pressure * normals[:, FORCE_IDX] * areas  # (N,)
    dist_coords    = centers[:, DIST_IDX]

    # Bin by distribution axis
    d_min, d_max = dist_coords.min(), dist_coords.max()
    bins = np.linspace(d_min, d_max, NUM_BINS + 1)
    centers_bin = 0.5 * (bins[:-1] + bins[1:])

    sectional  = np.zeros(NUM_BINS)
    cell_count = np.zeros(NUM_BINS, dtype=int)

    for i, f in enumerate(force_per_cell):
        idx = np.searchsorted(bins[1:], dist_coords[i])
        idx = min(idx, NUM_BINS - 1)
        sectional[idx] += f
        cell_count[idx] += 1

    accumulated = np.cumsum(sectional)
    total = float(force_per_cell.sum())

    _add_col(tbl, "station",           centers_bin.tolist())
    _add_col(tbl, "sectional_force",   sectional.tolist())
    _add_col(tbl, "accumulated_force", accumulated.tolist())
    _add_col(tbl, "num_cells",         cell_count.tolist())
    _add_scalar(tbl, "total_force", total)
    _add_scalar(tbl, "force_axis",  float(FORCE_IDX))
    _add_scalar(tbl, "dist_axis",   float(DIST_IDX))
