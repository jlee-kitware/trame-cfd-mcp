# Server-side field statistics.
# Injected parameters: FIELD_NAME (str), LOCATION ('POINTS' or 'CELLS')
#
# Output: vtkTable with one row containing:
#   min, max, mean, std, num_points, is_vector (0/1)
#   For vectors: mag_min, mag_max, mag_mean, mag_std also present.

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

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

if LOCATION == 'POINTS':
    data = inp.GetPointData()
else:
    data = inp.GetCellData()

arr_vtk = data.GetArray(FIELD_NAME)
if arr_vtk is None:
    # Try the other association
    other = inp.GetCellData() if LOCATION == 'POINTS' else inp.GetPointData()
    arr_vtk = other.GetArray(FIELD_NAME)

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

tbl = output

if arr_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    arr = vtk_to_numpy(arr_vtk)
    n = len(arr) if arr.ndim == 1 else arr.shape[0]
    _add_scalar(tbl, "num_points", n)

    if arr.ndim > 1 and arr.shape[1] > 1:
        mag = np.linalg.norm(arr, axis=1)
        _add_scalar(tbl, "is_vector", 1.0)
        _add_scalar(tbl, "mag_min",  float(mag.min()))
        _add_scalar(tbl, "mag_max",  float(mag.max()))
        _add_scalar(tbl, "mag_mean", float(mag.mean()))
        _add_scalar(tbl, "mag_std",  float(mag.std()))
        for c in range(arr.shape[1]):
            col = arr[:, c]
            suffix = ["x", "y", "z"][c] if c < 3 else str(c)
            _add_scalar(tbl, f"min_{suffix}",  float(col.min()))
            _add_scalar(tbl, f"max_{suffix}",  float(col.max()))
            _add_scalar(tbl, f"mean_{suffix}", float(col.mean()))
    else:
        a = arr.flatten()
        _add_scalar(tbl, "is_vector", 0.0)
        _add_scalar(tbl, "min",  float(a.min()))
        _add_scalar(tbl, "max",  float(a.max()))
        _add_scalar(tbl, "mean", float(a.mean()))
        _add_scalar(tbl, "std",  float(a.std()))
