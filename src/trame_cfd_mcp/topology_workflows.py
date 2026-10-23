"""
Topology (TTK) workflow tools: show_* methods that orchestrate compute +
visualize + structured return, mirroring CFDWorkflows.show_*.

Constructed with a reference to the CFDWorkflows instance (to reuse its data /
proxy / ontology helpers) and a TopologyAnalysis instance for the TTK compute.
This keeps the new domain additive: no change to the CFD classes.
"""

from paraview import simple


class TopologyWorkflows:
    def __init__(self, cfd_workflows, topology_analysis, app=None):
        self._wf = cfd_workflows           # reuse helpers + ontology
        self._topo = topology_analysis
        self._app = app

    # -- helpers (delegate to the shared CFDWorkflows instance) ------------

    def _reader(self):
        return self._wf._get_data_reader()

    def _provenance(self, proxy, chain, scalar, params):
        return {
            "dataset": self._wf._get_dataset_filename(proxy),
            "filter_chain": chain,
            "arrays_used": [scalar],
            "parameters": params,
        }

    # -- show_* tools ------------------------------------------------------

    def show_persistence_diagram(self, field: str = None) -> dict:
        """
        Compute and display the persistence diagram of a scalar field (TTK).
        Reveals the signal/noise gap: high-persistence pairs are robust features,
        pairs near the diagonal are noise. Use before feature extraction.
        """
        view = simple.GetActiveView()
        proxy = self._reader()
        if proxy is None:
            return {"error": "No data reader found"}
        self._wf._mcp.hide_all()
        r = self._topo.compute_persistence(proxy, field=field)
        if "error" in r:
            return r
        f = r["filter"]
        try:
            f.EmbedinDomain = 0  # lay out in the birth-death plane
            simple.UpdatePipeline(proxy=f)
        except Exception:
            pass
        d = simple.Show(f, view)
        try:
            simple.ColorBy(d, ("CELLS", "Persistence"))
        except Exception:
            pass
        simple.RenameSource("PersistenceDiagram", f)
        simple.ResetCamera(view)
        simple.Render(view)
        return {
            "status": "created",
            "type": "persistence_diagram",
            "proxy_name": "PersistenceDiagram",
            "provenance": self._provenance(proxy, ["TTKPersistenceDiagram"], r["scalar"], {}),
            "result": {
                "scalar": r["scalar"],
                "n_pairs": r["n_pairs"],
                "persistence_range": r.get("persistence_range"),
            },
            "ontology_hints": self._wf._ontology_hints([
                "topology_features.persistence_diagram.interpretation",
                "topology_features.persistence_diagram.persistence_gap",
            ]),
            "tip": "The diagram is in the birth-death plane; view straight on. "
                   "To denoise, say 'simplify by persistence' with a threshold in the gap.",
        }

    def show_critical_points(self, field: str = None) -> dict:
        """
        Compute and display the critical points of a scalar field (TTK):
        minima, 1-saddles, 2-saddles, maxima, colored by CriticalType.
        """
        view = simple.GetActiveView()
        proxy = self._reader()
        if proxy is None:
            return {"error": "No data reader found"}
        self._wf._mcp.hide_all()
        r = self._topo.compute_critical_points(proxy, field=field)
        if "error" in r:
            return r
        d = simple.Show(r["filter"], view)
        d.Representation = "Points"
        d.PointSize = 8
        try:
            simple.ColorBy(d, ("POINTS", "CriticalType"))
        except Exception:
            pass
        simple.RenameSource("CriticalPoints", r["filter"])
        self._wf._frame_body(view, direction="iso")
        simple.Render(view)
        return {
            "status": "created",
            "type": "critical_points",
            "proxy_name": "CriticalPoints",
            "provenance": self._provenance(proxy, ["TTKScalarFieldCriticalPoints"], r["scalar"], {}),
            "result": {"scalar": r["scalar"], "n_critical": r["n_critical"], "counts": r.get("counts", {})},
            "ontology_hints": self._wf._ontology_hints([
                "topology_features.critical_points.types",
            ]),
            "tip": "Colored by CriticalType (0=min, 1=1-saddle, 2=2-saddle, 3=max). "
                   "Run 'simplify by persistence' first to drop noise critical points.",
        }

    def show_morse_smale(self, field: str = None) -> dict:
        """
        Compute and display the Morse-Smale complex (TTK): the separatrix
        skeleton plus critical points. A threshold-free structural decomposition.
        """
        view = simple.GetActiveView()
        proxy = self._reader()
        if proxy is None:
            return {"error": "No data reader found"}
        self._wf._mcp.hide_all()
        r = self._topo.compute_morse_smale(proxy, field=field)
        if "error" in r:
            return r
        f = r["filter"]
        sep = simple.OutputPort(f, 1)
        ds = simple.Show(sep, view)
        ds.LineWidth = 2
        for arr in ("SeparatrixType", "CellDimension"):
            try:
                simple.ColorBy(ds, ("CELLS", arr)); break
            except Exception:
                continue
        cpp = simple.OutputPort(f, 0)
        dc = simple.Show(cpp, view)
        dc.Representation = "Points"
        dc.PointSize = 10
        try:
            simple.ColorBy(dc, ("POINTS", "CriticalType"))
        except Exception:
            pass
        simple.RenameSource("MorseSmaleComplex", f)
        self._wf._frame_body(view, direction="iso")
        simple.Render(view)
        return {
            "status": "created",
            "type": "morse_smale_complex",
            "proxy_name": "MorseSmaleComplex",
            "provenance": self._provenance(proxy, ["TTKMorseSmaleComplex"], r["scalar"], {}),
            "result": {
                "scalar": r["scalar"],
                "n_critical": r["n_critical"],
                "n_separatrix_cells": r["n_separatrix_cells"],
                "n_segmented_points": r["n_segmented_points"],
            },
            "ontology_hints": self._wf._ontology_hints([
                "topology_features.morse_smale_complex.use",
            ]),
            "tip": "Lines are the 1-separatrix skeleton; points are critical points. "
                   "Dense skeletons usually mean the field needs simplification first.",
        }

    def show_simplified(self, field: str = None, persistence_threshold: float = 0.05) -> dict:
        """
        Compute and display a persistence-simplified (denoised) scalar field (TTK).
        persistence_threshold is relative to the field range (e.g. 0.05 = 5%).
        """
        view = simple.GetActiveView()
        proxy = self._reader()
        if proxy is None:
            return {"error": "No data reader found"}
        self._wf._mcp.hide_all()
        r = self._topo.compute_simplification(proxy, field=field,
                                              persistence_threshold=persistence_threshold)
        if "error" in r:
            return r
        simple.RenameSource("SimplifiedField", r["filter"])
        bounds = r["filter"].GetDataInformation().GetBounds()
        origin, axis = self._wf._section_plane(self._wf._get_proxy_name(proxy), "auto", bounds)
        section = simple.Slice(Input=r["filter"], registrationName="SimplifiedField_Section")
        section.SliceType = "Plane"
        section.SliceType.Origin = origin
        section.SliceType.Normal = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[axis]
        d = simple.Show(section, view)
        try:
            simple.ColorBy(d, ("POINTS", r["scalar"]))
            self._wf._rescale_to_focus(section, r["scalar"])
            d.SetScalarBarVisibility(view, True)
        except Exception:
            pass
        self._wf._mcp.set_view(direction=f"-{axis}")
        self._wf._frame_body(view)
        simple.Render(view)
        return {
            "status": "created",
            "type": "topological_simplification",
            "proxy_name": "SimplifiedField_Section",
            "field_proxy": "SimplifiedField",
            "provenance": self._provenance(
                proxy, ["TTKTopologicalSimplificationByPersistence"], r["scalar"],
                {"persistence_threshold": r["persistence_threshold"]}),
            "result": {"scalar": r["scalar"], "persistence_threshold": r["persistence_threshold"]},
            "ontology_hints": self._wf._ontology_hints([
                "topology_features.topological_simplification.threshold_guidance",
            ]),
            "tip": "Denoised field. Re-run critical points or persistence on this to "
                   "confirm only significant features remain.",
        }
