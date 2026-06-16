"""Build the single-timestep TTK scene and save a ParaView state (.pvsm).
Open the resulting state in the GUI, frame the camera, and save screenshots.
"""
import os, glob, importlib.util
from paraview import simple, servermanager

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = "/Users/jeff.lee/gitsync/fun3d/fun3d_test/flow_demo2/catalyst_output"
OUT  = os.path.join(_HERE, "..", "..", "docs", "images")
FIELD = "p"
TTK_SO = "/usr/local/bin/plugins/TopologyToolKit/TopologyToolKit.so"
TS = "000051"

simple.LoadPlugin(TTK_SO, remote=False, ns=globals())

# import the verified TopologyAnalysis (no matplotlib dependency)
spec = importlib.util.spec_from_file_location(
    "topology_analysis",
    os.path.join(_HERE, "..", "..", "src", "trame_cfd_mcp", "topology_analysis.py"))
tam = importlib.util.module_from_spec(spec); spec.loader.exec_module(tam)
TopologyAnalysis = tam.TopologyAnalysis


def _merge(pattern):
    readers = [simple.OpenDataFile(f) for f in sorted(glob.glob(pattern))]
    for r in readers:
        simple.UpdatePipeline(proxy=r)
    m = simple.AppendDatasets(Input=readers); simple.UpdatePipeline(proxy=m)
    # strip ghost cells (rank-boundary duplicates) BEFORE merging points;
    # CleantoGrid/Threshold do not remove ghosts, and they corrupt topology
    g = simple.RemoveGhostInformation(Input=m); simple.UpdatePipeline(proxy=g)
    return g

def load_volume():
    m = _merge(os.path.join(DATA, "volume_%s_rank*.vtk" % TS))
    try:
        c = simple.CleantoGrid(Input=m); simple.UpdatePipeline(proxy=c); return c
    except Exception:
        return m

def load_wing():
    m = _merge(os.path.join(DATA, "surface_%s_rank*.vtk" % TS))
    w = simple.Threshold(Input=m, Scalars=["CELLS", "boundary_tag"],
                         LowerThreshold=2, UpperThreshold=2)
    simple.UpdatePipeline(proxy=w); return w

def topn_threshold(ta, src, keep_n=25):
    r = ta.compute_persistence(src, field=FIELD)
    ds = servermanager.Fetch(r["filter"]); pa = ds.GetCellData().GetArray("Persistence")
    vals = sorted((pa.GetValue(i) for i in range(ds.GetNumberOfCells())), reverse=True)
    return vals[keep_n] if len(vals) > keep_n else (vals[-1] if vals else 0.0)


def main():
    ta = TopologyAnalysis()
    vol = load_volume()
    wing = load_wing()
    thr = topn_threshold(ta, vol, keep_n=25)
    print("threshold (top-25):", round(thr, 5))

    simp = ta.compute_simplification(vol, field=FIELD,
                                     persistence_threshold=thr, relative=False)
    base = simp["filter"] if "filter" in simp else vol
    cp = ta.compute_critical_points(base, field=FIELD)["filter"]
    ms = ta.compute_morse_smale(base, field=FIELD)["filter"]

    view = simple.GetActiveViewOrCreate("RenderView")
    view.ViewSize = [1600, 1000]
    view.OrientationAxesVisibility = 0
    # leave the default gradient background (reads better than white for 3D flow)

    # wing as solid context
    dw = simple.Show(wing, view); dw.Representation = "Surface"
    dw.DiffuseColor = [0.62, 0.62, 0.66]; dw.AmbientColor = [0.62, 0.62, 0.66]
    try: simple.ColorBy(dw, None)
    except Exception: pass

    # critical points as spheres, colored by CriticalType (0 min .. 3 max)
    g = simple.Glyph(Input=cp, GlyphType="Sphere"); g.ScaleFactor = 0.14
    g.GlyphMode = "All Points"; simple.UpdatePipeline(proxy=g)
    dg = simple.Show(g, view)
    try: simple.ColorBy(dg, ("POINTS", "CriticalType"))
    except Exception: pass

    # streamlines seeded FROM the critical points, colored by velocity magnitude
    try:
        st = simple.StreamTracerWithCustomSource(Input=vol, SeedSource=cp)
        st.Vectors = ["POINTS", "Velocity"]
        st.IntegrationDirection = "BOTH"
        st.MaximumStreamlineLength = 30.0
        simple.UpdatePipeline(proxy=st)
        dst = simple.Show(st, view)
        simple.ColorBy(dst, ("POINTS", "Velocity", "Magnitude"))
        try:
            dst.RescaleTransferFunctionToDataRange(True, False)
            dst.SetScalarBarVisibility(view, True)   # the one meaningful legend
            dg.SetScalarBarVisibility(view, False)   # CriticalType: explain in caption
        except Exception: pass
    except Exception as e:
        print("streamlines skipped:", e)

    # Morse-Smale separatrices (port 1) as tubes, hidden by default (toggle in GUI)
    try:
        tube = simple.Tube(Input=simple.OutputPort(ms, 1)); tube.Radius = 0.03
        simple.UpdatePipeline(proxy=tube)
        dt = simple.Show(tube, view); dt.Visibility = 0
    except Exception as e:
        print("MS tube skipped:", e)

    # volume kept in pipeline but hidden
    try: simple.Hide(vol, view)
    except Exception: pass

    # starting camera (reframe in the GUI to taste, then re-save the state)
    simple.ResetCamera(view)
    simple.Render(view)

    path = os.path.join(OUT, "ttk_scene.pvsm")
    simple.SaveState(path)
    print("SAVED_STATE:", path)


if __name__ == "__main__":
    main()
