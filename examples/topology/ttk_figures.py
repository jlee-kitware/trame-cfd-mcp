"""
Publication TTK figures from FUN3D Catalyst output (pressure field).

Separate from ttk_demo.py (which is the reproducible Wavelet smoke test).
This produces the paper figures:
  fig_persistence.(pdf|png)   - matplotlib birth/death diagram
  fig_critical_points.png     - critical points over a translucent pressure isosurface
  fig_morse_smale.png         - separatrix skeleton + critical points
  fig_denoise_compare.pdf     - critical-point counts before/after simplification

Usage:
    pvpython examples/ttk_figures.py [/path/to/catalyst_output] [timestep_index]
"""
import os
import sys
import glob
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "topology_analysis",
    os.path.join(_HERE, "..", "..", "src", "trame_cfd_mcp", "topology_analysis.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TopologyAnalysis = _mod.TopologyAnalysis

from paraview import simple
from paraview import servermanager

DATA = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/jeff.lee/gitsync/fun3d/fun3d_test/flow_demo2/catalyst_output"
OUT = os.path.join(_HERE, "..", "..", "docs", "images")
os.makedirs(OUT, exist_ok=True)
FIELD = "p"


def load_volume(data_dir, idx=None):
    prefixes = sorted(set(
        f.rsplit("_rank", 1)[0]
        for f in glob.glob(os.path.join(data_dir, "volume_*_rank*.vtk"))
    ))
    prefix = prefixes[idx if idx is not None else len(prefixes) // 2]
    print("  timestep:", os.path.basename(prefix))
    readers = [simple.OpenDataFile(f) for f in sorted(glob.glob(prefix + "_rank*.vtk"))]
    for r in readers:
        simple.UpdatePipeline(proxy=r)
    merged = simple.AppendDatasets(Input=readers)
    simple.UpdatePipeline(proxy=merged)
    deghost = simple.RemoveGhostInformation(Input=merged)
    simple.UpdatePipeline(proxy=deghost)
    try:
        clean = simple.CleantoGrid(Input=deghost)
        simple.UpdatePipeline(proxy=clean)
        return clean
    except Exception:
        return deghost


def load_wing(data_dir, idx=None):
    """Extract the wing patch (boundary_tag == 2) from the surface output."""
    prefixes = sorted(set(
        f.rsplit("_rank", 1)[0]
        for f in glob.glob(os.path.join(data_dir, "surface_*_rank*.vtk"))
    ))
    prefix = prefixes[idx if idx is not None else len(prefixes) // 2]
    readers = [simple.OpenDataFile(f) for f in sorted(glob.glob(prefix + "_rank*.vtk"))]
    for r in readers:
        simple.UpdatePipeline(proxy=r)
    merged = simple.AppendDatasets(Input=readers)
    simple.UpdatePipeline(proxy=merged)
    deghost = simple.RemoveGhostInformation(Input=merged)
    simple.UpdatePipeline(proxy=deghost)
    # weld coincident points at rank boundaries (the per-proc seam), as for the volume
    clean = simple.CleantoGrid(Input=deghost)
    simple.UpdatePipeline(proxy=clean)
    wing = simple.Threshold(Input=clean, Scalars=["CELLS", "boundary_tag"],
                            LowerThreshold=2, UpperThreshold=2)
    simple.UpdatePipeline(proxy=wing)
    return wing


def white_bg(view):
    view.UseColorPaletteForBackground = 0
    try:
        view.BackgroundColorMode = "Single Color"
    except Exception:
        pass
    view.Background = [1, 1, 1]
    view.OrientationAxesVisibility = 0


def topn_threshold(ta, src, keep_n=25):
    """Absolute persistence threshold that keeps roughly the top keep_n features."""
    r = ta.compute_persistence(src, field=FIELD)
    ds = servermanager.Fetch(r["filter"])
    parr = ds.GetCellData().GetArray("Persistence")
    vals = sorted((parr.GetValue(i) for i in range(ds.GetNumberOfCells())), reverse=True)
    return vals[keep_n] if len(vals) > keep_n else (vals[-1] if vals else 0.0)


def frame_on(view, proxy, az=35, el=20, zoom=2.2):
    """Point the camera at a proxy's center from a 3/4 view at a fixed distance."""
    b = proxy.GetDataInformation().GetBounds()
    c = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    diag = max(b[1] - b[0], b[3] - b[2], b[5] - b[4], 1.0)
    d = diag * zoom
    view.CameraFocalPoint = c
    view.CameraPosition = [c[0] + d, c[1] + d * 0.6, c[2] + d * 1.1]
    view.CameraViewUp = [0, 1, 0]
    simple.Render(view)


def fig_persistence(ta, src):
    """Birth/death persistence diagram via matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r = ta.compute_persistence(src, field=FIELD)
    if "error" in r:
        print("  persistence error:", r["error"]); return
    f = r["filter"]
    try:
        f.EmbedinDomain = 0
        simple.UpdatePipeline(proxy=f)
    except Exception:
        pass
    ds = servermanager.Fetch(f)
    parr = ds.GetCellData().GetArray("Persistence")
    births, deaths, pers = [], [], []
    for i in range(ds.GetNumberOfCells()):
        cell = ds.GetCell(i)
        if cell.GetNumberOfPoints() < 2:
            continue
        p0 = ds.GetPoint(cell.GetPointId(0))
        p1 = ds.GetPoint(cell.GetPointId(1))
        b = min(p0[1], p1[1]); d = max(p0[1], p1[1])
        births.append(b); deaths.append(d)
        pers.append(parr.GetValue(i) if parr else (d - b))
    lo = min(births + deaths); hi = max(births + deaths)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([lo, hi], [lo, hi], color="0.6", lw=1, zorder=1)  # diagonal
    sc = ax.scatter(births, deaths, c=pers, s=18, cmap="viridis",
                    edgecolor="k", linewidth=0.3, zorder=2)
    ax.set_xlabel("Birth (pressure)")
    ax.set_ylabel("Death (pressure)")
    ax.set_title("Persistence diagram: pressure field (%d pairs)" % len(births))
    ax.set_aspect("equal")
    cb = fig.colorbar(sc, ax=ax, shrink=0.8); cb.set_label("Persistence")
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fn = os.path.join(OUT, "fig_persistence." + ext)
        fig.savefig(fn, dpi=200)
    plt.close(fig)
    print("  wrote fig_persistence.pdf/.png  (%d pairs)" % len(births))


def fig_critical_points(ta, src, wing, thr):
    """Critical points of the simplified pressure field, over the wing geometry."""
    view = simple.GetActiveViewOrCreate("RenderView")
    view.ViewSize = [1200, 900]; white_bg(view)
    for s in simple.GetSources().values():
        try: simple.Hide(s, view)
        except Exception: pass
    dw = simple.Show(wing, view); dw.Representation = "Surface"
    dw.DiffuseColor = [0.62, 0.62, 0.66]; dw.AmbientColor = [0.62, 0.62, 0.66]
    try: simple.ColorBy(dw, None)
    except Exception: pass
    simp = ta.compute_simplification(src, field=FIELD, persistence_threshold=thr, relative=False)
    base = simp["filter"] if "filter" in simp else src
    r = ta.compute_critical_points(base, field=FIELD)
    if "error" in r:
        print("  critical error:", r["error"]); return
    # show only extrema: minima = suction cores, maxima = stagnation
    for ctype, color in [(0, [0.15, 0.35, 0.9]), (3, [0.85, 0.1, 0.1])]:
        th = simple.Threshold(Input=r["filter"], Scalars=["POINTS", "CriticalType"],
                              LowerThreshold=ctype, UpperThreshold=ctype)
        simple.UpdatePipeline(proxy=th)
        if th.GetDataInformation().GetNumberOfPoints() == 0:
            continue
        gg = simple.Glyph(Input=th, GlyphType="Sphere"); gg.ScaleFactor = 0.04
        gg.GlyphMode = "All Points"; simple.UpdatePipeline(proxy=gg)
        dgg = simple.Show(gg, view)
        try: simple.ColorBy(dgg, None)
        except Exception: pass
        dgg.DiffuseColor = color; dgg.AmbientColor = color
    simple.Render(view)  # consume any pending auto-reset from the first Show
    # face-on (down the wing's thin z axis), framed tightly on the wing
    b = wing.GetDataInformation().GetBounds()
    c = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    dx, dy, dz = b[1] - b[0], b[3] - b[2], b[5] - b[4]
    view.CameraParallelProjection = 1
    view.CameraFocalPoint = c
    view.CameraPosition = [c[0], c[1], c[2] + max(dz, 1.0) * 5 + 10]
    view.CameraViewUp = [0, 1, 0]
    view.CameraParallelScale = 0.5 * max(dx, dy) * 1.25
    simple.Render(view)
    fn = os.path.join(OUT, "fig_critical_points.png")
    simple.SaveScreenshot(fn, view, ImageResolution=[1200, 900])
    print("  wrote fig_critical_points.png ", r.get("counts", {}))


def fig_morse_smale(ta, src, wing, thr):
    view = simple.GetActiveViewOrCreate("RenderView")
    view.ViewSize = [1200, 900]; white_bg(view)
    for s in simple.GetSources().values():
        try: simple.Hide(s, view)
        except Exception: pass
    dw = simple.Show(wing, view); dw.Representation = "Surface"
    dw.DiffuseColor = [0.62, 0.62, 0.66]; dw.AmbientColor = [0.62, 0.62, 0.66]
    try: simple.ColorBy(dw, None)
    except Exception: pass
    simp = ta.compute_simplification(src, field=FIELD, persistence_threshold=thr, relative=False)
    base = simp["filter"] if "filter" in simp else src
    r = ta.compute_morse_smale(base, field=FIELD)
    if "error" in r:
        print("  morse-smale error:", r["error"]); return
    f = r["filter"]
    tube = simple.Tube(Input=simple.OutputPort(f, 1)); tube.Radius = 0.006
    simple.UpdatePipeline(proxy=tube)
    dt = simple.Show(tube, view)
    for arr in ("SeparatrixType", "CellDimension"):
        try: simple.ColorBy(dt, ("CELLS", arr)); break
        except Exception: continue
    g = simple.Glyph(Input=simple.OutputPort(f, 0), GlyphType="Sphere")
    g.ScaleFactor = 0.03; g.GlyphMode = "All Points"
    simple.UpdatePipeline(proxy=g)
    dg = simple.Show(g, view)
    try: simple.ColorBy(dg, ("POINTS", "CriticalType"))
    except Exception: pass
    simple.Render(view)  # consume any pending auto-reset before framing
    frame_on(view, wing, zoom=1.6)
    fn = os.path.join(OUT, "fig_morse_smale.png")
    simple.SaveScreenshot(fn, view, ImageResolution=[1200, 900])
    print("  wrote fig_morse_smale.png")


def fig_denoise_compare(ta, src, thr):
    """Critical-point counts before vs after persistence simplification."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    raw = ta.compute_critical_points(src, field=FIELD).get("counts", {})
    simp = ta.compute_simplification(src, field=FIELD, persistence_threshold=thr, relative=False)
    after = {}
    if "filter" in simp:
        after = ta.compute_critical_points(simp["filter"], field=FIELD).get("counts", {})
    keys = ["minima", "1_saddles", "2_saddles", "maxima", "type_4"]
    labels = ["minima", "1-saddles", "2-saddles", "maxima", "multi-saddles"]
    b = [raw.get(c, 0) for c in keys]
    a = [after.get(c, 0) for c in keys]
    import numpy as np
    x = np.arange(len(keys)); w = 0.38
    fig, ax = plt.subplots(figsize=(5.5, 4))
    rb = ax.bar(x - w / 2, b, w, label="raw field (%d)" % sum(b), color="#bbbbbb")
    ra = ax.bar(x + w / 2, a, w, label="after simplification (%d)" % sum(a), color="#2a6fb0")
    try:
        ax.bar_label(rb, padding=2, fontsize=8)
        ax.bar_label(ra, padding=2, fontsize=8)
    except Exception:
        pass
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=15)
    ax.set_ylabel("count"); ax.set_title("Critical points before/after persistence simplification")
    ax.legend(); fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_denoise_compare.pdf"), dpi=200)
    fig.savefig(os.path.join(OUT, "fig_denoise_compare.png"), dpi=200)
    plt.close(fig)
    print("  wrote fig_denoise_compare.pdf/.png  raw=%s after=%s" % (sum(b), sum(a)))


def main():
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
    ta = TopologyAnalysis()
    src = load_volume(DATA, idx)
    wing = load_wing(DATA, idx)
    thr = topn_threshold(ta, src, keep_n=25)
    print("  simplification threshold (keep ~top 25):", round(thr, 5))
    print("[A] persistence");      fig_persistence(ta, src)
    print("[B] critical points");  fig_critical_points(ta, src, wing, thr)
    print("[C] morse-smale");      fig_morse_smale(ta, src, wing, thr)
    print("[D] denoise compare");  fig_denoise_compare(ta, src, thr)
    print("done")


if __name__ == "__main__":
    main()
