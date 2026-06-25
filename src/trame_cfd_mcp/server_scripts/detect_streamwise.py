# Server-side streamwise direction detection.
# Injected: VELOCITY_FIELD (str)
#
# Detects primary flow direction from velocity field statistics.
# Strategy: the streamwise axis is the one with the largest velocity component variance.
#
# Output: vtkTable with: streamwise_axis (0/1/2 → x/y/z), direction_sign (1 or -1),
#         streamwise (str e.g. "+x"), freestream_velocity (float)

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

inp = inputs[0].VTKObject

# Unwrap composite datasets to first leaf block
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

def _add_string(table, name, value):
    a = vtk.vtkStringArray()
    a.SetName(name)
    a.InsertNextValue(str(value))
    table.AddColumn(a)

vel_vtk = inp.GetPointData().GetArray(VELOCITY_FIELD)
if vel_vtk is None:
    vel_vtk = inp.GetCellData().GetArray(VELOCITY_FIELD)

if vel_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    vel = vtk_to_numpy(vel_vtk)
    if vel.ndim == 1:
        vel = vel.reshape(-1, 1)

    # Detect streamwise: axis with largest mean magnitude
    means = np.abs(vel.mean(axis=0))
    axis = int(np.argmax(means))
    sign = 1 if vel[:, axis].mean() >= 0 else -1

    freestream = float(np.linalg.norm(vel, axis=1).max()) if vel.shape[1] > 1 else float(np.abs(vel[:, 0]).max())

    axis_name = ["x", "y", "z"][axis]
    direction = f"+{axis_name}" if sign > 0 else f"-{axis_name}"

    _add_scalar(tbl, "streamwise_axis",      float(axis))
    _add_scalar(tbl, "direction_sign",       float(sign))
    _add_scalar(tbl, "freestream_velocity",  freestream)
    _add_string(tbl, "streamwise",           direction)
    _add_string(tbl, "axis_name",            axis_name)
