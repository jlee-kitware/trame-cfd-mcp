# Server-side boundary layer profile computation.
# Injected: VELOCITY_FIELD (str), SURFACE_POINT (list [x,y,z]),
#           SURFACE_NORMAL (list [nx,ny,nz]), PROBE_LENGTH (float),
#           NUM_PROBE_POINTS (int)
#
# Input: volume mesh with velocity field.
# Output: vtkTable with one row per probe point:
#   y (wall distance), u (velocity magnitude), u_normalized (u/u_edge),
#   ux, uy, uz (components)
# Plus scalar KPI rows appended after profile:
#   delta, delta_star, theta, shape_factor, u_edge, u_edge_idx

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

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

inp = inputs[0].VTKObject

def get_leaf(ds):
    if hasattr(ds, 'GetNumberOfBlocks'):
        for i in range(ds.GetNumberOfBlocks()):
            block = ds.GetBlock(i)
            if block is not None:
                return get_leaf(block)
    if hasattr(ds, 'GetNumberOfPartitions'):
        if ds.GetNumberOfPartitions() > 0:
            return get_leaf(ds.GetPartition(0))
    return ds

inp = get_leaf(inp)

# Build probe line: SURFACE_POINT + t * SURFACE_NORMAL for t in [0, PROBE_LENGTH]
sp = np.array(SURFACE_POINT)
sn = np.array(SURFACE_NORMAL)
sn = sn / (np.linalg.norm(sn) + 1e-12)

t_vals = np.linspace(0.0, PROBE_LENGTH, NUM_PROBE_POINTS)
probe_pts = sp[np.newaxis, :] + t_vals[:, np.newaxis] * sn[np.newaxis, :]

# Sample velocity at probe points via cell locator
locator = vtk.vtkCellLocator()
locator.SetDataSet(inp)
locator.BuildLocator()

vel_vtk = inp.GetPointData().GetArray(VELOCITY_FIELD)
use_points = vel_vtk is not None
if vel_vtk is None:
    vel_vtk = inp.GetCellData().GetArray(VELOCITY_FIELD)

if vel_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    u_samples = []
    cell_id = vtk.reference(0)
    sub_id = vtk.reference(0)
    dist2 = vtk.reference(0.0)
    pcoords = [0.0, 0.0, 0.0]
    weights = vtk.vtkDoubleArray()

    for pt in probe_pts:
        closest = [0.0, 0.0, 0.0]
        locator.FindClosestPoint(pt.tolist(), closest, cell_id, sub_id, dist2)
        cid = int(cell_id)
        if cid < 0:
            u_samples.append([0.0, 0.0, 0.0])
            continue

        if use_points:
            cell = inp.GetCell(cid)
            n_pts = cell.GetNumberOfPoints()
            u_sum = np.zeros(3)
            for j in range(n_pts):
                pid = cell.GetPointId(j)
                tup = vel_vtk.GetTuple(pid)
                u_sum += np.array(tup[:3])
            u_samples.append((u_sum / n_pts).tolist())
        else:
            tup = vel_vtk.GetTuple(cid)
            u_samples.append(list(tup[:3]))

    u_arr = np.array(u_samples)  # (N, 3)
    umag = np.linalg.norm(u_arr, axis=1)
    y = t_vals

    # Find edge velocity: where d(umag)/dy plateaus (gradient drops below 5% of max)
    if len(umag) > 3:
        grad = np.gradient(umag, y)
        max_grad = np.abs(grad).max()
        plateau = np.abs(grad) < 0.05 * max_grad if max_grad > 0 else np.ones(len(grad), bool)
        plateau_idx = np.where(plateau)[0]
        u_edge_idx = int(plateau_idx[0]) if len(plateau_idx) > 0 else len(umag) - 1
    else:
        u_edge_idx = len(umag) - 1

    u_edge = float(umag[u_edge_idx]) if umag[u_edge_idx] > 0 else float(umag.max())
    if u_edge < 1e-10:
        u_edge = 1.0

    u_norm = umag / u_edge

    # Boundary layer integral thicknesses (integrate only to edge)
    y_bl = y[:u_edge_idx + 1]
    u_bl = u_norm[:u_edge_idx + 1]

    if len(y_bl) > 1:
        delta99_mask = u_bl >= 0.99
        delta = float(y_bl[np.where(delta99_mask)[0][0]]) if delta99_mask.any() else float(y_bl[-1])
        delta_star = float(np.trapezoid(1.0 - u_bl, y_bl))
        theta      = float(np.trapezoid(u_bl * (1.0 - u_bl), y_bl))
        shape_factor = delta_star / theta if theta > 1e-12 else 99.0
    else:
        delta = float(y[-1])
        delta_star = 0.0
        theta = 0.0
        shape_factor = 99.0

    _add_col(tbl, "y",            y.tolist())
    _add_col(tbl, "u",            umag.tolist())
    _add_col(tbl, "u_normalized", u_norm.tolist())
    _add_col(tbl, "ux",           u_arr[:, 0].tolist())
    _add_col(tbl, "uy",           u_arr[:, 1].tolist())
    _add_col(tbl, "uz",           u_arr[:, 2].tolist())

    # Scalar KPIs stored in field data (no row-count constraint)
    def _add_fd_scalar(table, name, value):
        a = vtk.vtkDoubleArray()
        a.SetName(name)
        a.InsertNextValue(float(value))
        table.GetFieldData().AddArray(a)

    _add_fd_scalar(tbl, "delta",        delta)
    _add_fd_scalar(tbl, "delta_star",   delta_star)
    _add_fd_scalar(tbl, "theta",        theta)
    _add_fd_scalar(tbl, "shape_factor", shape_factor)
    _add_fd_scalar(tbl, "u_edge",       u_edge)
    _add_fd_scalar(tbl, "u_edge_idx",   float(u_edge_idx))
    _add_fd_scalar(tbl, "num_points",   float(len(y)))
