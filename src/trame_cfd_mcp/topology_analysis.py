"""
Topological analysis tools (TTK) for trame-cfd-mcp.

Separate domain module mirroring cfd_analysis.py: low-level compute_* methods
that wrap Topology ToolKit (TTK) ParaView filters and return a filter handle
plus metadata read from GetDataInformation (no data movement on the hot path).

The point of this module, for the paper: adding a new scientific domain is an
ontology plus a set of thin tool wrappers, with no change to the architecture.

Verified against ParaView 6.0 + TTK (filters: TTKPersistenceDiagram,
TTKScalarFieldCriticalPoints, TTKMorseSmaleComplex,
TTKTopologicalSimplificationByPersistence). All TTK scalar inputs are set via
the array-selection property `ScalarField = ['POINTS', name]`.
"""

from paraview import simple

_TTK_LOADED = False


def ensure_ttk_loaded():
    """Load the TopologyToolKit plugin once, on both client and server if connected."""
    global _TTK_LOADED
    if _TTK_LOADED:
        return True
    last_err = None
    for remote in (True, False):
        try:
            simple.LoadDistributedPlugin('TopologyToolKit', remote)
            _TTK_LOADED = True
            return True
        except Exception as e:  # builtin (no server) rejects remote=True
            last_err = e
    print("[topology_analysis] TTK plugin load failed:", repr(last_err))
    return False


def _is_image_data(proxy):
    di = proxy.GetDataInformation()
    # 6 == VTK_IMAGE_DATA / vtkImageData/UniformGrid family
    return di.GetDataSetType() in (6, 3)  # 6 image, 3 also accepted


def _first_point_scalar(proxy):
    pdi = proxy.GetDataInformation().GetPointDataInformation()
    for i in range(pdi.GetNumberOfArrays()):
        ai = pdi.GetArrayInformation(i)
        if ai.GetNumberOfComponents() == 1:
            return ai.GetName()
    return None


