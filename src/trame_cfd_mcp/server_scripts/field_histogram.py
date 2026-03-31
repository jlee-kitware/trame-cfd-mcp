# Server-side field histogram.
# Injected parameters: FIELD_NAME (str), LOCATION ('POINTS' or 'CELLS'), NUM_BINS (int)
#
# Output: vtkTable with columns:
#   bin_center (float), count (int), min, max, mean, std

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

if LOCATION == 'POINTS':
    data = inp.GetPointData()
else:
    data = inp.GetCellData()

arr_vtk = data.GetArray(FIELD_NAME)
if arr_vtk is None:
    other = inp.GetCellData() if LOCATION == 'POINTS' else inp.GetPointData()
    arr_vtk = other.GetArray(FIELD_NAME)

tbl = output

def _add_col(table, name, values, dtype=vtk.vtkDoubleArray):
    a = dtype()
    a.SetName(name)
    for v in values:
        a.InsertNextValue(v)
    table.AddColumn(a)

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

if arr_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    arr = vtk_to_numpy(arr_vtk)
    if arr.ndim > 1 and arr.shape[1] > 1:
        arr = np.linalg.norm(arr, axis=1)
    else:
        arr = arr.flatten()

    counts, edges = np.histogram(arr, bins=NUM_BINS)
    centers = 0.5 * (edges[:-1] + edges[1:])

    _add_col(tbl, "bin_center", centers.tolist())
    _add_col(tbl, "count", counts.tolist(), vtk.vtkIntArray)
    _add_scalar(tbl, "min",  float(arr.min()))
    _add_scalar(tbl, "max",  float(arr.max()))
    _add_scalar(tbl, "mean", float(arr.mean()))
    _add_scalar(tbl, "std",  float(arr.std()))
    _add_scalar(tbl, "num_points", float(len(arr)))
