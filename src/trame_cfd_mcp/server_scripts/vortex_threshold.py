# Server-side vortex threshold computation.
# Injected parameters: FIELD_NAME (str), METHOD (str), PERCENTILE (float)
#
# Input: proxy with a scalar or vector field FIELD_NAME at POINTS.
# Output: vtkTable with columns: threshold, field_min, field_max

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

inp = inputs[0].VTKObject
arr_vtk = inp.GetPointData().GetArray(FIELD_NAME)

tbl = output

def _add_scalar(table, name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    table.AddColumn(a)

if arr_vtk is None:
    _add_scalar(tbl, "error", 1.0)
else:
    arr = vtk_to_numpy(arr_vtk).flatten()
    field_min = float(arr.min())
    field_max = float(arr.max())

    if METHOD == "lambda2":
        threshold = 0.01 * field_min
    else:
        positive = arr[arr > 0]
        if len(positive) > 0:
            threshold = float(np.percentile(positive, PERCENTILE))
        else:
            threshold = max(0.0, field_max * 0.01)

    _add_scalar(tbl, "threshold",  threshold)
    _add_scalar(tbl, "field_min",  field_min)
    _add_scalar(tbl, "field_max",  field_max)
    _add_scalar(tbl, "num_points", float(len(arr)))
