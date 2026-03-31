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
    
    def __init__(self, cfd_analysis, on_pipeline_changed=None, app=None):
        """
        Initialize with reference to CFDAnalysis for internal tool access.
        
        Args:
            cfd_analysis: CFDAnalysis instance
            on_pipeline_changed: Optional callback to notify when pipeline changes
            app: Optional trame app for rendering charts
        """
        self._mcp = cfd_analysis  # Keep as _mcp for minimal code changes
        self._provenance_registry = {}  # proxy_name -> provenance dict
        self._on_pipeline_changed = on_pipeline_changed
        self._app = app
        self._chart_counter = 0
    
    def _notify_pipeline_changed(self):
        """Notify that pipeline has changed (for UI updates like pipeline browser)."""
        # Use trame's controller if available (this is what ptc's PipelineBrowser listens to)
        if self._app and hasattr(self._app, 'ctrl'):
            if self._app.ctrl.on_data_change.exists():
                print(f"[_notify_pipeline_changed] Calling app.ctrl.on_data_change()")
                self._app.ctrl.on_data_change()
            # Also try view_update which triggers render
            if self._app.ctrl.view_update.exists():
                self._app.ctrl.view_update()
        else:
            print(f"[_notify_pipeline_changed] No ctrl - app={self._app is not None}")
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
        
        print(f"[_create_chart_table] Created proxy '{proxy_name}', ID={producer.GetGlobalIDAsString()}")
        
        # Register as internal proxy so it doesn't show visibility toggle in pipeline browser
        # (vtkTable has no 3D representation)
        if self._app and hasattr(self._app, 'ctrl') and self._app.ctrl.register_internal_proxy.exists():
            self._app.ctrl.register_internal_proxy(producer)
            print(f"[_create_chart_table] Registered as internal proxy")
        
        self._notify_pipeline_changed()
        
        return proxy_name
    
    def get_chart_proxy(self, proxy_name: str):
        """Get a chart data proxy by name."""
        return simple.FindSource(proxy_name)
    
    def _render_chart(self, proxy_name: str):
        """Render a chart by proxy name if app is available."""
        print(f"[_render_chart] proxy_name={proxy_name}, app={self._app is not None}")
        if self._app and hasattr(self._app, 'render_chart_from_proxy'):
            print(f"[_render_chart] Calling render_chart_from_proxy")
            self._app.render_chart_from_proxy(proxy_name)
        else:
            print(f"[_render_chart] Cannot render - app or render_chart_from_proxy not available")
    
    def _render_chart_direct(self, chart_data: dict):
        """Render a chart directly from data dict (for complex charts that don't fit vtkTable)."""
        print(f"[_render_chart_direct] chart_type={chart_data.get('chart_type')}, app={self._app is not None}")
        if self._app and hasattr(self._app, 'render_analysis_chart'):
            self._app.render_analysis_chart(chart_data)
        else:
            print(f"[_render_chart_direct] Cannot render - app or render_analysis_chart not available")
    
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
        print(f"[_get_data_reader] Available sources:")
        for name, proxy in simple.GetSources().items():
            source_name = name[0] if isinstance(name, tuple) else name
            xml_name = proxy.GetXMLName()
            print(f"[_get_data_reader]   '{source_name}' -> {xml_name}")
        
        # First, look for traditional file readers
        for name, proxy in simple.GetSources().items():
            xml_name = proxy.GetXMLName()
            if 'Reader' in xml_name and xml_name not in skip_types:
                print(f"[_get_data_reader] Found reader: {name[0]} ({xml_name})")
                return proxy
        
        # For Live data, look for TrivialProducer sources named "volume" or "surface"
        # Prefer "volume" over "surface"
        for preferred in ['volume', 'surface']:
            for name, proxy in simple.GetSources().items():
                source_name = name[0] if isinstance(name, tuple) else name
                xml_name = proxy.GetXMLName()
                # Check both TrivialProducer and PVTrivialProducer
                if 'TrivialProducer' in xml_name and source_name == preferred:
                    print(f"[_get_data_reader] Found Live source: {source_name}")
                    return proxy
        
        # Fall back to active source
        active = simple.GetActiveSource()
        print(f"[_get_data_reader] Falling back to active source: {active.GetXMLName() if active else None}")
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
            "tip": "Use field names with update_color(proxy_name, field_name) to change visualization coloring."
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
            "tip": f"Threshold {vortex['threshold']:.2f} is auto-computed. To show MORE structures: update_list_property('Isosurfaces', [{vortex['threshold']/2:.2f}], '{contour_name}'). To show FEWER: update_list_property('Isosurfaces', [{vortex['threshold']*2:.2f}], '{contour_name}'). To change style: update_representation('Wireframe', '{contour_name}')."
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
            stream.SeedType.Center = seed["center"]
            stream.SeedType.Radius = seed["radius"]
            stream.SeedType.NumberOfPoints = num_points
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
        print(f"[show_slice] Created {slice_name}, Input={slice_filter.Input}, Input ID={slice_filter.Input.GetGlobalIDAsString() if slice_filter.Input else None}")
        print(f"[show_slice] Parent proxy: {self._get_proxy_name(proxy)}, ID={proxy.GetGlobalIDAsString()}")
        
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
            "tip": f"To refine: update_color('{slice_name}', field_name='pressure') to recolor, or update_representation('Surface With Edges', '{slice_name}') to show mesh."
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
            "tip": "To refine: update_representation('Points', 'VortexCores') to show as points, or update_color('VortexCores', field_name='Velocity') to color by velocity."
        }
        
        return result

    def show_forces(self) -> dict:
        """
        Show force distribution along the body.
        
        Returns:
            Dict with force distribution info
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
        
        result = self._mcp.create_force_distribution_chart(proxy_name=proxy_name)
        
        if "error" in result:
            return result
        
        # Create chart data proxy (vtkTable)
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
                "force_axis": result.get("force_axis"),
                "distribution_axis": result.get("distribution_axis"),
                "total_force": result.get("total_force"),
            }
        )
        
        # Render the chart from proxy
        self._render_chart(chart_proxy_name)
        
        # Return summary with proxy reference (no raw data)
        return {
            "status": "created",
            "chart_proxy": chart_proxy_name,
            "title": result.get("title"),
            "force_axis": result.get("force_axis"),
            "distribution_axis": result.get("distribution_axis"),
            "total_force": round(result.get("total_force", 0), 6),
            "num_bins": result.get("num_bins"),
            "num_body_cells": result.get("num_body_cells"),
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
