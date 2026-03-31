# Server-side centroid and bounds computation.
# No injected parameters needed — operates on whatever input proxy is given.
# Output: vtkTable with: cx, cy, cz (centroid), xmin, xmax, ymin, ymax, zmin, zmax, num_points

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

pts_vtk = inp.GetPoints()
n = inp.GetNumberOfPoints()

if pts_vtk is None or n == 0:
    _add_scalar(tbl, "error", 1.0)
    _add_scalar(tbl, "num_points", 0.0)
else:
    import numpy as np
    pts = vtk_to_numpy(pts_vtk.GetData())
    cx, cy, cz = pts.mean(axis=0)
    bounds = inp.GetBounds()
    _add_scalar(tbl, "cx", cx)
    _add_scalar(tbl, "cy", cy)
    _add_scalar(tbl, "cz", cz)
    _add_scalar(tbl, "xmin", bounds[0])
    _add_scalar(tbl, "xmax", bounds[1])
    _add_scalar(tbl, "ymin", bounds[2])
    _add_scalar(tbl, "ymax", bounds[3])
    _add_scalar(tbl, "zmin", bounds[4])
    _add_scalar(tbl, "zmax", bounds[5])
    _add_scalar(tbl, "num_points", float(n))
