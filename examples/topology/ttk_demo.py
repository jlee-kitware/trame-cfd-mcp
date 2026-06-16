"""
TTK demo: generate the four topology figures for the whitepaper.

Usage:
    pvpython examples/ttk_demo.py                 # synthetic Wavelet field
    pvpython examples/ttk_demo.py /path/data.vtu  # any scalar field

Writes PNGs to docs/images/ttk_*.png and prints metrics.
This calls the same TopologyAnalysis compute layer the MCP tools will use.
"""
import os
import sys

# import the topology module directly by path, bypassing the package __init__
# (which pulls in trame_llm; not needed for this standalone demo)
_HERE = os.path.dirname(os.path.abspath(__file__))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "topology_analysis",
    os.path.join(_HERE, "..", "..", "src", "trame_cfd_mcp", "topology_analysis.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TopologyAnalysis = _mod.TopologyAnalysis

from paraview import simple

OUT = os.path.join(_HERE, "..", "..", "docs", "images")
os.makedirs(OUT, exist_ok=True)


import glob


def _load_fun3d(prefix):
    """Load and merge the per-rank VTK files for one FUN3D timestep."""
    files = sorted(glob.glob(prefix + "_rank*.vtk"))
    readers = [simple.OpenDataFile(f) for f in files]
    for r in readers:
        simple.UpdatePipeline(proxy=r)
    merged = simple.AppendDatasets(Input=readers) if len(readers) > 1 else readers[0]
    simple.UpdatePipeline(proxy=merged)
    try:
        clean = simple.CleantoGrid(Input=merged)  # merge coincident points at rank seams
        simple.UpdatePipeline(proxy=clean)
        return clean
    except Exception:
        return merged


def _source(path):
    """Return (proxy, field_name). Wavelet by default; FUN3D dir or prefix otherwise."""
    if not path:
        w = simple.Wavelet()
        simple.UpdatePipeline(proxy=w)
        return w, "RTData"
    if os.path.isdir(path):
        prefixes = sorted(set(
            f.rsplit("_rank", 1)[0]
            for f in glob.glob(os.path.join(path, "volume_*_rank*.vtk"))
        ))
        if not prefixes:
            raise SystemExit("no volume_*_rank*.vtk under " + path)
        prefix = prefixes[len(prefixes) // 2]  # a mid timestep
        print("  using", os.path.basename(prefix))
        return _load_fun3d(prefix), "p"
    if "_rank" not in path and glob.glob(path + "_rank*.vtk"):
        return _load_fun3d(path), "p"
    src = simple.OpenDataFile(path)
    simple.UpdatePipeline(proxy=src)
    return src, "p"


def _shot(view, name):
    simple.ResetCamera(view)
    simple.Render(view)
    fn = os.path.join(OUT, name)
    simple.SaveScreenshot(fn, view, ImageResolution=[1200, 900])
    print("  wrote", os.path.relpath(fn))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    ta = TopologyAnalysis()
    view = simple.GetRenderView()
    view.Background = [1, 1, 1]
    src, FIELD = _source(path)
    print("  field:", FIELD)

    print("\n[1] persistence diagram")
    r = ta.compute_persistence(src, field=FIELD)
    print("   ", {k: v for k, v in r.items() if k != "filter"})
    if "filter" in r:
        simple.Hide(src, view)
        try:
            r["filter"].EmbedinDomain = 0   # lay out in birth-death plane
            simple.UpdatePipeline(proxy=r["filter"])
        except Exception:
            pass
        d = simple.Show(r["filter"], view)
        simple.ColorBy(d, ("CELLS", "Persistence"))
        # straight-on parallel view of the thin (planar) axis
        b = r["filter"].GetDataInformation().GetBounds()
        c = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
        ext = [b[1] - b[0], b[3] - b[2], b[5] - b[4]]
        dist = (max(ext) or 1.0) * 1.1
        thin = ext.index(min(ext))
        view.CameraParallelProjection = 1
        if thin == 2:
            view.CameraPosition = [c[0], c[1], c[2] + dist]; view.CameraViewUp = [0, 1, 0]
        elif thin == 1:
            view.CameraPosition = [c[0], c[1] + dist, c[2]]; view.CameraViewUp = [0, 0, 1]
        else:
            view.CameraPosition = [c[0] + dist, c[1], c[2]]; view.CameraViewUp = [0, 0, 1]
        view.CameraFocalPoint = c
        simple.ResetCamera(view)
        simple.Render(view)
        fn = os.path.join(OUT, "ttk_persistence.png")
        simple.SaveScreenshot(fn, view, ImageResolution=[1200, 900])
        print("  wrote", os.path.relpath(fn))
        view.CameraParallelProjection = 0
        simple.Hide(r["filter"], view)

    print("\n[2] critical points")
    r = ta.compute_critical_points(src, field=FIELD)
    print("   ", {k: v for k, v in r.items() if k != "filter"})
    if "filter" in r:
        d = simple.Show(r["filter"], view)
        d.Representation = "Points"
        d.PointSize = 8
        try:
            simple.ColorBy(d, ("POINTS", "CriticalType"))
        except Exception:
            pass
        _shot(view, "ttk_critical_points.png")
        simple.Hide(r["filter"], view)

    print("\n[3] Morse-Smale complex")
    r = ta.compute_morse_smale(src, field=FIELD)
    print("   ", {k: v for k, v in r.items() if k != "filter"})
    if "filter" in r:
        sep = simple.OutputPort(r["filter"], 1)   # 1-separatrices (MS skeleton)
        ds = simple.Show(sep, view)
        ds.Representation = "Surface"
        ds.LineWidth = 2
        for arr in ("SeparatrixType", "CellDimension", "SeparatrixFunctionMaximum"):
            try:
                simple.ColorBy(ds, ("CELLS", arr)); break
            except Exception:
                continue
        cpp = simple.OutputPort(r["filter"], 0)    # critical points
        dc = simple.Show(cpp, view)
        dc.Representation = "Points"
        dc.PointSize = 10
        try:
            simple.ColorBy(dc, ("POINTS", "CriticalType"))
        except Exception:
            pass
        _shot(view, "ttk_morse_smale.png")
        simple.Hide(sep, view)
        simple.Hide(cpp, view)

    print("\n[4] persistence simplification (denoising)")
    r = ta.compute_simplification(src, field=FIELD, persistence_threshold=0.1)
    print("   ", {k: v for k, v in r.items() if k != "filter"})
    if "filter" in r:
        c = simple.Contour(Input=r["filter"])
        c.ContourBy = ["POINTS", r["scalar"]]
        info = r["filter"].GetDataInformation().GetPointDataInformation()
        rng = info.GetArrayInformation(r["scalar"]).GetComponentRange(0)
        c.Isosurfaces = [0.5 * (rng[0] + rng[1])]
        simple.UpdatePipeline(proxy=c)
        simple.Show(c, view)
        _shot(view, "ttk_denoised.png")

    print("\ndone.")


if __name__ == "__main__":
    main()
