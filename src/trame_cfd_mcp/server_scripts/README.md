# Server-side analysis scripts

These Python files are executed inside ParaView's `ProgrammableFilter` via
`trame_llm.paraview.run_server_script`. They run on the ParaView server,
optionally in parallel across MPI ranks.

## The one rule

**Use `np.*` (or `numpy.*`) for all mathematical operations. Never use bare
Python builtins like `min`, `max`, `sum`, `abs`, `any`, `all`, `round`, or
the bare numpy names that `vtkmodules.numpy_interface.algorithms` exports
(`where`, `sort`, `clip`, `mean`, `cross`, `dot`, etc.).**

Specifically:

```python
# Bad — hits VTK's algorithms.max(array, axis) — the second arg becomes "axis"
idx = min(idx, NUM_BINS - 1)
margin = max(extent0, extent1)
total = sum(values)
mask = abs(x) > 0.1

# Good — always safe, including two-argument scalar comparisons
idx = np.minimum(idx, NUM_BINS - 1)
margin = np.maximum(extent0, extent1)
total = np.sum(values)     # or values.sum()
mask = np.abs(x) > 0.1
```

Method calls on numpy arrays (`arr.min()`, `arr.max()`, `arr.sum()`) are
also safe. The danger is only with bare functions.

## Why

The `ProgrammableFilter` execution namespace has
`from vtkmodules.numpy_interface.algorithms import *` applied to it. That
import defines parallel-reduction versions of many common names, including
`min` and `max`, which shadow Python's builtins. Their signatures are
different:

```
builtins.min(a, b)          # "return the smaller of a and b"
algorithms.min(array, axis, controller)
                            # "reduce `array` along `axis` across all MPI ranks"
```

A script that calls `min(some_scalar, some_int)` in this namespace hits
`algorithms.min`, which treats the scalar as a 0-dim array and tries to
reduce along the "axis" given by the second argument. The result is a
cryptic traceback from `vtkmodules/numpy_interface/algorithms.py` that
points at line numbers in numpy internals rather than the offending line
in the server script.

We discovered this via `force_distribution.py` calling
`min(idx, NUM_BINS - 1)` where `NUM_BINS=40`. The error was
`axis 39 is out of bounds for array of dimension 0`. The `39` came from
`NUM_BINS - 1`. Nothing in the error pointed at the real problem.

Using `np.*` sidesteps the whole mess because numpy's reduction functions
handle scalars correctly regardless of the surrounding namespace state.

## Pipeline type contract

Server scripts receive whatever proxy is passed to `run_server_script`. Always know what type the input is:

- `ExtractSurface` outputs `vtkPolyData` — scripts can use `GetPolys()`, `GetStrips()`, etc.
- `Clip` outputs `vtkUnstructuredGrid` — scripts **cannot** use `GetPolys()`. Use `GetCells()` instead, or add a second `ExtractSurface` after the clip to convert back to `vtkPolyData`.
- `SurfaceNormals` requires `vtkPolyData` input — always place after `ExtractSurface`, never directly after `Clip`.

Standard body-surface isolation pattern:

```python
ExtractSurface(Input=flat_proxy)   # full domain → vtkPolyData
→ Clip(ClipType='Box', Invert=1)   # keep body region → vtkUnstructuredGrid
→ ExtractSurface(Input=clip)       # convert back → vtkPolyData
→ SurfaceNormals(Input=surf)       # add cell normals → vtkPolyData
```

- Composite datasets: unwrap with the `get_leaf(ds)` helper at the top of
  the script before accessing `GetPointData()` / `GetCellData()`. See
  `detect_streamwise.py` for the canonical pattern.
- Output: write to the `tbl = output` vtkTable via `AddColumn` for arrays
  and `AddColumn` + single-element `vtkDoubleArray` for scalars. Use
  `GetFieldData().AddArray()` for scalar KPIs that don't have a row count
  matching the main output columns (see `boundary_layer.py`).
- Errors: on failure, add a single scalar column named `"error"` with
  value `1.0`. Callers check for this via `kpi["error"]`.
- Injected parameters: documented at the top of each script, passed as
  keyword args to `run_server_script(..., params={...})`. They appear as
  top-level names in the script's namespace.
