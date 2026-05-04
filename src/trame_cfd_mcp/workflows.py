import logging
"""
High-level CFD workflow tools.

These wrap the fine-grained tools into complete workflows.
The LLM just does intent matching - workflows execute deterministically.
Full provenance tracking enables reproducibility and explanation.
"""

from paraview import simple
from trame_llm.paraview import ensure_flat_input, create_table_source


class CFDWorkflows:
    """High-level workflow tools for CFD visualization."""
    
    def __init__(self, cfd_analysis, on_pipeline_changed=None, app=None, ontology=None):
        """
        Initialize with reference to CFDAnalysis for internal tool access.
        
        Args:
            cfd_analysis: CFDAnalysis instance
            on_pipeline_changed: Optional callback to notify when pipeline changes
            app: Optional trame app for rendering charts
            ontology: Optional ontology dict (from ontology.json). When provided,
                      workflow returns include validated `ontology_hints` pointing
                      at relevant domain knowledge. See _ontology_hints().
        """
        self._mcp = cfd_analysis  # Keep as _mcp for minimal code changes
        self._provenance_registry = {}  # proxy_name -> provenance dict
        self._on_pipeline_changed = on_pipeline_changed
        self._app = app
        self._chart_counter = 0
        self._ontology = ontology or {}

    def _ontology_hints(self, keys) -> list:
        """
        Validate dotted ontology keys against the loaded ontology and return the
        subset that resolves. Keys that don't resolve log a warning so stale
        references surface during development rather than failing silently.
        
        Ontology hints are passive: the LLM is expected to call get_ontology()
        and look up the hinted keys when explaining results. This keeps tool
        returns small (a few short strings) while nudging the LLM toward
        grounded CFD interpretation instead of free-form recall.
        
        Args:
            keys: Single dotted key string or list of them (e.g.
                  "flow_features.boundary_layer.metrics.shape_factor")
        
        Returns:
            List of keys that resolve against the current ontology. Empty list
            if ontology wasn't provided to the constructor.
        """
        if not self._ontology:
            return []
        if isinstance(keys, str):
            keys = [keys]
        
        resolved = []
        for key in keys:
            node = self._ontology
            ok = True
            for part in key.split('.'):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if ok:
                resolved.append(key)
            else:
                logging.warning(
                    f"[_ontology_hints] Stale ontology key: '{key}' "
                    f"does not resolve in ontology version "
                    f"{self._ontology.get('version', '?')}. "
                    f"Update the workflow or add the key to ontology.json."
                )
        return resolved
    
    def _notify_pipeline_changed(self):
        """Notify that pipeline has changed (for UI updates like pipeline browser)."""
        # Use trame's controller if available (this is what ptc's PipelineBrowser listens to)
        if self._app and hasattr(self._app, 'ctrl'):
            if self._app.ctrl.on_data_change.exists():
                logging.debug(f"[_notify_pipeline_changed] Calling app.ctrl.on_data_change()")
                self._app.ctrl.on_data_change()
            # Also try view_update which triggers render
            if self._app.ctrl.view_update.exists():
                self._app.ctrl.view_update()
        else:
            logging.debug(f"[_notify_pipeline_changed] No ctrl - app={self._app is not None}")
        # Also call legacy callback if provided
        if self._on_pipeline_changed:
            self._on_pipeline_changed()
    
    def _create_chart_table(self, chart_type: str, title: str, data: dict, metadata: dict = None) -> str:
        """
        Create a vtkTable proxy for chart data.
        
        Returns the proxy name which can be used to retrieve data for plotting.
        """
        from paraview import servermanager
        
        self._chart_counter += 1
        proxy_name = f"Chart_{self._chart_counter}_{chart_type}"
        
        # Build column dict for create_table_source
        columns = {}

        # Store metadata for FieldData (added after proxy creation)
        chart_metadata = {
            "chart_type": chart_type,
            "chart_title": title,
            "x_label": data.get("x_label", ""),
            "y_label": data.get("y_label", ""),
        }

        if chart_type == "boundary_layer":
            columns["u_Ue"] = data.get("x", [])
            columns["y_wall"] = data.get("y", [])
        elif chart_type == "histogram":
            columns["bin_center"] = data.get("x", [])
            columns["count"] = data.get("y", [])
        elif chart_type == "force_distribution":
            columns["section"] = data.get("x", [])
            for series_name, values in data.get("series", {}).items():
                columns[series_name] = values
        else:
            columns["x"] = data.get("x", [])
            columns["y"] = data.get("y", [])

        producer = create_table_source(columns, name=proxy_name)
        
        # Store chart metadata (title, labels) keyed by proxy name
        # FieldData on vtkTable is unreliable in pvserver mode, so we store it here
        if not hasattr(self, '_chart_metadata'):
            self._chart_metadata = {}
        self._chart_metadata[proxy_name] = chart_metadata
        
        logging.debug(f"[_create_chart_table] Created proxy '{proxy_name}', ID={producer.GetGlobalIDAsString()}")
        
        # Register as internal proxy so it doesn't show visibility toggle in pipeline browser
        # (vtkTable has no 3D representation)
        if self._app and hasattr(self._app, 'ctrl') and self._app.ctrl.register_internal_proxy.exists():
            self._app.ctrl.register_internal_proxy(producer)
            logging.debug(f"[_create_chart_table] Registered as internal proxy")
        
        self._notify_pipeline_changed()
        
        return proxy_name
    
    def get_chart_proxy(self, proxy_name: str):
        """Get a chart data proxy by name."""
        return simple.FindSource(proxy_name)

    def get_chart_metadata(self, proxy_name: str) -> dict:
        """Get stored metadata (title, labels, chart_type) for a chart proxy."""
        meta = getattr(self, '_chart_metadata', {})
        return meta.get(proxy_name, {})
    
    def _render_chart(self, proxy_name: str):
        """Render a chart by proxy name if app is available."""
        logging.debug(f"[_render_chart] proxy_name={proxy_name}, app={self._app is not None}")
        if self._app and hasattr(self._app, 'render_chart_from_proxy'):
            logging.debug(f"[_render_chart] Calling render_chart_from_proxy")
            self._app.render_chart_from_proxy(proxy_name)
        else:
            logging.debug(f"[_render_chart] Cannot render - app or render_chart_from_proxy not available")
    
    def _render_chart_direct(self, chart_data: dict):
        """Render a chart directly from data dict (for complex charts that don't fit vtkTable)."""
        logging.debug(f"[_render_chart_direct] chart_type={chart_data.get('chart_type')}, app={self._app is not None}")
        if self._app and hasattr(self._app, 'render_analysis_chart'):
            self._app.render_analysis_chart(chart_data)
        else:
            logging.debug(f"[_render_chart_direct] Cannot render - app or render_analysis_chart not available")
    
    def _register_provenance(self, proxy_name: str, provenance: dict):
        """Register provenance for a proxy to enable chaining."""
        if proxy_name and provenance:
            self._provenance_registry[proxy_name] = provenance
    
    def _get_input_provenance(self, proxy_name: str) -> dict:
        """Get provenance for an input proxy if it was created by a workflow."""
        return self._provenance_registry.get(proxy_name)
    
    def _get_data_reader(self):
        """Get the original data reader or Live-extracted source."""
        # Skip temporary readers like CSVReader created by charts
        skip_types = ['CSVReader', 'DelimitedTextReader']
        
        # Debug: list all sources
        logging.debug(f"[_get_data_reader] Available sources:")
        for name, proxy in simple.GetSources().items():
            source_name = name[0] if isinstance(name, tuple) else name
            xml_name = proxy.GetXMLName()
            logging.debug(f"[_get_data_reader]   '{source_name}' -> {xml_name}")
        
        # First, look for traditional file readers
        for name, proxy in simple.GetSources().items():
            xml_name = proxy.GetXMLName()
            if 'Reader' in xml_name and xml_name not in skip_types:
                logging.debug(f"[_get_data_reader] Found reader: {name[0]} ({xml_name})")
                return proxy
        
        # For Live data, look for TrivialProducer sources named "volume" or "surface"
        # Prefer "volume" over "surface"
        for preferred in ['volume', 'surface']:
            for name, proxy in simple.GetSources().items():
                source_name = name[0] if isinstance(name, tuple) else name
                xml_name = proxy.GetXMLName()
                # Check both TrivialProducer and PVTrivialProducer
                if 'TrivialProducer' in xml_name and source_name == preferred:
                    logging.debug(f"[_get_data_reader] Found Live source: {source_name}")
                    return proxy
        
        # Fall back to active source
        active = simple.GetActiveSource()
        logging.debug(f"[_get_data_reader] Falling back to active source: {active.GetXMLName() if active else None}")
        return active
    
    def _get_proxy_name(self, proxy):
        """Get name of a proxy."""
        for name, p in simple.GetSources().items():
            if p == proxy:
                return name[0]
        return None
    
    def _get_dataset_filename(self, proxy) -> str:
        """Get dataset filename from a proxy."""
        if hasattr(proxy, 'FileName'):
            fn = proxy.FileName
            if hasattr(fn, '__iter__') and not isinstance(fn, str):
                fn = list(fn)
                return fn[0] if fn else "unknown"
            return str(fn)
        return "unknown"

    def get_fields(self, proxy_name: str = None) -> dict:
        """
        Get available fields on a data source.
        
        Args:
            proxy_name: Data source name (uses first reader if not specified)
            
        Returns:
            Dict with point_fields and cell_fields, each listing field names and ranges
        """
        if proxy_name:
            proxy = simple.FindSource(proxy_name)
        else:
            proxy = self._get_data_reader()
        
        if proxy is None:
            return {"error": "No data source found"}
        
        simple.UpdatePipeline(proxy=proxy)
        di = proxy.GetDataInformation()
        
        point_fields = []
        point_info = di.GetPointDataInformation()
        for i in range(point_info.GetNumberOfArrays()):
            arr = point_info.GetArrayInformation(i)
            name = arr.GetName()
            components = arr.GetNumberOfComponents()
            ranges = []
            for c in range(components):
                r = arr.GetComponentRange(c)
                ranges.append([r[0], r[1]])
            point_fields.append({
                "name": name,
                "components": components,
                "range": ranges[0] if components == 1 else ranges
            })
        
        cell_fields = []
        cell_info = di.GetCellDataInformation()
        for i in range(cell_info.GetNumberOfArrays()):
            arr = cell_info.GetArrayInformation(i)
            name = arr.GetName()
            components = arr.GetNumberOfComponents()
            ranges = []
            for c in range(components):
                r = arr.GetComponentRange(c)
                ranges.append([r[0], r[1]])
            cell_fields.append({
                "name": name,
                "components": components,
                "range": ranges[0] if components == 1 else ranges
            })
        
        return {
            "proxy_name": self._get_proxy_name(proxy),
            "point_fields": point_fields,
            "cell_fields": cell_fields,
            "tip": "Say 'change coloring' with a field name to update visualization coloring."
        }

    def show_vortices(
        self,
        method: str = "q_criterion",
        color_by: str = "Velocity"
    ) -> dict:
        """
        Show vortex structures using Q-criterion, vorticity, or lambda2.

        Args:
            method: "q_criterion" (default), "vorticity", or "lambda2"
            color_by: Field to color by (default: "Velocity")

        Returns:
            Dict with visualization info including proxy_name and full provenance
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        
        # Clear analysis log for fresh provenance
        self._mcp.clear_analysis_log()
        
        # Hide all first
        self._mcp.hide_all()
        
        # Compute vortex field (logs analysis decisions)
        vortex = self._mcp.compute_vortex_field(method=method, proxy_name=self._get_proxy_name(proxy))
        if "error" in vortex:
            return vortex
        
        # Create contour on the vortex field proxy with descriptive name
        vortex_proxy = simple.FindSource(vortex["proxy_name"])
        contour_name = f"Vortices_{method}"
        contour = simple.Contour(Input=vortex_proxy, registrationName=contour_name)
        contour.ContourBy = ['POINTS', vortex["field_name"]]
        contour.Isosurfaces = [vortex["threshold"]]
        simple.UpdatePipeline(proxy=contour)
        
        # Show and color
        display = simple.Show(contour, view)
        color_array = self._mcp._resolve_field_type(color_by, contour)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)
        
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Build provenance: filter chain from ParaView, analysis from our log
        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(contour),
            "analysis": self._mcp.get_analysis_log(),
            "display": {
                "color_by": color_array or color_by,
                "representation": "Surface"
            }
        }
        
        # Register for chaining
        self._register_provenance(contour_name, provenance)
        self._notify_pipeline_changed()
        
        return {
            "status": "created",
            "type": "vortex_isosurface", 
            "method": method,
            "proxy_name": contour_name,
            "provenance": provenance,
            "result": {
                "field": vortex["field_name"],
                "threshold": vortex["threshold"],
                "field_range": vortex.get("field_range")
            },
            "tip": f"Threshold {vortex['threshold']:.2f} is auto-computed. Say 'show more structures' or 'show fewer structures' to adjust, or 'make it wireframe' to change style."
        }

    def show_streamlines(
        self,
        color_by: str = "Velocity",
        num_points: int = 100,
        seed_source: str = None,
    ) -> dict:
        """
        Show streamlines seeded from an existing pipeline source or the auto-detected wake.

        Args:
            color_by: Field to color by (default: "Velocity")
            num_points: Number of seed points when using auto wake seeding (default: 100)
            seed_source: Name of any existing pipeline proxy to use as seed points.
                         Can be any source visible in the pipeline browser — a slice,
                         surface extraction, vortex contour, custom geometry, etc.
                         Use list_data() to see available proxy names.
                         If None, seeds are auto-placed in the wake region.

        Returns:
            Dict with visualization info including proxy_name and provenance
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)

        self._mcp.clear_analysis_log()
        self._mcp.hide_all()

        vel_field = self._mcp._resolve_field_type("velocity", proxy)

        if seed_source:
            # Use an existing proxy as the seed source
            seed_proxy = simple.FindSource(seed_source)
            if seed_proxy is None:
                return {"error": f"Seed source '{seed_source}' not found in pipeline"}

            stream_name = f"Streamlines_{seed_source}"
            stream = simple.StreamTracer(
                Input=proxy,
                Source=seed_proxy,
                registrationName=stream_name,
            )
            stream.Vectors = ['POINTS', vel_field]
            simple.UpdatePipeline(proxy=stream)
            seed_info = {"type": "proxy", "source": seed_source}
        else:
            # Auto-place seeds in the wake region
            seed = self._mcp.compute_streamline_seed(proxy_name=proxy_name)
            if "error" in seed:
                return seed

            stream_name = "Streamlines_wake"
            stream = simple.StreamTracer(Input=proxy, registrationName=stream_name)
            stream.SeedType = "Point Cloud"
            stream.SeedType.Set(
                Center=seed["center"],
                Radius=seed["radius"],
                NumberOfPoints=num_points,
            )
            stream.MaximumStreamlineLength = seed["max_length"]
            stream.Vectors = ['POINTS', vel_field]
            simple.UpdatePipeline(proxy=stream)
            seed_info = {"type": "wake", "center": seed["center"], "radius": seed["radius"]}

        # Show and color
        display = simple.Show(stream, view)
        color_array = self._mcp._resolve_field_type(color_by, stream)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)

        simple.ResetCamera(view)
        simple.Render(view)

        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(stream),
            "analysis": self._mcp.get_analysis_log(),
            "seed": seed_info,
            "display": {"color_by": color_array or color_by, "representation": "Surface"},
        }

        self._register_provenance(stream_name, provenance)
        self._notify_pipeline_changed()

        tip = f"To refine: update_color('{stream_name}', field_name='pressure') to recolor."
        if not seed_source:
            tip += " Or call show_streamlines(seed_source='Vortices_q_criterion') to seed from vortex cores."

        return {
            "status": "created",
            "type": "streamlines",
            "proxy_name": stream_name,
            "seed_source": seed_source or "wake (auto)",
            "provenance": provenance,
            "ontology_hints": self._ontology_hints([
                "causal_relationships.drag_increase",
            ]),
            "tip": tip,
        }

    def show_slice(
        self,
        location: str = "wake",
        normal: str = "auto",
        offset: float = 0.0,
        color_by: str = "Velocity",
        representation: str = "Surface"
    ) -> dict:
        """
        Show a slice through the data.
        
        Args:
            location: Where to place the slice:
                - "wake": At wake centroid, normal to streamwise direction
                - "center": At body center
                - "span" or "spanwise": Perpendicular to span direction (for airfoil sections)
            normal: Slice normal direction:
                - "auto": Determined by location (streamwise for wake, span for spanwise)
                - "x", "y", "z": Explicit axis
            offset: For "span" location, offset from center as fraction of span (-1 to 1)
            color_by: Field to color by (default: "Velocity")
            representation: "Surface" or "Surface LIC" for flow patterns
            
        Returns:
            Dict with visualization info including proxy_name and provenance
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)
        
        # Clear analysis log for fresh provenance
        self._mcp.clear_analysis_log()
        
        # Hide all first
        self._mcp.hide_all()
        
        # Determine slice parameters based on location (logs analysis decisions)
        if location in ("span", "spanwise"):
            slice_params = self._mcp.compute_spanwise_slice_params(
                offset=offset, 
                proxy_name=proxy_name
            )
            if "error" in slice_params:
                return slice_params
            
            origin = slice_params["origin"]
            slice_normal = slice_params["normal_axis"] if normal == "auto" else normal
            span_axis = slice_params["normal_axis"]
            streamwise_axis = slice_params["streamwise_axis"]
            body_bounds = slice_params["body_bounds"]
            location = f"span (offset={offset:.2f})"
            
        else:
            span_info = self._mcp.detect_span_direction(proxy_name=proxy_name)
            span_axis = span_info.get("span_axis", "z")
            streamwise_axis = span_info.get("streamwise_axis", "x")
            body_bounds = span_info.get("body_bounds")
            
            if location == "wake":
                wake = self._mcp.detect_wake_region(proxy_name=proxy_name)
                if "error" in wake:
                    seed = self._mcp.compute_streamline_seed(proxy_name=proxy_name)
                    if "error" not in seed:
                        origin = seed["center"]
                        location = "downstream (wake detection failed)"
                    else:
                        params = self._mcp.compute_slice_params(normal=normal if normal != "auto" else "x", proxy_name=proxy_name)
                        if "error" in params:
                            return params
                        origin = params["origin"]
                        location = "center (wake detection failed)"
                else:
                    origin = wake["wake_centroid"]
                slice_normal = streamwise_axis if normal == "auto" else normal
                
            elif location == "center":
                params = self._mcp.compute_slice_params(normal=normal if normal != "auto" else "x", proxy_name=proxy_name)
                if "error" in params:
                    return params
                origin = params["origin"]
                slice_normal = normal if normal != "auto" else "x"
                
            else:
                return {"error": f"Unknown location: {location}. Use 'wake', 'center', or 'span'"}
        
        # Normal vector
        normal_map = {"x": [1,0,0], "y": [0,1,0], "z": [0,0,1]}
        normal_vec = normal_map.get(slice_normal.lower(), [1,0,0])
        
        # For span slices, show body context first
        if location.startswith("span"):
            self._mcp.show_data_context(proxy_name=proxy_name, opacity=0.3)
        
        # Create slice with descriptive name
        slice_name = f"Slice_{location}"
        slice_filter = simple.Slice(Input=proxy, registrationName=slice_name)
        slice_filter.SliceType = 'Plane'
        slice_filter.SliceType.Origin = origin
        slice_filter.SliceType.Normal = normal_vec
        simple.UpdatePipeline(proxy=slice_filter)
        
        # Debug: verify parent relationship
        logging.debug(f"[show_slice] Created {slice_name}, Input={slice_filter.Input}, Input ID={slice_filter.Input.GetGlobalIDAsString() if slice_filter.Input else None}")
        logging.debug(f"[show_slice] Parent proxy: {self._get_proxy_name(proxy)}, ID={proxy.GetGlobalIDAsString()}")
        
        # Show with representation
        display = simple.Show(slice_filter, view)
        
        if representation == "Surface LIC" and "Surface LIC" in display.Representation.Available:
            display.Representation = "Surface LIC"
            vel_field = self._mcp._resolve_field_type("velocity", slice_filter)
            display.SelectInputVectors = ['POINTS', vel_field]
            color_array = f"{vel_field} (LIC)"
        else:
            display.Representation = "Surface"
            color_array = self._mcp._resolve_field_type(color_by, slice_filter)
            if color_array:
                simple.ColorBy(display, ('POINTS', color_array))
                display.RescaleTransferFunctionToDataRange(True, False)
                display.SetScalarBarVisibility(view, True)
        
        # Set view perpendicular to slice
        self._mcp.set_view(direction=f"-{slice_normal}")
        
        # Focus on slice
        if location.startswith("span") and body_bounds:
            view.ResetCamera(body_bounds[0], body_bounds[1], 
                           body_bounds[2], body_bounds[3], 
                           body_bounds[4], body_bounds[5], False, 0.9)
        else:
            bounds = slice_filter.GetDataInformation().GetBounds()
            view.ResetCamera(*bounds, False, 0.9)
        simple.Render(view)
        
        # Build provenance
        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(slice_filter),
            "analysis": self._mcp.get_analysis_log(),
            "display": {
                "color_by": color_array or color_by,
                "representation": representation
            }
        }
        
        self._register_provenance(slice_name, provenance)
        self._notify_pipeline_changed()
        
        return {
            "status": "created",
            "type": "slice",
            "proxy_name": slice_name,
            "location": location,
            "span_axis": span_axis,
            "streamwise_axis": streamwise_axis,
            "provenance": provenance,
            "ontology_hints": self._ontology_hints([
                "causal_relationships.drag_increase",
            ]),
            "tip": f"To refine: say 'color by pressure' to recolor, or 'show mesh edges' to show mesh on '{slice_name}'."
        }

    def show_schlieren(
        self,
        field: str = "Density",
        log_scale: bool = True,
        on_slice: bool = True,
        slice_normal: str = "z",
    ) -> dict:
        """
        Show Schlieren visualization (density gradient magnitude).
        
        Schlieren imaging reveals shocks, shear layers, and expansion fans
        in compressible flows by visualizing |∇ρ|.
        
        Args:
            field: Field to compute gradient of (default: "Density")
            log_scale: Use log scale for better shock visibility (default: True)
            on_slice: If True, show on a slice; if False, volume render (default: True)
            slice_normal: Normal direction for slice: "x", "y", or "z" (default: "z")
            
        Returns:
            Dict with visualization info
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        
        # Clear analysis log for fresh provenance
        self._mcp.clear_analysis_log()
        
        # Compute Schlieren field
        result = self._mcp.compute_schlieren(
            proxy_name=None,
            field=field,
            log_scale=log_scale,
        )
        
        if "error" in result:
            return result
        
        schlieren_proxy = simple.FindSource(result["proxy_name"])
        field_name = result["field_name"]
        
        if on_slice:
            # Create a slice through the center
            bounds = schlieren_proxy.GetDataInformation().GetBounds()
            center = [(bounds[i*2] + bounds[i*2+1]) / 2 for i in range(3)]
            
            normal_map = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
            normal_vec = normal_map.get(slice_normal.lower(), [0, 0, 1])
            
            slice_name = f"Schlieren_Slice"
            slice_filter = simple.Slice(Input=schlieren_proxy, registrationName=slice_name)
            slice_filter.SliceType = 'Plane'
            slice_filter.SliceType.Origin = center
            slice_filter.SliceType.Normal = normal_vec
            simple.UpdatePipeline(proxy=slice_filter)
            
            display_proxy = slice_filter
            output_name = slice_name
        else:
            display_proxy = schlieren_proxy
            output_name = result["proxy_name"]
        
        # Show with grayscale colormap (traditional Schlieren look)
        display = simple.Show(display_proxy, view)
        display.Representation = "Surface"
        simple.ColorBy(display, ('POINTS', field_name))
        
        # Apply grayscale colormap
        lut = simple.GetColorTransferFunction(field_name)
        lut.ApplyPreset('Grayscale', True)
        
        # Set range
        field_range = result["field_range"]
        lut.RescaleTransferFunction(field_range[0], field_range[1])
        
        display.SetScalarBarVisibility(view, True)
        
        # Set view perpendicular to slice
        if on_slice:
            self._mcp.set_view(direction=f"-{slice_normal}")
        
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Build provenance
        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(display_proxy),
            "analysis": self._mcp.get_analysis_log(),
            "display": {
                "color_by": field_name,
                "colormap": "Grayscale",
                "log_scale": log_scale,
            }
        }
        
        self._register_provenance(output_name, provenance)
        self._notify_pipeline_changed()
        
        return {
            "status": "created",
            "type": "schlieren",
            "proxy_name": output_name,
            "field_name": field_name,
            "field_range": field_range,
            "log_scale": log_scale,
            "provenance": provenance,
            "description": "Schlieren visualization showing density gradient magnitude",
            "tip": "Bright regions indicate strong density gradients (shocks, shear layers)."
        }

    def show_shadowgraph(
        self,
        field: str = "Density",
        on_slice: bool = True,
        slice_normal: str = "z",
    ) -> dict:
        """
        Show Shadowgraph visualization (Laplacian of density).
        
        Shadowgraph imaging shows the second derivative of density (∇²ρ),
        highlighting shock edges more sharply than Schlieren.
        
        Args:
            field: Field to compute Laplacian of (default: "Density")
            on_slice: If True, show on a slice; if False, volume render (default: True)
            slice_normal: Normal direction for slice: "x", "y", or "z" (default: "z")
            
        Returns:
            Dict with visualization info
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        
        # Clear analysis log for fresh provenance
        self._mcp.clear_analysis_log()
        
        # Compute Shadowgraph field
        result = self._mcp.compute_shadowgraph(
            proxy_name=None,
            field=field,
        )
        
        if "error" in result:
            return result
        
        shadowgraph_proxy = simple.FindSource(result["proxy_name"])
        field_name = result["field_name"]
        
        if on_slice:
            # Create a slice through the center
            bounds = shadowgraph_proxy.GetDataInformation().GetBounds()
            center = [(bounds[i*2] + bounds[i*2+1]) / 2 for i in range(3)]
            
            normal_map = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
            normal_vec = normal_map.get(slice_normal.lower(), [0, 0, 1])
            
            slice_name = f"Shadowgraph_Slice"
            slice_filter = simple.Slice(Input=shadowgraph_proxy, registrationName=slice_name)
            slice_filter.SliceType = 'Plane'
            slice_filter.SliceType.Origin = center
            slice_filter.SliceType.Normal = normal_vec
            simple.UpdatePipeline(proxy=slice_filter)
            
            display_proxy = slice_filter
            output_name = slice_name
        else:
            display_proxy = shadowgraph_proxy
            output_name = result["proxy_name"]
        
        # Show with grayscale colormap
        display = simple.Show(display_proxy, view)
        display.Representation = "Surface"
        simple.ColorBy(display, ('POINTS', field_name))
        
        # Apply grayscale colormap
        lut = simple.GetColorTransferFunction(field_name)
        lut.ApplyPreset('Grayscale', True)
        
        # Set range (symmetric around zero for Laplacian)
        field_range = result["field_range"]
        max_abs = max(abs(field_range[0]), abs(field_range[1]))
        lut.RescaleTransferFunction(-max_abs, max_abs)
        
        display.SetScalarBarVisibility(view, True)
        
        # Set view perpendicular to slice
        if on_slice:
            self._mcp.set_view(direction=f"-{slice_normal}")
        
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Build provenance
        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(display_proxy),
            "analysis": self._mcp.get_analysis_log(),
            "display": {
                "color_by": field_name,
                "colormap": "Grayscale",
            }
        }
        
        self._register_provenance(output_name, provenance)
        self._notify_pipeline_changed()
        
        return {
            "status": "created",
            "type": "shadowgraph",
            "proxy_name": output_name,
            "field_name": field_name,
            "field_range": field_range,
            "provenance": provenance,
            "description": "Shadowgraph visualization showing Laplacian of density",
            "tip": "Shows shock edges more sharply than Schlieren."
        }

    def show_histogram(
        self,
        field: str = "p",
        num_bins: int = 20
    ) -> dict:
        """
        Show histogram of a field distribution.
        
        Args:
            field: Field name - "p", "pressure", "Velocity", etc.
            num_bins: Number of histogram bins (default: 20)
            
        Returns:
            Dict with histogram info
        """
        # Find data reader name
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        proxy_name = None
        for name, p in simple.GetSources().items():
            if p == proxy:
                proxy_name = name[0]
                break
        
        result = self._mcp.create_histogram_chart(field=field, num_bins=num_bins, proxy_name=proxy_name)
        
        if "error" in result:
            return result
        
        # Create chart data proxy (vtkTable)
        chart_proxy_name = self._create_chart_table(
            chart_type="histogram",
            title=result.get("title", f"Distribution of {field}"),
            data={
                "x": result["data"]["x"],
                "y": result["data"]["y"],
                "x_label": result.get("x_label", field),
                "y_label": result.get("y_label", "Count"),
            },
            metadata={
                "field": result.get("field", field),
                "num_bins": result.get("num_bins", num_bins),
                "min": result.get("min"),
                "max": result.get("max"),
                "mean": result.get("mean"),
                "std": result.get("std"),
            }
        )
        
        # Render the chart from proxy
        self._render_chart(chart_proxy_name)
        
        # Return summary with proxy reference (no raw data)
        return {
            "status": "created",
            "chart_proxy": chart_proxy_name,
            "title": result.get("title"),
            "field": result.get("field", field),
            "num_bins": result.get("num_bins", num_bins),
            "num_points": result.get("num_points"),
            "min": round(result.get("min", 0), 6),
            "max": round(result.get("max", 0), 6),
            "mean": round(result.get("mean", 0), 6),
            "std": round(result.get("std", 0), 6),
        }

    def show_boundary_layer(self, x_over_chord: float = 0.5, span_fraction: float = 0.5, 
                            probe_length: float = None,
                            stations: object = None) -> dict:
        """
        Show boundary layer velocity profile at given chordwise and spanwise location(s).
        
        IMPORTANT: For multiple stations, pass stations as a JSON array in a SINGLE call:
          show_boundary_layer(stations=[0.1, 0.3, 0.5, 0.7, 0.9])
        Do NOT make separate calls for each station. A single call with a list is
        10x more efficient (shared infrastructure, one response).
        
        Args:
            x_over_chord: Single chordwise location as fraction of chord (0=LE, 1=TE)
            span_fraction: Spanwise location (0=root, 1=tip, default: 0.5 mid-span)
            probe_length: How far to probe into the flow (default: 30% of chord)
            stations: List of x/c values, e.g. [0.1, 0.3, 0.5, 0.7, 0.9]. Preferred over x_over_chord for multi-station.
            
        Returns:
            Dict with boundary layer profile data including delta, delta*, theta, H
        """
        import numpy as np
        
        # Multi-station mode: batch all profiles in one call
        if stations is not None:
            # Coerce single float to list
            if isinstance(stations, (int, float)):
                stations = [float(stations)]
            if isinstance(stations, list) and len(stations) > 1:
                return self._show_boundary_layer_multi(
                    stations=stations,
                    span_fraction=span_fraction,
                    probe_length=probe_length,
                )
            elif isinstance(stations, list) and len(stations) == 1:
                x_over_chord = float(stations[0])
        
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Compute boundary layer profile using cfd_analysis
        bl_data = self._mcp.compute_boundary_layer_profile(
            proxy=proxy, 
            x_over_chord=x_over_chord,
            span_fraction=span_fraction,
            probe_length=probe_length,
            proxy_name=proxy_name
        )
        
        if "error" in bl_data:
            return bl_data
        
        # Extract data for plotting
        y = np.array(bl_data["y"])
        u_normalized = np.array(bl_data["u_normalized"])
        u = np.array(bl_data["u"])
        delta = float(bl_data["delta"])
        u_edge_idx = int(bl_data["u_edge_idx"])
        
        # Truncate plot at 3x delta or edge velocity location
        plot_limit = min(3 * delta, y[u_edge_idx]) if delta > 0 else y[u_edge_idx]
        plot_mask = y <= plot_limit
        
        # Get geometry info for labels
        geom = bl_data["geometry"]
        span_axis = geom["span_axis"]
        x_over_chord_val = bl_data["x_over_chord"]
        span_absolute = bl_data["span_absolute"]
        span_frac = bl_data["span_fraction"]
        
        # Store full data for context visualization
        self._last_bl_results = getattr(self, '_last_bl_results', [])
        full_result = {
            "y": y.tolist(),
            "surface_point": bl_data["surface_point"],
            "surface_normal": bl_data["surface_normal"],
            "section": bl_data["section"],
            "probe_length": bl_data["probe_length"],
            "span_absolute": bl_data["span_absolute"],
            "x_over_chord": bl_data["x_over_chord"],
            "shape_factor": bl_data["shape_factor"],
            "delta": bl_data["delta"],
            "delta_star": bl_data["delta_star"],
            "theta": bl_data["theta"],
            "u_edge": bl_data["u_edge"],
        }
        self._last_bl_results.append(full_result)
        
        # Create chart data proxy (vtkTable)
        chart_title = f'Boundary Layer at x/c={x_over_chord_val:.2f}, {span_axis}={span_absolute:.3f} ({span_frac*100:.0f}% span)'
        
        proxy_name = self._create_chart_table(
            chart_type="boundary_layer",
            title=chart_title,
            data={
                "x": u_normalized[plot_mask].tolist(),
                "y": y[plot_mask].tolist(),
                "x_label": "u / Ue",
                "y_label": "y (distance from wall)",
            },
            metadata={
                "surface": bl_data["surface"],
                "x_over_chord": bl_data["x_over_chord"],
                "span_fraction": bl_data["span_fraction"],
                "u_edge": bl_data["u_edge"],
                "delta": bl_data["delta"],
                "delta_star": bl_data["delta_star"],
                "theta": bl_data["theta"],
                "shape_factor": bl_data["shape_factor"],
            }
        )
        
        # Render the chart from proxy
        self._render_chart(proxy_name)
        
        # Return summary with proxy reference (no raw data)
        return {
            "status": "created",
            "chart_proxy": proxy_name,
            "title": chart_title,
            "surface": bl_data["surface"],
            "x_over_chord": round(bl_data["x_over_chord"], 4),
            "span_fraction": round(bl_data["span_fraction"], 4),
            "num_points": int(plot_mask.sum()),
            # Key BL metrics
            "u_edge": round(bl_data["u_edge"], 4),
            "delta_mm": round(bl_data["delta"] * 1000, 3),
            "delta_star_mm": round(bl_data["delta_star"] * 1000, 3),
            "theta_mm": round(bl_data["theta"] * 1000, 3),
            "shape_factor": round(bl_data["shape_factor"], 3),
            "ontology_hints": self._ontology_hints([
                "flow_features.boundary_layer.metrics.shape_factor",
                "flow_features.boundary_layer.design_relevance",
            ]),
        }

    def _show_boundary_layer_multi(self, stations: list, span_fraction: float = 0.5,
                                    probe_length: float = None) -> dict:
        """Internal: compute boundary layer profiles at multiple stations in one call.
        Creates shared ExtractSurface+Clip infrastructure once, reused across all stations."""
        import numpy as np
        from paraview import simple
        from trame_llm.paraview import ensure_flat_input, safe_delete

        print(f"[BL MULTI] Entering multi-station mode with {len(stations)} stations: {stations}")

        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}

        proxy_name = self._get_proxy_name(proxy)
        self._mcp.hide_all()

        # Create shared infrastructure once
        merge, _, cleanup_merge = ensure_flat_input(proxy)
        body_bounds, _ = self._mcp._get_body_bounds(proxy)

        surface = simple.ExtractSurface(Input=merge)
        simple.UpdatePipeline(proxy=surface)

        clip = simple.Clip(Input=surface)
        clip.ClipType = 'Box'
        clip.ClipType.Bounds = [
            body_bounds[0] - 0.01, body_bounds[1] + 0.01,
            body_bounds[2] - 0.01, body_bounds[3] + 0.01,
            body_bounds[4] - 0.01, body_bounds[5] + 0.01
        ]
        clip.Invert = 1
        simple.UpdatePipeline(proxy=clip)

        results = []
        errors = []

        for xc in stations:
            bl_data = self._mcp.compute_boundary_layer_profile(
                proxy=proxy,
                x_over_chord=float(xc),
                span_fraction=span_fraction,
                probe_length=probe_length,
                proxy_name=proxy_name,
                _shared_surface=clip,
            )

            if "error" in bl_data:
                errors.append({"x_over_chord": xc, "error": bl_data["error"]})
                continue

            # Extract data for plotting
            y = np.array(bl_data["y"])
            u_normalized = np.array(bl_data["u_normalized"])
            delta = float(bl_data["delta"])
            u_edge_idx = int(bl_data["u_edge_idx"])

            plot_limit = min(3 * delta, y[u_edge_idx]) if delta > 0 else y[u_edge_idx]
            plot_mask = y <= plot_limit

            geom = bl_data["geometry"]
            span_axis = geom["span_axis"]
            x_over_chord_val = bl_data["x_over_chord"]
            span_absolute = bl_data["span_absolute"]
            span_frac = bl_data["span_fraction"]

            # Cache for context visualization
            self._last_bl_results = getattr(self, '_last_bl_results', [])
            self._last_bl_results.append({
                "y": y.tolist(),
                "surface_point": bl_data["surface_point"],
                "surface_normal": bl_data["surface_normal"],
                "section": bl_data["section"],
                "probe_length": bl_data["probe_length"],
                "span_absolute": bl_data["span_absolute"],
                "x_over_chord": bl_data["x_over_chord"],
                "shape_factor": bl_data["shape_factor"],
                "delta": bl_data["delta"],
                "delta_star": bl_data["delta_star"],
                "theta": bl_data["theta"],
                "u_edge": bl_data["u_edge"],
            })

            chart_title = f'Boundary Layer at x/c={x_over_chord_val:.2f}, {span_axis}={span_absolute:.3f} ({span_frac*100:.0f}% span)'

            chart_proxy = self._create_chart_table(
                chart_type="boundary_layer",
                title=chart_title,
                data={
                    "x": u_normalized[plot_mask].tolist(),
                    "y": y[plot_mask].tolist(),
                    "x_label": "u / Ue",
                    "y_label": "y (distance from wall)",
                },
                metadata={
                    "surface": bl_data["surface"],
                    "x_over_chord": bl_data["x_over_chord"],
                    "span_fraction": bl_data["span_fraction"],
                    "u_edge": bl_data["u_edge"],
                    "delta": bl_data["delta"],
                    "delta_star": bl_data["delta_star"],
                    "theta": bl_data["theta"],
                    "shape_factor": bl_data["shape_factor"],
                }
            )
            self._render_chart(chart_proxy)

            results.append({
                "chart_proxy": chart_proxy,
                "x_over_chord": round(bl_data["x_over_chord"], 4),
                "surface": bl_data["surface"],
                "u_edge": round(bl_data["u_edge"], 4),
                "delta_mm": round(bl_data["delta"] * 1000, 3),
                "delta_star_mm": round(bl_data["delta_star"] * 1000, 3),
                "theta_mm": round(bl_data["theta"] * 1000, 3),
                "shape_factor": round(bl_data["shape_factor"], 3),
            })

        # Clean up shared infrastructure
        safe_delete(clip)
        safe_delete(surface)
        if cleanup_merge:
            safe_delete(cleanup_merge)

        return {
            "status": "created",
            "stations_requested": len(stations),
            "stations_computed": len(results),
            "stations_failed": len(errors),
            "span_fraction": span_fraction,
            "profiles": results,
            "errors": errors if errors else None,
            "ontology_hints": self._ontology_hints([
                "flow_features.boundary_layer.metrics.shape_factor",
                "flow_features.boundary_layer.design_relevance",
            ]),
        }

    def create_section_debug_chart(self, bl_results: list = None, title: str = None) -> dict:
        """
        Create a debug chart showing airfoil section with probe locations.
        
        Args:
            bl_results: List of boundary layer result dicts (optional - uses internal cache if None)
            title: Optional chart title
            
        Returns:
            Dict with Plotly-compatible chart data
        """
        # Use internal cache if no results provided
        if bl_results is None:
            bl_results = getattr(self, '_last_bl_results', [])
        
        if not bl_results:
            return {"error": "No boundary layer results provided"}
        
        # Get section data from first valid result
        section_data = None
        for r in bl_results:
            if 'section' in r and 'suction_contour' in r['section']:
                section_data = r['section']
                break
        
        if section_data is None:
            return {"error": "No valid section data in results"}
        
        stream_idx = section_data['stream_idx']
        vert_idx = section_data['vert_idx']
        le_x = section_data['le'][stream_idx]
        chord = section_data['chord']
        
        # Build section contour data
        suction = section_data['suction_contour']
        pressure = section_data['pressure_contour']
        
        section_x = []
        section_y = []
        for pt in suction:
            section_x.append((pt[0] - le_x) / chord)
            section_y.append(pt[1] / chord)
        for pt in pressure:
            section_x.append((pt[0] - le_x) / chord)
            section_y.append(pt[1] / chord)
        
        # Build probe lines and markers
        probe_lines = []
        surface_markers_x = []
        surface_markers_y = []
        
        for r in bl_results:
            if 'error' in r:
                continue
            pt = r['surface_point']
            norm = r['surface_normal']
            probe_len = r.get('probe_length', 0.1)
            
            xc = (pt[stream_idx] - le_x) / chord
            zc = pt[vert_idx] / chord
            
            end_x = pt[stream_idx] + probe_len * norm[stream_idx]
            end_z = pt[vert_idx] + probe_len * norm[vert_idx]
            xc_end = (end_x - le_x) / chord
            zc_end = end_z / chord
            
            probe_lines.append({
                'x': [xc, xc_end],
                'y': [zc, zc_end]
            })
            surface_markers_x.append(xc)
            surface_markers_y.append(zc)
        
        chart_data = {
            "status": "created",
            "chart_type": "section_debug",
            "title": title or "Airfoil Section with Probe Locations",
            "x_label": "x/c",
            "y_label": "z/c",
            "data": {
                "section": {"x": section_x, "y": section_y},
                "probes": probe_lines,
                "markers": {"x": surface_markers_x, "y": surface_markers_y},
            },
            "num_probes": len(probe_lines),
            "section_chord": chord,
        }
        
        # Render the chart directly (complex nested structure doesn't fit vtkTable)
        self._render_chart_direct(chart_data)
        
        return {
            "status": "created",
            "chart_type": "section_debug",
            "title": chart_data["title"],
            "num_probes": len(probe_lines),
            "section_chord": round(chord, 4),
        }

    def show_boundary_layer_context(self, span_fraction: float = 0.5) -> dict:
        """
        Show boundary layer probe locations on a velocity slice.
        
        Creates a 3D visualization showing:
        - Velocity slice at the specified span station  
        - Probe markers colored by flow state (red=separation, orange=laminar, blue=turbulent)
        - Probe length proportional to boundary layer thickness
        
        This provides visual context for boundary layer analysis results.
        
        Args:
            span_fraction: Span location (0=root, 1=tip), default 0.5 (midspan)
            
        Returns:
            Dict with visualization info and probe data
        """
        import vtk
        
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        # Hide the reader
        simple.Hide(proxy, view)
        
        # Get probe data from cache, or compute it
        probe_results = getattr(self, '_last_bl_results', [])
        if not probe_results:
            # Compute BL at several locations
            for xc in [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
                r = self._mcp.compute_boundary_layer_profile(
                    x_over_chord=xc, 
                    span_fraction=span_fraction
                )
                if 'error' not in r:
                    probe_results.append(r)
        
        if not probe_results:
            return {"error": "Could not compute boundary layer profiles"}
        
        span_y = probe_results[0]['span_absolute']
        
        # Flatten composite data for slicing (reuses existing MergeBlocks)
        merge, _, _ = ensure_flat_input(proxy)
        
        slice_filter = simple.Slice(Input=merge, registrationName='BL_Context_Slice')
        slice_filter.SliceType = 'Plane'
        slice_filter.SliceType.Origin = [0.5, span_y, 0.0]
        slice_filter.SliceType.Normal = [0, 1, 0]
        simple.UpdatePipeline(proxy=slice_filter)
        
        # Clip to body region
        bounds = proxy.GetDataInformation().GetBounds()
        body_xmin = bounds[0] * 0.1 + bounds[1] * 0.9  # Approximate body region
        body_xmax = bounds[1] * 0.1 + bounds[0] * 0.9
        
        clip = simple.Clip(Input=slice_filter, registrationName='BL_Context_Clip')
        clip.ClipType = 'Box'
        clip.ClipType.Position = [0.15, span_y - 0.01, -0.15]
        clip.ClipType.Length = [0.85, 0.02, 0.30]
        clip.Invert = 1
        simple.UpdatePipeline(proxy=clip)
        
        # Show slice with velocity coloring
        vel_field = self._mcp._resolve_field_type("velocity", clip)
        clip_display = simple.Show(clip, view)
        simple.ColorBy(clip_display, ('POINTS', vel_field, 'Magnitude'))
        
        vel_lut = simple.GetColorTransferFunction(vel_field)
        vel_lut.ApplyPreset('Jet', True)
        vel_lut.RescaleTransferFunction(0.0, 0.95)
        clip_display.SetScalarBarVisibility(view, True)
        
        # Add probe markers
        probe_info = []
        for i, p in enumerate(probe_results):
            pt = p['surface_point']
            norm = p['surface_normal']
            H = p['shape_factor']
            delta = p['delta']
            
            # Create tube from surface along normal
            line = simple.Line(registrationName=f'BL_Probe_{i}')
            line.Point1 = [pt[0], span_y, pt[2]]
            end_pt = [pt[0] + delta * 4 * norm[0], span_y, pt[2] + delta * 4 * norm[2]]
            line.Point2 = end_pt
            simple.UpdatePipeline(proxy=line)
            
            tube = simple.Tube(Input=line, registrationName=f'BL_Probe_Tube_{i}')
            tube.Radius = 0.003
            simple.UpdatePipeline(proxy=tube)
            
            display = simple.Show(tube, view)
            
            # Color by flow state
            if H > 3.5:
                display.DiffuseColor = [1.0, 0.2, 0.2]  # Red - separation
                state = "separation"
            elif H > 2.0:
                display.DiffuseColor = [1.0, 0.6, 0.2]  # Orange - transitional
                state = "transitional"
            else:
                display.DiffuseColor = [0.2, 0.5, 1.0]  # Blue - turbulent
                state = "turbulent"
            
            probe_info.append({
                "x_over_chord": round(p['x_over_chord'], 2),
                "shape_factor": round(H, 2),
                "delta_mm": round(delta * 1000, 2),
                "state": state
            })
        
        # Compute camera to frame all probes
        if probe_results:
            x_coords = [p['surface_point'][0] for p in probe_results]
            z_coords = [p['surface_point'][2] for p in probe_results]
            x_min, x_max = min(x_coords), max(x_coords)
            z_min, z_max = min(z_coords), max(z_coords)
            
            # Center of all probes
            x_center = (x_min + x_max) / 2
            z_center = (z_min + z_max) / 2
            
            # Distance based on extent - need to see full chord
            x_extent = x_max - x_min
            z_extent = z_max - z_min
            extent = max(x_extent, z_extent, 0.4)  # Minimum extent for good framing
            
            # Pull camera back enough to see everything with margin
            distance = extent * 1.2
            
            view.CameraPosition = [x_min - extent * 0.3, span_y - distance, z_center + extent * 0.3]
            view.CameraFocalPoint = [x_center, span_y, z_center]
            view.CameraViewUp = [0, 0, 1]
        
        simple.Render(view)
        
        return {
            "status": "created",
            "type": "boundary_layer_context",
            "span_fraction": span_fraction,
            "span_y": round(span_y, 4),
            "num_probes": len(probe_info),
            "probes": probe_info,
            "legend": {
                "red": "separation (H > 3.5)",
                "orange": "transitional (2.0 < H < 3.5)",
                "blue": "turbulent (H < 2.0)"
            },
            "ontology_hints": self._ontology_hints([
                "flow_features.boundary_layer.metrics.shape_factor",
                "flow_features.boundary_layer.design_relevance",
            ]),
            "tip": "Camera is set to frame all probes. Call save_all_charts() for BL charts, then save_screenshot() directly (do NOT call set_view first)."
        }

    def show_flow_topology(self) -> dict:
        """
        Show flow topology using vortex core detection.
        
        Uses VTK's VortexCores filter to identify vortex core lines in the flow.
        This is more appropriate for external aerodynamics than critical point
        analysis, which finds spurious points on no-slip walls.
        
        Returns:
            Dict with vortex core information
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        # Hide all first
        self._mcp.hide_all()
        
        # Get vortex cores from compute function
        topo_data = self._mcp.compute_flow_topology(
            proxy_name=self._get_proxy_name(proxy)
        )
        
        if "error" in topo_data:
            return topo_data
        
        n_cores = topo_data["n_cores"]
        n_points = topo_data["n_points"]
        bounds = topo_data["bounds"]
        vortex_filter = topo_data["vortex_filter"]
        
        # Visualize vortex cores
        if n_cores > 0:
            display = simple.Show(vortex_filter, view)
            display.Representation = 'Surface'
            display.LineWidth = 3.0
            display.AmbientColor = [1.0, 0.2, 0.2]  # Red
            display.DiffuseColor = [1.0, 0.2, 0.2]
            simple.RenameSource('VortexCores', vortex_filter)
        
        simple.ResetCamera(view)
        simple.Render(view)
        
        result = {
            "status": "created",
            "type": "flow_topology",
            "proxy_name": "VortexCores",
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["MergeBlocks", "VortexCores"],
                "arrays_used": ["Velocity"],
                "parameters": {}
            },
            "result": {
                "vortex_cores": n_cores,
                "vortex_points": n_points,
                "bounds": bounds
            },
            "tip": "To refine: say 'show as points' or 'color vortex cores by velocity'."
        }
        
        return result

    def show_force_surface(self, margin_frac: float = 0.02) -> dict:
        """
        Show the surface used for force integration, colored by body_mask.

        Green (body_mask=1) cells were included in the force integration.
        Red (body_mask=0) cells were excluded as farfield boundary faces.

        Use this to verify the body_mask threshold is capturing the right surface.
        Adjust margin_frac (default 0.02 = 2% of domain extent) if cells are
        incorrectly included or excluded.

        Args:
            margin_frac: Fraction of domain extent used as exclusion margin (default 0.02)

        Returns:
            Dict with proxy_name, num_total_cells, margin_frac
        """
        from trame_llm.paraview import ensure_flat_input, safe_delete

        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data source found"}

        self._mcp.hide_all()

        flat_proxy, _, cleanup = ensure_flat_input(proxy)
        surface = simple.ExtractSurface(Input=flat_proxy)
        simple.UpdatePipeline(proxy=surface)
        normals = simple.SurfaceNormals(Input=surface)
        normals.ComputeCellNormals = 1
        simple.UpdatePipeline(proxy=normals)

        # Tag cells with body_mask scalar via ProgrammableFilter directly
        # (run_server_script forces vtkTable output; we need vtkPolyData passthrough)
        script = f"""
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0].VTKObject
output.ShallowCopy(inp)

n_cells = inp.GetNumberOfCells()
centers = np.zeros((n_cells, 3))
for i in range(n_cells):
    cell = inp.GetCell(i)
    pts = vtk_to_numpy(cell.GetPoints().GetData())
    centers[i] = pts.mean(axis=0)

bounds = inp.GetBounds()
margin_frac = {margin_frac}
mask = np.ones(n_cells, dtype=np.float32)
for ax in range(3):
    lo = bounds[ax*2]     + margin_frac * (bounds[ax*2+1] - bounds[ax*2])
    hi = bounds[ax*2+1]   - margin_frac * (bounds[ax*2+1] - bounds[ax*2])
    mask *= ((centers[:, ax] > lo) & (centers[:, ax] < hi)).astype(np.float32)

arr = numpy_to_vtk(mask, deep=True)
arr.SetName("body_mask")
output.GetCellData().AddArray(arr)
"""
        tagged = simple.ProgrammableFilter(
            Input=normals,
            registrationName="ForceIntegrationSurface",
        )
        tagged.Script = script
        tagged.OutputDataSetType = "vtkPolyData"
        simple.UpdatePipeline(proxy=tagged)

        n_total = int(tagged.GetDataInformation().GetNumberOfCells())

        # Show colored by body_mask
        display = simple.Show(tagged, view)
        simple.ColorBy(display, ('CELLS', 'body_mask'))
        lut = simple.GetColorTransferFunction('body_mask')
        lut.RGBPoints = [0.0, 0.8, 0.2, 0.2,   # red = excluded farfield
                         1.0, 0.2, 0.8, 0.2]    # green = included body
        lut.ColorSpace = 'RGB'
        display.SetScalarBarVisibility(view, True)
        simple.ResetCamera(view)
        simple.Render(view)

        # Clean up intermediates; keep tagged surface visible
        safe_delete(normals)
        if cleanup:
            safe_delete(cleanup)

        self._notify_pipeline_changed()

        return {
            "status": "created",
            "proxy_name": "ForceIntegrationSurface",
            "margin_frac": margin_frac,
            "num_total_cells": n_total,
            "tip": "Green = included in force integration. Red = excluded as farfield. "
                   "Adjust margin_frac if cells are wrong.",
        }

    def show_forces(self) -> dict:
        """
        Show force distribution along the body.

        Builds the body surface pipeline once and shares it across:
        - Force distribution chart (drag + lift vs. chordwise position)
        - Force integration (total Cd, Cl, drag, lift)
        - Projected area computation (stencil + render cross-check)
        - ForceIntegrationSurface proxy (tagged green/red, left hidden in pipeline)

        Returns:
            Dict with force distribution info, integrated Cl/Cd/lift/drag,
            area comparison, and area_image path.
        """
        from trame_llm.paraview import ensure_flat_input, safe_delete

        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}

        proxy_name = None
        for name, p in simple.GetSources().items():
            if p == proxy:
                proxy_name = name[0]
                break

        view = simple.GetActiveView()

        # Remove previous ForceIntegrationSurface and its pipeline if present,
        # so we don't accumulate stale proxies across repeated show_forces calls.
        prev = simple.FindSource("ForceIntegrationSurface")
        if prev is not None:
            # Walk up the input chain and collect all temporary ancestors
            # (they were all created by the previous show_forces call)
            to_delete = []
            cur = prev
            while cur is not None:
                to_delete.append(cur)
                inp = getattr(cur, 'Input', None)
                cur = inp if inp is not None else None
                # Stop at the data reader — don't delete the original source
                if cur is not None and cur == proxy:
                    break
            for p in to_delete:
                try:
                    simple.Delete(p)
                except Exception:
                    pass
        # ExtractSurface → Clip (body bounds) → ExtractSurface (polydata) → SurfaceNormals
        # All analysis functions reuse shared_normals; projected area reuses body_surf.
        body_bounds, _ = self._mcp._get_body_bounds(proxy)
        flat_proxy, _, cleanup = ensure_flat_input(proxy)
        full_surf = simple.ExtractSurface(Input=flat_proxy)
        simple.UpdatePipeline(proxy=full_surf)
        body_clip = simple.Clip(Input=full_surf)
        body_clip.ClipType = 'Box'
        body_clip.ClipType.Bounds = [
            body_bounds[0] - 0.01, body_bounds[1] + 0.01,
            body_bounds[2] - 0.01, body_bounds[3] + 0.01,
            body_bounds[4] - 0.01, body_bounds[5] + 0.01,
        ]
        body_clip.Invert = 1
        simple.UpdatePipeline(proxy=body_clip)
        body_surf = simple.ExtractSurface(Input=body_clip)  # vtkPolyData
        simple.UpdatePipeline(proxy=body_surf)
        shared_normals = simple.SurfaceNormals(Input=body_surf)
        shared_normals.ComputeCellNormals = 1
        simple.UpdatePipeline(proxy=shared_normals)

        # ── ForceIntegrationSurface: tag cells with body_mask, leave hidden ──
        margin_frac = 0.02
        tag_script = f"""
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
inp = inputs[0].VTKObject
output.ShallowCopy(inp)
n_cells = inp.GetNumberOfCells()
centers = np.zeros((n_cells, 3))
for i in range(n_cells):
    cell = inp.GetCell(i)
    pts = vtk_to_numpy(cell.GetPoints().GetData())
    centers[i] = pts.mean(axis=0)
bounds = inp.GetBounds()
mf = {margin_frac}
mask = np.ones(n_cells, dtype=np.float32)
for ax in range(3):
    lo = bounds[ax*2]   + mf*(bounds[ax*2+1]-bounds[ax*2])
    hi = bounds[ax*2+1] - mf*(bounds[ax*2+1]-bounds[ax*2])
    mask *= ((centers[:,ax]>lo)&(centers[:,ax]<hi)).astype(np.float32)
arr = numpy_to_vtk(mask, deep=True)
arr.SetName("body_mask")
output.GetCellData().AddArray(arr)
"""
        try:
            tagged = simple.ProgrammableFilter(
                Input=shared_normals,
                registrationName="ForceIntegrationSurface",
            )
            tagged.Script = tag_script
            tagged.OutputDataSetType = "vtkPolyData"
            simple.UpdatePipeline(proxy=tagged)
            display = simple.Show(tagged, view)
            simple.ColorBy(display, ('CELLS', 'body_mask'))
            lut = simple.GetColorTransferFunction('body_mask')
            lut.RGBPoints = [0.0, 0.8, 0.2, 0.2, 1.0, 0.2, 0.8, 0.2]
            lut.ColorSpace = 'RGB'
            simple.Hide(tagged, view)
        except Exception as e:
            import logging
            logging.warning(f"[show_forces] Could not build ForceIntegrationSurface: {e}")

        # ── Force distribution chart (reuses shared_normals) ─────────────────
        result = self._mcp.create_force_distribution_chart(
            proxy_name=proxy_name,
            _shared_normals=shared_normals,
        )

        # ── Force integration for Cl/Cd (reuses shared_normals + body_surf) ──
        forces = self._mcp.compute_forces(
            proxy_name=proxy_name,
            _shared_normals=shared_normals,
            _shared_body_surf=body_surf,
        )

        # ── Clean up shared pipeline (keep ForceIntegrationSurface) ──────────
        safe_delete(shared_normals)
        safe_delete(body_surf)
        safe_delete(body_clip)
        safe_delete(full_surf)
        if cleanup:
            safe_delete(cleanup)

        if "error" in result:
            return result

        # ── Chart ─────────────────────────────────────────────────────────────
        chart_proxy_name = self._create_chart_table(
            chart_type="force_distribution",
            title=result.get("title", "Force Distribution"),
            data={
                "x": result["data"]["x"],
                "series": result["data"]["series"],
                "x_label": result.get("x_label", "Position"),
                "y_label": result.get("y_label", "Force"),
            },
            metadata={
                "force_axis":        result.get("force_axis"),
                "lift_axis":         result.get("lift_axis"),
                "distribution_axis": result.get("distribution_axis"),
                "total_drag":        result.get("total_drag"),
                "total_lift":        result.get("total_lift"),
            }
        )
        self._render_chart(chart_proxy_name)
        self._notify_pipeline_changed()

        area_image = forces.get("area_image") if "error" not in forces else None

        # Render the silhouette image in the chart drawer
        if area_image:
            self._render_chart_direct({
                "chart_type": "projected_area_image",
                "title":      "Frontal Area Silhouette",
                "data":       {"image_path": area_image},
            })

        return {
            "status":            "created",
            "chart_proxy":       chart_proxy_name,
            "title":             result.get("title"),
            "force_axis":        result.get("force_axis"),
            "lift_axis":         result.get("lift_axis"),
            "distribution_axis": result.get("distribution_axis"),
            "total_drag":        round(result.get("total_drag", 0), 6),
            "total_lift":        round(result.get("total_lift", 0), 6),
            "num_bins":          result.get("num_bins"),
            "num_body_cells":    result.get("num_body_cells"),
            "drag":   round(forces.get("drag_force", 0), 6) if "error" not in forces else None,
            "lift":   round(forces.get("lift_force", 0), 6) if "error" not in forces else None,
            "Cd":     round(forces.get("Cd", 0), 6)         if "error" not in forces else None,
            "Cl":     round(forces.get("Cl", 0), 6)         if "error" not in forces else None,
            "reference_area": forces.get("reference_area")  if "error" not in forces else None,
            "area_image":     area_image,
            "pipeline":       "ForceIntegrationSurface added (hidden) — show/hide via pipeline browser",
            "ontology_hints": self._ontology_hints([
                "causal_relationships.drag_increase",
                "causal_relationships.lift_change",
            ]),
        }



    def analyze_data(self) -> dict:
        """
        Analyze the loaded dataset and provide recommendations.
        
        Returns:
            Dict with simulation type, available fields, and recommendations
        """
        # Find data reader name
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        proxy_name = None
        for name, p in simple.GetSources().items():
            if p == proxy:
                proxy_name = name[0]
                break
        
        result = self._mcp.characterize_dataset(proxy_name=proxy_name)
        if "error" not in result:
            result["tip"] = "Use the 'applicable_tools' list to see which show_* workflows will work with this dataset."
        return result
