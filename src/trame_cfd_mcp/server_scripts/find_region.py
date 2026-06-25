# Server-side spatial extremum finder.
# Injected: FIELD_NAME (str), MODE ('min'|'max'|'high_gradient'),
#           LOCATION ('POINTS'|'CELLS'), EXCLUDE_BOUNDARY_FRACTION (float, 0=no exclusion)
#
# Output: vtkTable with: loc_x, loc_y, loc_z, value, num_points
# For high_gradient: value is gradient magnitude at that location.

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

if LOCATION == 'POINTS':
    field_data = inp.GetPointData()
else:
    field_data = inp.GetCellData()

arr_vtk = field_data.GetArray(FIELD_NAME)
if arr_vtk is None:
    other = inp.GetCellData() if LOCATION == 'POINTS' else inp.GetPointData()
    arr_vtk = other.GetArray(FIELD_NAME)

if arr_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    arr = vtk_to_numpy(arr_vtk)
    mag = np.linalg.norm(arr, axis=1) if (arr.ndim > 1 and arr.shape[1] > 1) else arr.flatten()
    n = len(mag)

    pts_vtk = inp.GetPoints()
    pts = vtk_to_numpy(pts_vtk.GetData()) if pts_vtk else None

    if pts is None or len(pts) != n:
        _add_scalar(tbl, "error", 2.0)
    else:
        valid = np.ones(n, dtype=bool)

        if EXCLUDE_BOUNDARY_FRACTION > 0 and pts is not None:
            bounds = inp.GetBounds()
            mx = (bounds[1] - bounds[0]) * EXCLUDE_BOUNDARY_FRACTION
            my = (bounds[3] - bounds[2]) * EXCLUDE_BOUNDARY_FRACTION
            mz = (bounds[5] - bounds[4]) * EXCLUDE_BOUNDARY_FRACTION if bounds[5] != bounds[4] else 0
            valid = (
                (pts[:, 0] >= bounds[0] + mx) & (pts[:, 0] <= bounds[1] - mx) &
                (pts[:, 1] >= bounds[2] + my) & (pts[:, 1] <= bounds[3] - my)
            )
            if mz > 0:
                valid &= (pts[:, 2] >= bounds[4] + mz) & (pts[:, 2] <= bounds[5] - mz)
            valid &= (mag > 1e-10)
            if not valid.any():
                valid = np.ones(n, dtype=bool)

        if MODE == 'min':
            search = np.where(valid, mag, np.inf)
            idx = int(np.argmin(search))
        else:  # 'max' or 'high_gradient'
            search = np.where(valid, mag, -np.inf)
            idx = int(np.argmax(search))

        loc = pts[idx]
        _add_scalar(tbl, "loc_x", loc[0])
        _add_scalar(tbl, "loc_y", loc[1])
        _add_scalar(tbl, "loc_z", loc[2])
        _add_scalar(tbl, "value", float(mag[idx]))
        _add_scalar(tbl, "num_points", float(n))
