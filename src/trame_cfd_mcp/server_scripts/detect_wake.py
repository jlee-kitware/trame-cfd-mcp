# Server-side wake region detection.
# Injected: VELOCITY_FIELD (str), VELOCITY_DEFICIT (float 0-1),
#           STREAMWISE_IDX (int), STREAMWISE_SIGN (int +1/-1),
#           TRAILING_EDGE_COORD (float)  ← downstream boundary of body
#
# Strategy: find cells where velocity magnitude < deficit * freestream,
#           constrained to the downstream half of the domain.
#
# Output: vtkTable with: wake_x, wake_y, wake_z (centroid),
#         wake_xmin, wake_xmax, wake_ymin, wake_ymax, wake_zmin, wake_zmax,
#         freestream_velocity, num_wake_points

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

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
tbl = output

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

vel_vtk = inp.GetPointData().GetArray(VELOCITY_FIELD)
if vel_vtk is None:
    vel_vtk = inp.GetCellData().GetArray(VELOCITY_FIELD)

if vel_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    vel = vtk_to_numpy(vel_vtk)
    mag = np.linalg.norm(vel, axis=1) if vel.ndim > 1 else np.abs(vel.flatten())
    freestream = float(mag.max())
    threshold = VELOCITY_DEFICIT * freestream

    pts_vtk = inp.GetPoints()
    pts = vtk_to_numpy(pts_vtk.GetData()) if pts_vtk else None

    if pts is None or len(pts) != len(mag):
        _add_scalar(tbl, "error", 2.0)
    else:
        # Constrain to downstream of body
        coords = pts[:, STREAMWISE_IDX]
        if STREAMWISE_SIGN > 0:
            downstream_mask = coords > TRAILING_EDGE_COORD
        else:
            downstream_mask = coords < TRAILING_EDGE_COORD

        wake_mask = (mag < threshold) & downstream_mask

        if wake_mask.sum() == 0:
            # Relax: drop spatial constraint
            wake_mask = mag < threshold

        wake_pts = pts[wake_mask] if wake_mask.sum() > 0 else pts[mag < threshold * 1.5]

        if len(wake_pts) == 0:
            centroid = pts.mean(axis=0)
        else:
            centroid = wake_pts.mean(axis=0)

        _add_scalar(tbl, "wake_x", centroid[0])
        _add_scalar(tbl, "wake_y", centroid[1])
        _add_scalar(tbl, "wake_z", centroid[2])
        _add_scalar(tbl, "wake_xmin", float(wake_pts[:, 0].min()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "wake_xmax", float(wake_pts[:, 0].max()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "wake_ymin", float(wake_pts[:, 1].min()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "wake_ymax", float(wake_pts[:, 1].max()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "wake_zmin", float(wake_pts[:, 2].min()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "wake_zmax", float(wake_pts[:, 2].max()) if len(wake_pts) else 0.0)
        _add_scalar(tbl, "freestream_velocity", freestream)
        _add_scalar(tbl, "num_wake_points",     float(wake_mask.sum()))
