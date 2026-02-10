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