class TopologyAnalysis:
    """Low-level TTK filter wrappers. One instance per session, like CFDAnalysis."""

    # -- input preparation -------------------------------------------------

    def prepare(self, proxy, field=None, resample=False, resample_dims=128):
        """
        Return (input_proxy, scalar_name) suitable for TTK.

        Image data is passed through (TTK uses implicit triangulation, fastest).
        Unstructured input can optionally be resampled to an image grid for speed;
        otherwise it is passed through and TTK triangulates internally.
        A cell scalar is promoted to point data when needed.
        """
        src = proxy
        if not _is_image_data(src):
            if resample:
                src = simple.ResampleToImage(Input=src)
                src.SamplingDimensions = [resample_dims] * 3
                simple.UpdatePipeline(proxy=src)
        scalar = field or _first_point_scalar(src)
        if scalar is None:
            # promote cell data to point data and retry
            c2p = simple.CellDatatoPointData(Input=src)
            simple.UpdatePipeline(proxy=c2p)
            src = c2p
            scalar = field or _first_point_scalar(src)
        return src, scalar

    # -- compute_* (one TTK filter each) -----------------------------------

    def compute_persistence(self, proxy, field=None, resample=False):
        """TTKPersistenceDiagram -> birth/death pairs. Output points = 2 * n_pairs."""
        if not ensure_ttk_loaded():
            return {"error": "TTK plugin not available"}
        try:
            src, scalar = self.prepare(proxy, field, resample)
            if scalar is None:
                return {"error": "no scalar point field found"}
            pd = simple.TTKPersistenceDiagram(Input=src)
            pd.ScalarField = ['POINTS', scalar]
            simple.UpdatePipeline(proxy=pd)
            info = pd.GetDataInformation()
            n_pairs = info.GetNumberOfPoints() // 2
            pers_range = None
            cdi = info.GetCellDataInformation()
            for nm in ("Persistence", "Birth", "Death"):
                ai = cdi.GetArrayInformation(nm)
                if ai is not None:
                    r = ai.GetComponentRange(0)
                    pers_range = [float(r[0]), float(r[1])]
                    break
            return {"filter": pd, "scalar": scalar, "n_pairs": n_pairs,
                    "persistence_range": pers_range}
        except Exception as e:
            return {"error": str(e)}

    def compute_critical_points(self, proxy, field=None, resample=False):
        """TTKScalarFieldCriticalPoints -> minima/saddles/maxima as points."""
        if not ensure_ttk_loaded():
            return {"error": "TTK plugin not available"}
        try:
            src, scalar = self.prepare(proxy, field, resample)
            if scalar is None:
                return {"error": "no scalar point field found"}
            cp = simple.TTKScalarFieldCriticalPoints(Input=src)
            cp.ScalarField = ['POINTS', scalar]
            simple.UpdatePipeline(proxy=cp)
            n_points = cp.GetDataInformation().GetNumberOfPoints()
            counts = self._critical_type_counts(cp)
            return {"filter": cp, "scalar": scalar, "n_critical": n_points,
                    "counts": counts}
        except Exception as e:
            return {"error": str(e)}

    def compute_morse_smale(self, proxy, field=None, resample=False):
        """TTKMorseSmaleComplex -> 4 ports: crit pts, 1-sep, 2-sep, segmentation."""
        if not ensure_ttk_loaded():
            return {"error": "TTK plugin not available"}
        try:
            src, scalar = self.prepare(proxy, field, resample)
            if scalar is None:
                return {"error": "no scalar point field found"}
            ms = simple.TTKMorseSmaleComplex(Input=src)
            ms.ScalarField = ['POINTS', scalar]
            simple.UpdatePipeline(proxy=ms)
            n_crit = simple.OutputPort(ms, 0).GetDataInformation().GetNumberOfPoints()
            n_sep = simple.OutputPort(ms, 1).GetDataInformation().GetNumberOfCells()
            n_seg = simple.OutputPort(ms, 3).GetDataInformation().GetNumberOfPoints()
            return {"filter": ms, "scalar": scalar, "n_critical": n_crit,
                    "n_separatrix_cells": n_sep, "n_segmented_points": n_seg}
        except Exception as e:
            return {"error": str(e)}

    def compute_simplification(self, proxy, field=None, persistence_threshold=0.05,
                               relative=True, resample=False):
        """
        TTKTopologicalSimplificationByPersistence -> denoised scalar field.
        persistence_threshold relative to the field range when relative=True.
        """
        if not ensure_ttk_loaded():
            return {"error": "TTK plugin not available"}
        try:
            src, scalar = self.prepare(proxy, field, resample)
            if scalar is None:
                return {"error": "no scalar point field found"}
            thr = persistence_threshold
            if relative:
                ai = src.GetDataInformation().GetPointDataInformation().GetArrayInformation(scalar)
                lo, hi = ai.GetComponentRange(0)
                thr = persistence_threshold * (hi - lo)
            sf = simple.TTKTopologicalSimplificationByPersistence(Input=src)
            try:
                sf.InputArray = ['POINTS', scalar]
            except Exception:
                sf.InputArray = scalar
            try:
                sf.PersistenceThreshold = thr
                sf.ThresholdIsAbsolute = 1
            except Exception:
                pass
            simple.UpdatePipeline(proxy=sf)
            return {"filter": sf, "scalar": scalar, "persistence_threshold": float(thr)}
        except Exception as e:
            return {"error": str(e)}

    # -- helpers -----------------------------------------------------------

    def _critical_type_counts(self, cp_filter):
        """Count critical points by type from the small output (cheap Fetch)."""
        try:
            from paraview import servermanager
            ds = servermanager.Fetch(cp_filter)
            pd = ds.GetPointData()
            arr = pd.GetArray("CriticalType")
            if arr is None:
                return {}
            labels = {0: "minima", 1: "1_saddles", 2: "2_saddles", 3: "maxima"}
            out = {}
            for i in range(arr.GetNumberOfTuples()):
                k = int(arr.GetValue(i))
                out[labels.get(k, "type_%d" % k)] = out.get(labels.get(k, "type_%d" % k), 0) + 1
            return out
        except Exception:
            return {}
