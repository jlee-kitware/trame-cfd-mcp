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
        normal: str = "x",
        color_by: str = "Velocity"
    ) -> dict:
        """
        Show a slice through the data.
        
        Args:
            location: "wake" (at wake centroid) or "center" (domain center)
            normal: Slice normal - "x", "y", or "z" (default: "x" for wake slices)
            color_by: Field to color by (default: "Velocity")
            
        Returns:
            Dict with visualization info including proxy_name
        """
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Determine slice origin
        if location == "wake":
            wake = self._mcp.detect_wake_region(proxy_name=proxy_name)
            if "error" in wake:
                # Fallback: use streamline seed location (has better fallback logic)
                seed = self._mcp.compute_streamline_seed(proxy_name=proxy_name)
                if "error" not in seed:
                    origin = seed["center"]
                    location = "downstream (wake detection failed)"
                else:
                    # Last resort: domain center
                    params = self._mcp.compute_slice_params(normal=normal, proxy_name=proxy_name)
                    if "error" in params:
                        return params
                    origin = params["origin"]
                    location = "center (wake detection failed)"
            else:
                origin = wake["wake_centroid"]
        elif location == "center":
            params = self._mcp.compute_slice_params(normal=normal, proxy_name=proxy_name)
            if "error" in params:
                return params
            origin = params["origin"]
        else:
            return {"error": f"Unknown location: {location}. Use 'wake' or 'center'"}
        
        # Normal vector
        normal_map = {"x": [1,0,0], "y": [0,1,0], "z": [0,0,1]}
        normal_vec = normal_map.get(normal.lower(), [1,0,0])
        
        # Create slice
        slice_filter = simple.Slice(Input=proxy)
        slice_filter.SliceType = 'Plane'
        slice_filter.SliceType.Origin = origin
        slice_filter.SliceType.Normal = normal_vec
        simple.UpdatePipeline(proxy=slice_filter)
        
        # Show and color
        display = simple.Show(slice_filter, view)
        color_array = self._mcp._resolve_field_type(color_by, slice_filter)
        if color_array:
            simple.ColorBy(display, ('POINTS', color_array))
            display.RescaleTransferFunctionToDataRange(True, False)
            display.SetScalarBarVisibility(view, True)
        
        # Set view perpendicular to slice
        self._mcp.set_view(direction=f"-{normal}")
        
        # Focus
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
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["Slice"],
                "arrays_used": [color_array or color_by],
                "parameters": {
                    "origin": list(origin),
                    "normal": normal,
                    "location": location,
                    "color_by": color_array or color_by
                }
            },
            "interpretation": {
                "location_type": location,
                "claim": f"Slice shows {color_array or color_by} distribution on a plane. Wake slices reveal base pressure deficit."
            },
            "tip": f"Slice at {normal}-normal through {location}. Use location='center' for domain center."
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

    def show_boundary_layer(self, x_location: float = 0.5, probe_length: float = 0.3) -> dict:
        """
        Show boundary layer velocity profile at a given x-location.
        
        Creates a line probe normal to the body surface and plots velocity vs distance from wall.
        
        Args:
            x_location: X-coordinate where to probe (default: 0.5)
            probe_length: How far to probe into the flow (default: 0.3)
            
        Returns:
            Dict with boundary layer profile data
        """
        import numpy as np
        from vtk.util.numpy_support import vtk_to_numpy
        
        view = simple.GetActiveView()
        proxy = self._get_data_reader()
        if proxy is None:
            return {"error": "No data reader found"}
        
        proxy_name = self._get_proxy_name(proxy)
        
        # Hide all first
        self._mcp.hide_all()
        
        # Merge blocks
        merge = simple.MergeBlocks(Input=proxy)
        simple.UpdatePipeline(proxy=merge)
        
        # Get domain center for normal orientation
        di = merge.GetDataInformation()
        bounds = di.GetBounds()
        domain_center = np.array([(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2])
        
        # Extract surface and compute normals
        surface = simple.ExtractSurface(Input=merge)
        simple.UpdatePipeline(proxy=surface)
        
        normals = simple.SurfaceNormals(Input=surface)
        simple.UpdatePipeline(proxy=normals)
        
        data = normals.GetClientSideObject().GetOutput()
        points = vtk_to_numpy(data.GetPoints().GetData())
        normal_arr = vtk_to_numpy(data.GetPointData().GetArray('Normals'))
        
        # Find surface point near x_location on centerline (z~0)
        mask = (np.abs(points[:,0] - x_location) < 0.1) & (np.abs(points[:,2]) < 0.2) & (points[:,1] > 0.01) & (points[:,1] < 1.0)
        candidates = np.where(mask)[0]
        
        if len(candidates) == 0:
            # Try wider search
            mask = np.abs(points[:,0] - x_location) < 0.3
            candidates = np.where(mask)[0]
        
        if len(candidates) == 0:
            simple.Delete(normals)
            simple.Delete(surface)
            simple.Delete(merge)
            return {"error": f"No surface point found near x={x_location}"}
        
        # Pick point with smallest y (closest to body surface, but above symmetry plane)
        y_vals = points[candidates, 1]
        best_idx = candidates[np.argmin(y_vals)]
        
        surface_point = points[best_idx]
        surface_normal = normal_arr[best_idx]
        
        # Flip normal if pointing away from domain center (we want it pointing into fluid)
        to_center = domain_center - surface_point
        if np.dot(surface_normal, to_center) < 0:
            surface_normal = -surface_normal
        
        # Create line probe
        end_point = surface_point + probe_length * surface_normal
        
        line = simple.PlotOverLine(Input=merge)
        line.Point1 = surface_point.tolist()
        line.Point2 = end_point.tolist()
        line.Resolution = 50
        simple.UpdatePipeline(proxy=line)
        
        # Extract profile data
        line_data = line.GetClientSideObject().GetOutput()
        if line_data.GetNumberOfPoints() == 0:
            simple.Delete(line)
            simple.Delete(normals)
            simple.Delete(surface)
            simple.Delete(merge)
            return {"error": "Line probe returned no points"}
        
        arc_length = vtk_to_numpy(line_data.GetPointData().GetArray('arc_length'))
        velocity = vtk_to_numpy(line_data.GetPointData().GetArray('Velocity'))
        u_mag = np.linalg.norm(velocity, axis=1)
        
        # Filter NaN
        valid = ~np.isnan(u_mag)
        arc_length = arc_length[valid]
        u_mag = u_mag[valid]
        
        if len(arc_length) == 0:
            simple.Delete(line)
            simple.Delete(normals)
            simple.Delete(surface)
            simple.Delete(merge)
            return {"error": "No valid velocity data in probe"}
        
        # Compute boundary layer properties
        u_inf = u_mag[-1] if len(u_mag) > 1 else u_mag[0]
        u_normalized = u_mag / u_inf if u_inf > 0 else u_mag
        
        # Find delta (BL thickness) - where u/U_inf reaches 0.99
        delta_idx = np.where(u_normalized >= 0.99)[0]
        delta = arc_length[delta_idx[0]] if len(delta_idx) > 0 else arc_length[-1]
        
        # Integrate only within the boundary layer (up to delta) for proper BL integrals
        bl_mask = arc_length <= delta
        y_bl = arc_length[bl_mask]
        u_bl = u_normalized[bl_mask]
        
        # Compute displacement thickness: δ* = ∫(1 - u/U∞) dy
        delta_star = np.trapz(1 - u_bl, y_bl) if len(y_bl) > 1 else 0.0
        
        # Compute momentum thickness: θ = ∫(u/U∞)(1 - u/U∞) dy
        theta = np.trapz(u_bl * (1 - u_bl), y_bl) if len(y_bl) > 1 else 0.0
        
        # Shape factor H = δ*/θ (H ≈ 2.6 laminar, H ≈ 1.3-1.4 turbulent)
        shape_factor = delta_star / theta if theta > 1e-10 else float('nan')
        
        # Create XY chart
        import tempfile
        import os
        
        csv_path = os.path.join(tempfile.gettempdir(), 'boundary_layer.csv')
        with open(csv_path, 'w') as f:
            f.write('Distance,Velocity,u_over_Uinf\n')
            for i in range(len(arc_length)):
                f.write(f'{arc_length[i]:.6f},{u_mag[i]:.6f},{u_normalized[i]:.6f}\n')
        
        original_view = simple.GetActiveView()
        
        table = simple.CSVReader(FileName=[csv_path])
        simple.UpdatePipeline(proxy=table)
        
        chart_view = simple.CreateXYPlotView()
        chart_view.ViewSize = [800, 400]
        chart_view.ChartTitle = f'Boundary Layer Profile at x={x_location:.2f}'
        chart_view.BottomAxisTitle = 'Distance from wall'
        chart_view.LeftAxisTitle = 'u / U∞'
        
        display = simple.Show(table, chart_view)
        display.XArrayName = 'Distance'
        display.UseIndexForXAxis = 0
        display.SeriesVisibility = ['u_over_Uinf']
        display.SeriesColor = ['u_over_Uinf', '0', '0', '0.8']
        display.SeriesLineThickness = ['u_over_Uinf', '2']
        
        simple.Render(chart_view)
        self._mcp._chart_view_queue.append(chart_view)
        
        # Restore view
        if original_view:
            simple.SetActiveView(original_view)
        
        # Cleanup temporary filters
        simple.Delete(normals)
        simple.Delete(surface)
        
        result = {
            "status": "created",
            "type": "boundary_layer_profile",
            "x_location": x_location,
            "surface_point": surface_point.tolist(),
            "surface_normal": surface_normal.tolist(),
            "num_points": len(arc_length),
            "u_infinity": float(u_inf),
            "delta": float(delta),
            "delta_star": float(delta_star),
            "theta": float(theta),
            "shape_factor": float(shape_factor),
            "provenance": {
                "dataset": self._get_dataset_filename(proxy),
                "filter_chain": ["MergeBlocks", "ExtractSurface", "SurfaceNormals", "PlotOverLine"],
                "arrays_used": ["Velocity", "Normals"],
                "parameters": {
                    "x_location": x_location,
                    "probe_length": probe_length
                }
            },
            "interpretation": {
                "delta": float(delta),
                "delta_star": float(delta_star),
                "theta": float(theta),
                "shape_factor": float(shape_factor),
                "u_infinity": float(u_inf),
                "claim": f"Boundary layer at x={x_location:.2f}: δ={delta:.4f}, δ*={delta_star:.4f}, θ={theta:.4f}, H={shape_factor:.2f}. " +
                         ("H ≈ 1.3-1.4 suggests turbulent BL." if 1.2 < shape_factor < 1.6 else
                          "H ≈ 2.6 suggests laminar BL." if 2.4 < shape_factor < 2.8 else
                          "Shape factor indicates transitional or separated flow.")
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
