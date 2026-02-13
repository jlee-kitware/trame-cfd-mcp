"""
High-level CFD workflow tools.

These wrap the fine-grained tools into complete workflows.
The LLM just does intent matching - workflows execute deterministically.
Full provenance tracking enables reproducibility and explanation.
"""

from paraview import simple


class CFDWorkflows:
    """High-level workflow tools for CFD visualization."""
    
    def __init__(self, cfd_analysis):
        """
        Initialize with reference to CFDAnalysis for internal tool access.
        
        Args:
            cfd_analysis: CFDAnalysis instance
        """
        self._mcp = cfd_analysis  # Keep as _mcp for minimal code changes
        self._provenance_registry = {}  # proxy_name -> provenance dict
    
    def _register_provenance(self, proxy_name: str, provenance: dict):
        """Register provenance for a proxy to enable chaining."""
        if proxy_name and provenance:
            self._provenance_registry[proxy_name] = provenance
    
    def _get_input_provenance(self, proxy_name: str) -> dict:
        """Get provenance for an input proxy if it was created by a workflow."""
        return self._provenance_registry.get(proxy_name)
    
    def _get_data_reader(self):
        """Get the original data reader (not CSV/temporary readers)."""
        # Skip temporary readers like CSVReader created by charts
        skip_types = ['CSVReader', 'DelimitedTextReader']
        
        for name, proxy in simple.GetSources().items():
            xml_name = proxy.GetXMLName()
            if 'Reader' in xml_name and xml_name not in skip_types:
                return proxy
        return simple.GetActiveSource()
    
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
        
        # Create contour on the vortex field proxy
        vortex_proxy = simple.FindSource(vortex["proxy_name"])
        contour = simple.Contour(Input=vortex_proxy)
        contour.ContourBy = ['POINTS', vortex["field_name"]]
        contour.Isosurfaces = [vortex["threshold"]]
        simple.UpdatePipeline(proxy=contour)
        
        contour_name = self._get_proxy_name(contour)
        
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
        num_points: int = 100
    ) -> dict:
        """
        Show streamlines in the wake region.
        
        Args:
            color_by: Field to color by (default: "Velocity")
            num_points: Number of seed points (default: 100)
            
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
        
        # Compute seed parameters (logs analysis decisions)
        seed = self._mcp.compute_streamline_seed(proxy_name=proxy_name)
        if "error" in seed:
            return seed
        
        # Create StreamTracer
        stream = simple.StreamTracer(Input=proxy)
        stream.SeedType = "Point Cloud"
        stream.SeedType.Center = seed["center"]
        stream.SeedType.Radius = seed["radius"]
        stream.SeedType.NumberOfPoints = num_points
        stream.MaximumStreamlineLength = seed["max_length"]
        stream.Vectors = ['POINTS', 'Velocity']
        simple.UpdatePipeline(proxy=stream)
        
        stream_name = self._get_proxy_name(stream)
        
        # Show and color
        display = simple.Show(stream, view)
        color_array = self._mcp._resolve_field_type(color_by, stream)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)
        
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Build provenance
        provenance = {
            "dataset": self._get_dataset_filename(proxy),
            "filter_chain": self._mcp.extract_filter_chain(stream),
            "analysis": self._mcp.get_analysis_log(),
            "display": {
                "color_by": color_array or color_by,
                "representation": "Surface"
            }
        }
        
        self._register_provenance(stream_name, provenance)
        
        return {
            "status": "created",
            "type": "streamlines",
            "proxy_name": stream_name,
            "provenance": provenance,
            "tip": f"To refine: update_color('{stream_name}', field_name='pressure') to recolor, or update_representation('Wireframe', '{stream_name}') to change style."
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
        
        # Create slice
        slice_filter = simple.Slice(Input=proxy)
        slice_filter.SliceType = 'Plane'
        slice_filter.SliceType.Origin = origin
        slice_filter.SliceType.Normal = normal_vec
        simple.UpdatePipeline(proxy=slice_filter)
        
        slice_name = self._get_proxy_name(slice_filter)
        
        # Show with representation
        display = simple.Show(slice_filter, view)
        
        if representation == "Surface LIC" and "Surface LIC" in display.Representation.Available:
            display.Representation = "Surface LIC"
            display.SelectInputVectors = ['POINTS', 'Velocity']
            color_array = "Velocity (LIC)"
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
        
        # Add provenance
        if "error" not in result:
            result["provenance"] = {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["Histogram"],
                "arrays_used": [result.get("field", field)],
                "parameters": {
                    "field": result.get("field", field),
                    "num_bins": num_bins
                }
            }
            result["tip"] = "Chart created. Use save_screenshot() for single chart or save_all_charts() for multiple."
        
        return result

    def show_boundary_layer(self, x_over_chord: float = 0.5, span_fraction: float = 0.5, 
                            probe_length: float = None) -> dict:
        """
        Show boundary layer velocity profile at a given chordwise and spanwise location.
        
        Creates a line probe normal to the body surface and plots velocity vs distance from wall.
        Uses surface-normal probing with multiple edge detection criteria following
        Antares/CERFACS methodology.
        
        Args:
            x_over_chord: Chordwise location as fraction of chord (0=LE, 1=TE, default: 0.5)
            span_fraction: Spanwise location as fraction of span (0=root, 1=tip, default: 0.5 for mid-span)
            probe_length: How far to probe into the flow (default: 30% of chord)
            
        Returns:
            Dict with boundary layer profile data including delta, delta*, theta, H
        """
        import numpy as np
        import tempfile
        import os
        
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
        delta = bl_data["delta"]
        u_edge_idx = bl_data["u_edge_idx"]
        
        # Truncate plot at 3x delta or edge velocity location
        plot_limit = min(3 * delta, y[u_edge_idx]) if delta > 0 else y[u_edge_idx]
        plot_mask = y <= plot_limit
        
        # Write CSV for BL profile chart
        csv_path = os.path.join(tempfile.gettempdir(), 'boundary_layer.csv')
        with open(csv_path, 'w') as f:
            f.write('y,u,u_over_Ue\n')
            for i in np.where(plot_mask)[0]:
                f.write(f'{y[i]:.6f},{u[i]:.6f},{u_normalized[i]:.6f}\n')
        
        original_view = simple.GetActiveView()
        
        # Get geometry info for labels
        geom = bl_data["geometry"]
        span_axis = geom["span_axis"]
        x_over_chord = bl_data["x_over_chord"]
        span_absolute = bl_data["span_absolute"]
        span_frac = bl_data["span_fraction"]
        
        # ===== BL profile chart =====
        table = simple.CSVReader(FileName=[csv_path])
        simple.UpdatePipeline(proxy=table)
        
        chart_view = simple.CreateXYPlotView()
        chart_view.ViewSize = [600, 500]
        chart_view.ChartTitle = f'Boundary Layer at x/c={x_over_chord:.2f}, {span_axis}={span_absolute:.3f} ({span_frac*100:.0f}% span)'
        chart_view.BottomAxisTitle = 'u / Ue'
        chart_view.LeftAxisTitle = 'y (distance from wall)'
        chart_view.ShowLegend = 0
        
        display = simple.Show(table, chart_view)
        display.XArrayName = 'u_over_Ue'
        display.UseIndexForXAxis = 0
        display.SeriesVisibility = ['y']
        display.SeriesColor = ['y', '0', '0', '0.8']
        display.SeriesLineThickness = ['y', '2']
        
        simple.Render(chart_view)
        self._mcp._chart_view_queue.append(chart_view)
        
        if original_view:
            simple.SetActiveView(original_view)
        
        # Build result with provenance
        # Build result - keep lightweight for LLM, store full data internally
        # Full data stored in _last_bl_results for debug chart and context visualization
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
        
        result = {
            "status": "created",
            "type": "boundary_layer_profile",
            "surface": bl_data["surface"],
            "x_over_chord": bl_data["x_over_chord"],
            "span_fraction": bl_data["span_fraction"],
            "section_chord": bl_data["section"]["chord"],
            "num_points": len(y),
            "u_edge": bl_data["u_edge"],
            "delta": bl_data["delta"],
            "delta_star": bl_data["delta_star"],
            "theta": bl_data["theta"],
            "shape_factor": bl_data["shape_factor"],
            "provenance": {
                "filter_chain": ["MergeBlocks", "ExtractSurface", "Clip", "Slice", "ResampleWithDataset"],
                "arrays_used": ["Velocity"],
            },
            "tip": "BL profile chart created. After all BL calls: save_all_charts() for charts, show_boundary_layer_context() for 3D visualization."
        }
        
        return result

    def create_section_debug_chart(self, bl_results: list = None, title: str = None) -> dict:
        """
        Create a debug chart showing airfoil section with probe locations.
        
        Args:
            bl_results: List of boundary layer result dicts (optional - uses internal cache if None)
            title: Optional chart title
            
        Returns:
            Dict with chart info
        """
        import tempfile
        import os
        
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
        
        # Write section contour CSV
        suction = section_data['suction_contour']
        pressure = section_data['pressure_contour']
        
        section_csv = os.path.join(tempfile.gettempdir(), 'debug_section.csv')
        with open(section_csv, 'w') as f:
            f.write('x_over_c,z_over_c\n')
            for pt in suction:
                xc = (pt[0] - le_x) / chord
                zc = pt[1] / chord
                f.write(f'{xc:.6f},{zc:.6f}\n')
            for pt in pressure:
                xc = (pt[0] - le_x) / chord
                zc = pt[1] / chord
                f.write(f'{xc:.6f},{zc:.6f}\n')
        
        # Write probe lines and sample points
        probe_lines = []
        surface_markers = []
        all_sample_points = []  # All sample points along all probes
        
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
            
            probe_lines.append({'xc': xc, 'zc': zc, 'xc_end': xc_end, 'zc_end': zc_end})
            surface_markers.append({'xc': xc, 'zc': zc})
            
            # Compute sample point positions along the probe
            if 'y' in r:
                y_vals = r['y']  # arc_length values
                for y_dist in y_vals:
                    sample_x = pt[stream_idx] + y_dist * norm[stream_idx]
                    sample_z = pt[vert_idx] + y_dist * norm[vert_idx]
                    sample_xc = (sample_x - le_x) / chord
                    sample_zc = sample_z / chord
                    all_sample_points.append({'xc': sample_xc, 'zc': sample_zc})
        
        # Write probe lines (each as separate file for different colors)
        for i, p in enumerate(probe_lines):
            probe_file = os.path.join(tempfile.gettempdir(), f'probe_line_{i}.csv')
            with open(probe_file, 'w') as f:
                f.write('x_over_c,z_over_c\n')
                f.write(f'{p["xc"]:.6f},{p["zc"]:.6f}\n')
                f.write(f'{p["xc_end"]:.6f},{p["zc_end"]:.6f}\n')
        
        # Write surface markers
        markers_csv = os.path.join(tempfile.gettempdir(), 'probe_markers.csv')
        with open(markers_csv, 'w') as f:
            f.write('x_over_c,z_over_c\n')
            for m in surface_markers:
                f.write(f'{m["xc"]:.6f},{m["zc"]:.6f}\n')
        
        # Write all sample points
        samples_csv = os.path.join(tempfile.gettempdir(), 'sample_points.csv')
        with open(samples_csv, 'w') as f:
            f.write('x_over_c,z_over_c\n')
            for sp in all_sample_points:
                f.write(f'{sp["xc"]:.6f},{sp["zc"]:.6f}\n')
        
        # Create chart
        section_table = simple.CSVReader(FileName=[section_csv])
        simple.UpdatePipeline(proxy=section_table)
        
        markers_table = simple.CSVReader(FileName=[markers_csv])
        simple.UpdatePipeline(proxy=markers_table)
        
        chart = simple.CreateXYPlotView()
        chart.ViewSize = [800, 500]
        chart.ChartTitle = title or 'Airfoil Section with Probe Locations'
        chart.BottomAxisTitle = 'x/c'
        chart.LeftAxisTitle = 'z/c'
        chart.ShowLegend = 0
        
        # Section contour (black)
        section_display = simple.Show(section_table, chart)
        section_display.XArrayName = 'x_over_c'
        section_display.UseIndexForXAxis = 0
        section_display.SeriesVisibility = ['z_over_c']
        section_display.SeriesColor = ['z_over_c', '0', '0', '0']
        section_display.SeriesLineThickness = ['z_over_c', '2']
        
        # Probe lines (colored)
        colors = ['0.8,0,0', '0,0.6,0', '0,0,0.8', '0.8,0.4,0', '0.5,0,0.8', '0,0.6,0.6', '0.6,0,0.6']
        for i in range(len(probe_lines)):
            probe_file = os.path.join(tempfile.gettempdir(), f'probe_line_{i}.csv')
            probe_table = simple.CSVReader(FileName=[probe_file])
            simple.UpdatePipeline(proxy=probe_table)
            
            probe_display = simple.Show(probe_table, chart)
            probe_display.XArrayName = 'x_over_c'
            probe_display.UseIndexForXAxis = 0
            probe_display.SeriesVisibility = ['z_over_c']
            c = colors[i % len(colors)].split(',')
            probe_display.SeriesColor = ['z_over_c', c[0], c[1], c[2]]
            probe_display.SeriesLineThickness = ['z_over_c', '2']
        
        # Surface markers (red circles)
        markers_display = simple.Show(markers_table, chart)
        markers_display.XArrayName = 'x_over_c'
        markers_display.UseIndexForXAxis = 0
        markers_display.SeriesVisibility = ['z_over_c']
        markers_display.SeriesColor = ['z_over_c', '1', '0', '0']
        markers_display.SeriesLineStyle = ['z_over_c', '0']  # No line
        markers_display.SeriesMarkerStyle = ['z_over_c', '4']  # Filled circle
        markers_display.SeriesMarkerSize = ['z_over_c', '12']
        
        # Sample points along probes (small blue dots)
        if all_sample_points:
            samples_table = simple.CSVReader(FileName=[samples_csv])
            simple.UpdatePipeline(proxy=samples_table)
            
            samples_display = simple.Show(samples_table, chart)
            samples_display.XArrayName = 'x_over_c'
            samples_display.UseIndexForXAxis = 0
            samples_display.SeriesVisibility = ['z_over_c']
            samples_display.SeriesColor = ['z_over_c', '0', '0', '0.8']
            samples_display.SeriesLineStyle = ['z_over_c', '0']  # No line
            samples_display.SeriesMarkerStyle = ['z_over_c', '4']  # Filled circle
            samples_display.SeriesMarkerSize = ['z_over_c', '3']
        
        simple.Render(chart)
        self._mcp._chart_view_queue.append(chart)
        
        return {
            "status": "created",
            "type": "section_debug_chart",
            "num_probes": len(probe_lines),
            "num_sample_points": len(all_sample_points),
            "section_chord": chord
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
        
        # Create velocity slice at span station
        merge = simple.MergeBlocks(Input=proxy)
        simple.UpdatePipeline(proxy=merge)
        
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
        clip_display = simple.Show(clip, view)
        simple.ColorBy(clip_display, ('POINTS', 'Velocity', 'Magnitude'))
        
        vel_lut = simple.GetColorTransferFunction('Velocity')
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
        
        # Add provenance
        if "error" not in result:
            result["provenance"] = {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["ExtractSurface", "Calculator", "PlotOverLine"],
                "arrays_used": ["p", "Normals"],
                "parameters": {}
            }
            result["tip"] = "Chart created. Use save_screenshot() for single chart or save_all_charts() for multiple."
        
        return result

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
