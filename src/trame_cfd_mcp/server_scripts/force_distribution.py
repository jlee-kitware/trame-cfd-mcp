# Server-side force distribution computation.
# Injected: PRESSURE_FIELD (str), FORCE_IDX (int 0/1/2), LIFT_IDX (int 0/1/2),
#           DIST_IDX (int 0/1/2), NUM_BINS (int)
#
# Input: surface mesh with cell normals and pressure field.
# Output: vtkTable with columns (NUM_BINS rows each):
#   station, sectional_drag, accumulated_drag, sectional_lift, accumulated_lift, num_cells
# Plus FieldData scalars: total_drag, total_lift, force_axis, lift_axis, dist_axis,
#                         num_body_cells, num_total_cells, margin_frac

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

p_vtk = inp.GetCellData().GetArray(PRESSURE_FIELD)
use_cell = p_vtk is not None
if p_vtk is None:
    p_vtk = inp.GetPointData().GetArray(PRESSURE_FIELD)
normals_vtk = inp.GetCellData().GetArray("Normals")

if p_vtk is None or normals_vtk is None:
    a = vtk.vtkDoubleArray()
    a.SetName("error")
    a.InsertNextValue(1.0)
    tbl.GetFieldData().AddArray(a)
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

    # Force contributions per cell — compute drag and lift in one pass
    drag_per_cell = -pressure * normals[:, FORCE_IDX] * areas  # (N,)
    lift_per_cell = -pressure * normals[:, LIFT_IDX]  * areas  # (N,)
    dist_coords   = centers[:, DIST_IDX]

    # Exclude farfield boundary faces: reject cells whose centers sit within
    # MARGIN of the domain bounds. The input is ExtractSurface on the full
    # domain mesh, which includes both body and farfield faces. Farfield faces
    # dominate the integration if not excluded. Using a fractional margin (2%
    # of each axis extent) is robust across different dataset scales.
    bounds = inp.GetBounds()  # (xmin, xmax, ymin, ymax, zmin, zmax)
    margin_frac = 0.02
    margins = [
        margin_frac * (bounds[1] - bounds[0]),
        margin_frac * (bounds[3] - bounds[2]),
        margin_frac * (bounds[5] - bounds[4]),
    ]
    body_mask = np.ones(n_cells, dtype=bool)
    for ax in range(3):
        lo = bounds[ax * 2]     + margins[ax]
        hi = bounds[ax * 2 + 1] - margins[ax]
        body_mask &= (centers[:, ax] > lo) & (centers[:, ax] < hi)

    drag_per_cell = drag_per_cell[body_mask]
    lift_per_cell = lift_per_cell[body_mask]
    dist_coords   = dist_coords[body_mask]

    if len(drag_per_cell) == 0:
        a = vtk.vtkDoubleArray()
        a.SetName("error")
        a.InsertNextValue(2.0)  # 2 = no body cells found
        tbl.GetFieldData().AddArray(a)
    else:
        d_min, d_max = dist_coords.min(), dist_coords.max()
        bins = np.linspace(d_min, d_max, NUM_BINS + 1)
        centers_bin = 0.5 * (bins[:-1] + bins[1:])

        sectional_drag = np.zeros(NUM_BINS)
        sectional_lift = np.zeros(NUM_BINS)
        cell_count     = np.zeros(NUM_BINS, dtype=int)

        for i in range(len(drag_per_cell)):
            idx = np.searchsorted(bins[1:], dist_coords[i])
            idx = np.minimum(idx, NUM_BINS - 1)
            sectional_drag[idx] += drag_per_cell[i]
            sectional_lift[idx] += lift_per_cell[i]
            cell_count[idx] += 1

        accumulated_drag = np.cumsum(sectional_drag)
        accumulated_lift = np.cumsum(sectional_lift)

        _add_col(tbl, "station",           centers_bin.tolist())
        _add_col(tbl, "sectional_drag",    sectional_drag.tolist())
        _add_col(tbl, "accumulated_drag",  accumulated_drag.tolist())
        _add_col(tbl, "sectional_lift",    sectional_lift.tolist())
        _add_col(tbl, "accumulated_lift",  accumulated_lift.tolist())
        _add_col(tbl, "num_cells",         cell_count.tolist())

        def _add_fd_scalar(table, name, value):
            a = vtk.vtkDoubleArray()
            a.SetName(name)
            a.InsertNextValue(float(value))
            table.GetFieldData().AddArray(a)

        _add_fd_scalar(tbl, "total_drag",      float(drag_per_cell.sum()))
        _add_fd_scalar(tbl, "total_lift",      float(lift_per_cell.sum()))
        _add_fd_scalar(tbl, "force_axis",      float(FORCE_IDX))
        _add_fd_scalar(tbl, "lift_axis",       float(LIFT_IDX))
        _add_fd_scalar(tbl, "dist_axis",       float(DIST_IDX))
        _add_fd_scalar(tbl, "num_body_cells",  float(np.sum(body_mask)))
        _add_fd_scalar(tbl, "num_total_cells", float(n_cells))
        _add_fd_scalar(tbl, "margin_frac",     float(margin_frac))
