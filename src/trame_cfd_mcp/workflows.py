# -*- coding: utf-8 -*-
"""
High-level CFD workflow tools.

These wrap the fine-grained tools into complete workflows.
The LLM just does intent matching - workflows execute deterministically.
"""

from paraview import simple


class CFDWorkflows:
    """High-level workflow tools for CFD visualization."""
    
    def __init__(self, extended_mcp):
        """
        Initialize with reference to ExtendedParaViewMCP for internal tool access.
        
        Args:
            extended_mcp: ExtendedParaViewMCP instance
        """
        self._mcp = extended_mcp
    
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
            "cell_fields": cell_fields
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
            Dict with visualization info including proxy_name
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Compute vortex field
        vortex = self._mcp.compute_vortex_field(method=method, proxy_name=proxy_name)
        if "error" in vortex:
            return vortex
        
        # Create contour on the vortex field proxy
        vortex_proxy = simple.FindSource(vortex["proxy_name"])
        contour = simple.Contour(Input=vortex_proxy)
        
        # Set ContourBy to the vortex field (CRITICAL!)
        contour.ContourBy = ['POINTS', vortex["field_name"]]
        
        # Set isosurface value
        contour.Isosurfaces = [vortex["threshold"]]
        simple.UpdatePipeline(proxy=contour)
        
        # Show and color
        display = simple.Show(contour, view)
        color_array = self._mcp._resolve_field_type(color_by, contour)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)
        
        # Focus on result
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Get contour name
        contour_name = None
        for name, p in simple.GetSources().items():
            if p == contour:
                contour_name = name[0]
                break
        
        return {
            "status": "created",
            "type": "vortex_isosurface", 
            "method": method,
            "proxy_name": contour_name,
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["MergeBlocks", "Gradient", "Contour"],
                "arrays_used": ["Velocity", vortex["field_name"]],
                "parameters": {
                    "method": method,
                    "threshold": vortex["threshold"],
                    "ContourBy": vortex["field_name"],
                    "color_by": color_array or color_by
                }
            },
            "interpretation": {
                "field": vortex["field_name"],
                "threshold": vortex["threshold"],
                "field_range": vortex.get("field_range"),
                "claim": f"{method.replace('_', ' ').title()} > 0 indicates vortex cores where rotation dominates strain"
            },
            "tip": f"Threshold {vortex['threshold']:.2f} is auto-computed. Adjust for more/fewer structures."
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
            Dict with visualization info including proxy_name
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Compute seed parameters
        seed = self._mcp.compute_streamline_seed(proxy_name=proxy_name)
        if "error" in seed:
            return seed
        
        # Create StreamTracer
        stream = simple.StreamTracer(Input=proxy)
        
        # Configure all parameters
        stream.SeedType = "Point Cloud"
        stream.SeedType.Center = seed["center"]
        stream.SeedType.Radius = seed["radius"]
        stream.SeedType.NumberOfPoints = num_points
        stream.MaximumStreamlineLength = seed["max_length"]
        stream.Vectors = ['POINTS', 'Velocity']
        simple.UpdatePipeline(proxy=stream)
        
        # Show and color
        display = simple.Show(stream, view)
        color_array = self._mcp._resolve_field_type(color_by, stream)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)
        
        # Focus
        simple.ResetCamera(view)
        simple.Render(view)
        
        # Get name
        stream_name = None
        for name, p in simple.GetSources().items():
            if p == stream:
                stream_name = name[0]
                break
        
        return {
            "status": "created",
            "type": "streamlines",
            "proxy_name": stream_name,
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["StreamTracer"],
                "arrays_used": ["Velocity"],
                "parameters": {
                    "seed_center": seed["center"],
                    "seed_radius": seed["radius"],
                    "num_points": num_points,
                    "max_length": seed["max_length"],
                    "color_by": color_array or color_by
                }
            },
            "interpretation": {
                "seed_location": seed.get("source", "wake"),
                "claim": "Streamlines show flow path lines. In wake region, they reveal recirculation and separation."
            },
            "tip": "Seed placed in wake region. Adjust num_points for density."
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
            Dict with visualization info including proxy_name
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Determine slice parameters based on location
        if location in ("span", "spanwise"):
            # Use spanwise slice params from extended_mcp
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
            # Get span info for metadata
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
        
        # Focus on slice (zoom to body region for span slices)
        if location.startswith("span") and body_bounds:
            view.ResetCamera(body_bounds[0], body_bounds[1], 
                           body_bounds[2], body_bounds[3], 
                           body_bounds[4], body_bounds[5], False, 0.9)
        else:
            bounds = slice_filter.GetDataInformation().GetBounds()
            view.ResetCamera(*bounds, False, 0.9)
        simple.Render(view)
        
        # Get name
        slice_name = None
        for name, p in simple.GetSources().items():
            if p == slice_filter:
                slice_name = name[0]
                break
        
        return {
            "status": "created",
            "type": "slice",
            "proxy_name": slice_name,
            "span_axis": span_axis,
            "streamwise_axis": streamwise_axis,
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["Slice"],
                "arrays_used": [color_array or color_by],
                "parameters": {
                    "origin": list(origin),
                    "normal": slice_normal,
                    "location": location,
                    "offset": offset,
                    "color_by": color_by,
                    "representation": representation
                }
            },
            "interpretation": {
                "location_type": location,
                "claim": f"Slice shows {color_array or color_by} distribution. " +
                         ("Spanwise slice shows airfoil section flow pattern." if location.startswith("span") else
                          "Wake slice reveals velocity deficit and pressure recovery.")
            }
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
        
        # Add provenance and interpretation
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
            result["interpretation"] = {
                "claim": f"Histogram shows distribution of {result.get('field', field)}. Asymmetric distributions may indicate flow features."
            }
        
        return result

    def show_boundary_layer(self, x_location: float = 0.5, probe_length: float = None) -> dict:
        """
        Show boundary layer velocity profile at a given x-location.
        
        Creates a line probe normal to the body surface and plots velocity vs distance from wall.
        Uses surface-normal probing with multiple edge detection criteria following
        Antares/CERFACS methodology.
        
        Args:
            x_location: Streamwise location - either absolute coordinate or fraction (0-1) of chord
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
        
        # Compute boundary layer profile using extended_mcp
        bl_data = self._mcp.compute_boundary_layer_profile(
            proxy=proxy, 
            x_location=x_location, 
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
        
        # Write CSV for chart
        csv_path = os.path.join(tempfile.gettempdir(), 'boundary_layer.csv')
        with open(csv_path, 'w') as f:
            f.write('y,u,u_over_Ue\n')
            for i in np.where(plot_mask)[0]:
                f.write(f'{y[i]:.6f},{u[i]:.6f},{u_normalized[i]:.6f}\n')
        
        original_view = simple.GetActiveView()
        
        table = simple.CSVReader(FileName=[csv_path])
        simple.UpdatePipeline(proxy=table)
        
        # Chart title with location info
        geom = bl_data["geometry"]
        span_axis = geom["span_axis"]
        x_over_chord = bl_data["x_over_chord"]
        span_location = bl_data["span_location"]
        span_fraction = bl_data["span_fraction"]
        
        chart_view = simple.CreateXYPlotView()
        chart_view.ViewSize = [600, 500]
        chart_view.ChartTitle = f'Boundary Layer Profile at x/c={x_over_chord:.2f}, {span_axis}={span_location:.3f} ({span_fraction*100:.0f}% span)'
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
        result = {
            "status": "created",
            "type": "boundary_layer_profile",
            "x_location": bl_data["x_location"],
            "x_absolute": bl_data["x_absolute"],
            "x_over_chord": bl_data["x_over_chord"],
            "span_location": bl_data["span_location"],
            "span_fraction": bl_data["span_fraction"],
            "surface_point": bl_data["surface_point"],
            "surface_normal": bl_data["surface_normal"],
            "num_points": len(y),
            "u_edge": bl_data["u_edge"],
            "delta": bl_data["delta"],
            "delta_99": bl_data["delta_99"],
            "delta_haase": bl_data["delta_haase"],
            "edge_method": bl_data["edge_method"],
            "delta_star": bl_data["delta_star"],
            "theta": bl_data["theta"],
            "shape_factor": bl_data["shape_factor"],
            "geometry": bl_data["geometry"],
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["MergeBlocks", "ExtractSurface", "SurfaceNormals", "PlotOverLine"],
                "arrays_used": ["Velocity", "Normals"],
                "parameters": {
                    "x_location": x_location,
                    "x_absolute": bl_data["x_absolute"],
                    "probe_length": bl_data["probe_length"]
                }
            },
            "interpretation": {
                "delta": bl_data["delta"],
                "delta_star": bl_data["delta_star"],
                "theta": bl_data["theta"],
                "shape_factor": bl_data["shape_factor"],
                "u_edge": bl_data["u_edge"],
                "claim": f"Boundary layer at x/c={x_over_chord:.2f}: δ={bl_data['delta']:.4f}, δ*={bl_data['delta_star']:.4f}, θ={bl_data['theta']:.4f}, H={bl_data['shape_factor']:.2f}. " +
                         ("H ≈ 1.3-1.4 suggests turbulent BL." if 1.2 < bl_data['shape_factor'] < 1.6 else
                          "H ≈ 2.6 suggests laminar BL." if 2.4 < bl_data['shape_factor'] < 2.8 else
                          "Shape factor indicates transitional or separated flow.")
            }
        }
        
        return result

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
            "vortex_cores": n_cores,
            "vortex_points": n_points,
            "bounds": bounds,
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["MergeBlocks", "VortexCores"],
                "arrays_used": ["Velocity"],
                "parameters": {}
            },
            "interpretation": {
                "vortex_cores": n_cores,
                "claim": f"Found {n_cores} vortex core line segments with {n_points} points. " +
                         (f"Cores extend from x=[{bounds['x'][0]:.2f}, {bounds['x'][1]:.2f}]. " if bounds else "") +
                         "Vortex cores indicate regions of concentrated rotation in the flow."
            }
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
        
        # Add provenance and interpretation
        if "error" not in result:
            result["provenance"] = {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["ExtractSurface", "Calculator", "PlotOverLine"],
                "arrays_used": ["p", "Normals"],
                "parameters": {}
            }
            result["interpretation"] = {
                "claim": "Force distribution shows where drag/lift accumulates along the body. Peaks indicate high-drag regions."
            }
        
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
        
        return self._mcp.characterize_dataset(proxy_name=proxy_name)
