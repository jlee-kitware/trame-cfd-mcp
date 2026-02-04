"""
Extended ParaViewMCP

Extends trame-llm's ParaViewMCP with query and analysis tools.
These additions could be contributed upstream to trame-llm.
"""

from paraview import simple
import numpy as np
import json
from pathlib import Path


# Semantic field type patterns for field resolution
FIELD_TYPE_PATTERNS = {
    "velocity": ["velocity", "vel", "u", "v", "w", "U"],
    "pressure": ["pressure", "p", "P", "press"],
    "density": ["density", "rho", "Density"],
    "temperature": ["temperature", "temp", "T", "Temperature"],
    "mach": ["mach", "Mach", "Ma"],
    "turbulent_kinetic_energy": ["tke", "k", "TurbulentKineticEnergy", "TKE"],
}


class ExtendedParaViewMCP:
    """
    Wraps ParaViewMCP and adds analysis/query tools.
    
    Usage:
        from trame_llm.paraview import ParaViewMCP
        from paraview_llm.extended_mcp import ExtendedParaViewMCP
        
        base_mcp = ParaViewMCP(app)
        extended = ExtendedParaViewMCP(base_mcp)
        
        llm_client.register_mcp(extended)
    """
    
    def __init__(self, paraview_mcp):
        self._base = paraview_mcp
        self.base_mcp = paraview_mcp  # Also expose as base_mcp for convenience
    
    def _resolve_field_type(self, field_type: str, proxy) -> str:
        """
        Resolve a semantic field type to actual field name in the data.
        
        Args:
            field_type: Semantic type like "velocity", "pressure", or actual field name
            proxy: ParaView proxy to search for fields
            
        Returns:
            Actual field name found in proxy, or field_type if not a semantic type
        """
        # If it's not a known semantic type, assume it's already a field name
        if field_type not in FIELD_TYPE_PATTERNS:
            return field_type
        
        patterns = FIELD_TYPE_PATTERNS[field_type]
        
        # Get available fields from proxy
        data = proxy.GetClientSideObject().GetOutput()
        
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            block = data.GetBlock(0)
            while block and block.IsA("vtkMultiBlockDataSet"):
                block = block.GetBlock(0)
            if block:
                data = block
        
        # Collect all field names
        all_fields = []
        for data_arrays in [data.GetPointData(), data.GetCellData()]:
            for i in range(data_arrays.GetNumberOfArrays()):
                all_fields.append(data_arrays.GetArrayName(i))
        
        # First pass: exact match (case-insensitive)
        for name in all_fields:
            name_lower = name.lower()
            for pattern in patterns:
                if pattern.lower() == name_lower:
                    return name
        
        # Second pass: pattern is a substring, but only for longer patterns (avoid "u" matching "Turbulence")
        for name in all_fields:
            name_lower = name.lower()
            for pattern in patterns:
                # Only use substring matching for patterns >= 3 chars
                if len(pattern) >= 3 and pattern.lower() in name_lower:
                    return name
        
        # Fallback: return first pattern as best guess
        return patterns[0]
    
    def _get_available_fields(self, proxy) -> dict:
        """
        Get available fields and their types from proxy.
        
        Returns:
            Dict mapping semantic type to actual field name, plus all field names
        """
        data = proxy.GetClientSideObject().GetOutput()
        
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            block = data.GetBlock(0)
            while block and block.IsA("vtkMultiBlockDataSet"):
                block = block.GetBlock(0)
            if block:
                data = block
        
        result = {"all_fields": [], "resolved": {}}
        
        for data_arrays in [data.GetPointData(), data.GetCellData()]:
            for i in range(data_arrays.GetNumberOfArrays()):
                name = data_arrays.GetArrayName(i)
                result["all_fields"].append(name)
                
                # Try to match to semantic type
                name_lower = name.lower()
                for field_type, patterns in FIELD_TYPE_PATTERNS.items():
                    for pattern in patterns:
                        if pattern.lower() == name_lower or pattern.lower() in name_lower:
                            result["resolved"][field_type] = name
                            break
        
        return result
    
    @property
    def mcp(self):
        """Return combined MCP definition with base + extended tools."""
        base_mcp = self._base.mcp
        
        # Add our tools to the base tools
        extended_tools = [
            self.query_select,
            self.find_by_query,
            self.find_minimum,
            self.find_maximum,
            self.find_high_gradient,
            self.field_statistics,
            self.field_histogram,
            self.compute_forces,
            self.create_histogram_chart,
            self.create_force_distribution_chart,
            self.get_selection_info,
            self.create_streamlines,
            self.create_vortex_isosurface,
            self.create_slice,
            self.set_view,
            self.detect_streamwise_direction,
            self.set_streamwise_view,
            self.hide_all,
            self.show_data_context,
        ]
        
        return {
            "name": base_mcp["name"],
            "instructions": base_mcp["instructions"] + """
                
                Additional CFD tools (always specify proxy_name for explicit input):
                
                ANALYSIS (return data, no visualization):
                - find_minimum: Find location of minimum field value (stagnation points)
                - find_maximum: Find location of maximum field value (freestream)
                - find_high_gradient: Find max gradient location (shear layers, wakes)
                - find_by_query: Find centroid of points matching a query expression
                - field_statistics: Get min/max/mean/std of a field
                - query_select: Count points/cells matching expression (analysis only, not for visualization)
                - get_selection_info: Get info about current selection
                
                VISUALIZATION (create geometry, then use focus_on to focus camera):
                - create_streamlines: Create streamlines at a location
                - create_slice: Create slice plane with camera normal to it (preferred for slices!)
                    normal="x", "y", or "z" - slice and camera will be perpendicular
                - create_vortex_isosurface: Visualize vortical structures. Methods:
                    method="q_criterion" (default): Q = 0.5*(||Ω||² - ||S||²), positive Q = vortex
                    method="vorticity": Vorticity magnitude, includes shear layers
                    method="lambda2": Second eigenvalue of S²+Ω², negative λ2 = vortex core (most accurate)
                    method="swirling_strength": Imaginary eigenvalues of ∇u, good for compressible
                    method="helicity": Normalized helicity |Hn|, identifies helical vortices
                
                VISIBILITY CONTROL (use before visualizations for clean views):
                - hide_all: Hide all proxies - call first for clean slate
                - show_data_context: Show base data as transparent context geometry
                  Typical workflow: hide_all() → show_data_context(opacity=0.15) → create_visualization → focus_on
                
                CAMERA CONTROL:
                - set_view: Set camera to standard view (front/back/top/side/iso) and focus on proxy
                  Use this for slices - view should be NORMAL to slice plane
            """,
            "tools": base_mcp["tools"] + extended_tools,
            "resources": base_mcp.get("resources", {}),
        }
    
    def query_select(self, query: str, field_type: str = "POINT", proxy_name: str = None) -> dict:
        """
        Select points or cells matching a query expression (ANALYSIS ONLY).
        
        NOTE: This is for counting/analysis, NOT visualization. Selection is
        automatically cleared after counting. For visualization, use
        create_streamlines or create_vortex_isosurface instead.
        
        Args:
            query: Expression like "mag(Velocity) < 0.01" or "p > 0.5"
            field_type: "POINT" or "CELL"
            proxy_name: Name of proxy to query, or None for active source
            
        Returns:
            Dict with selection count and query info
            
        Examples:
            query_select("mag(Velocity) < 0.01")  - count near-zero velocity points
            query_select("p < -0.5")              - count low pressure points
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Remember current active source
        original_active = simple.GetActiveSource()
        
        try:
            # Ensure the target proxy is active for QuerySelect
            simple.SetActiveSource(proxy)
            
            simple.QuerySelect(
                QueryString=query,
                FieldType=field_type,
                InsideOut=0
            )
            
            # Extract selection to count and analyze
            extracted = simple.ExtractSelection(Input=proxy)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                merged_data = merge.GetClientSideObject().GetOutput()
                num_selected = merged_data.GetNumberOfPoints() if field_type == "POINT" else merged_data.GetNumberOfCells()
                simple.Delete(merge)
            else:
                num_selected = data.GetNumberOfPoints() if field_type == "POINT" else data.GetNumberOfCells()
            
            simple.Delete(extracted)
            
            # Clear selection to avoid visual clutter (pink dots)
            # Must clear on the specific proxy that has the selection
            simple.SetActiveSource(proxy)
            simple.ClearSelection()
            
            # Restore active source
            simple.SetActiveSource(original_active)
            
            return {
                "query": query,
                "field_type": field_type,
                "num_selected": num_selected,
                "status": "Selection created" if num_selected > 0 else "No matches"
            }
        except Exception as e:
            # Clear selection and restore active source on error
            simple.SetActiveSource(proxy)
            simple.ClearSelection()
            simple.SetActiveSource(original_active)
            return {"error": str(e), "query": query}
    
    def get_selection_info(self, proxy_name: str = None) -> dict:
        """
        Get information about the current selection.
        
        Returns centroid, bounds, and count of selected points/cells.
        
        Args:
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with centroid, bounds, count
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Extract selection to get actual data
            extracted = simple.ExtractSelection(Input=proxy)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutput()
                cleanup_merge = merge
            else:
                cleanup_merge = None
            
            num_points = data.GetNumberOfPoints()
            
            if num_points == 0:
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                simple.Delete(extracted)
                return {"error": "No selection or empty selection"}
            
            # Compute centroid and bounds (vectorized)
            from vtk.util.numpy_support import vtk_to_numpy
            bounds = data.GetBounds()
            points = vtk_to_numpy(data.GetPoints().GetData())
            centroid = points.mean(axis=0).tolist()
            
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            simple.Delete(extracted)
            
            return {
                "num_points": num_points,
                "centroid": centroid,
                "bounds": {
                    "x": [bounds[0], bounds[1]],
                    "y": [bounds[2], bounds[3]],
                    "z": [bounds[4], bounds[5]],
                }
            }
        except Exception as e:
            return {"error": str(e)}
    
    def find_by_query(self, query: str, proxy_name: str = None) -> dict:
        """
        Find the centroid of points matching a query expression.
        
        Combines query_select + get_selection_info in one call.
        Useful for finding flow features like stagnation points.
        
        Args:
            query: Expression like "mag(Velocity) < 0.05" 
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with centroid location, count, and bounds
            
        Examples:
            find_by_query("mag(Velocity) < 0.05")  - find stagnation region
            find_by_query("p < -0.5")              - find low pressure region
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        original_active = simple.GetActiveSource()
        
        try:
            simple.SetActiveSource(proxy)
            
            simple.QuerySelect(
                QueryString=query,
                FieldType="POINT",
                InsideOut=0
            )
            
            extracted = simple.ExtractSelection(Input=proxy)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutput()
                cleanup_merge = merge
            else:
                cleanup_merge = None
            
            num_points = data.GetNumberOfPoints()
            
            if num_points == 0:
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                simple.Delete(extracted)
                simple.SetActiveSource(proxy)
                simple.ClearSelection()
                simple.SetActiveSource(original_active)
                return {"error": "No points match query", "query": query}
            
            # Compute centroid (vectorized)
            from vtk.util.numpy_support import vtk_to_numpy
            bounds = data.GetBounds()
            points = vtk_to_numpy(data.GetPoints().GetData())
            centroid = points.mean(axis=0).tolist()
            
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            simple.Delete(extracted)
            
            # Clear selection to avoid pink dots
            simple.SetActiveSource(proxy)
            simple.ClearSelection()
            simple.SetActiveSource(original_active)
            
            return {
                "location": centroid,
                "num_points": num_points,
                "bounds": [bounds[0], bounds[1], bounds[2], bounds[3], bounds[4], bounds[5]],
                "query": query
            }
        except Exception as e:
            simple.SetActiveSource(proxy)
            simple.ClearSelection()
            simple.SetActiveSource(original_active)
            return {"error": str(e), "query": query}
    
    def create_streamlines(
        self, 
        center: list[float], 
        radius: float = 0.1, 
        num_points: int = 50,
        color_field: str = "Velocity",
        proxy_name: str = None
    ) -> dict:
        """
        Create streamlines seeded at a point cloud location.
        
        CFD convenience tool that creates a fully configured StreamTracer
        in one call (vs 6+ separate tool calls for create, seed config, coloring).
        
        After creation, use focus_on(name) to focus camera on the streamlines.
        
        Args:
            center: [x, y, z] seed center location
            radius: Radius of the point cloud seed
            num_points: Number of seed points
            color_field: Field to color by (default: Velocity)
            proxy_name: Source proxy name (required for explicit input connection)
            
        Returns:
            Dict with status and streamtracer name
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Create StreamTracer with proper input
            stream = simple.StreamTracer(Input=proxy, SeedType="Point Cloud")
            stream.Vectors = ['POINTS', 'Velocity']
            stream.IntegrationDirection = 'BOTH'
            stream.MaximumStreamlineLength = 2.0
            
            # Configure seed
            stream.SeedType.Center = center
            stream.SeedType.Radius = radius
            stream.SeedType.NumberOfPoints = num_points
            
            simple.UpdatePipeline(proxy=stream)
            
            # Show and color
            view = simple.GetActiveView()
            if view is None:
                view = simple.CreateRenderView()
            
            display = simple.Show(stream, view)
            
            # Color by field
            resolved_field = self._resolve_field_name(color_field, stream)
            try:
                simple.ColorBy(display, ('POINTS', resolved_field))
                display.SetScalarBarVisibility(view, True)
            except:
                pass  # Coloring may fail if field not present
            
            # Get the name ParaView assigned
            stream_name = None
            for name, p in simple.GetSources().items():
                if p == stream:
                    stream_name = name[0]
                    break
            
            # Focus camera on the streamlines
            if stream_name:
                self.base_mcp.focus_on(stream_name)
            
            simple.Render(view)
            
            return {
                "status": "created",
                "name": stream_name,
                "center": center,
                "radius": radius,
                "num_points": num_points
            }
        except Exception as e:
            return {"error": str(e)}
    
    def find_minimum(self, field: str, proxy_name: str = None, exclude_boundaries: bool = True) -> dict:
        """
        Find location where a field has minimum value/magnitude.
        
        For vector fields, finds minimum magnitude.
        Useful for finding stagnation points (min velocity).
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            exclude_boundaries: If True, exclude points near domain boundaries
            
        Returns:
            Dict with location [x,y,z] and value
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        # Compute magnitude if vector
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
        else:
            mag = arr.flatten()
        
        if exclude_boundaries:
            bounds = data.GetBounds()
            margin = 0.05
            x_margin = (bounds[1] - bounds[0]) * margin
            y_margin = (bounds[3] - bounds[2]) * margin
            z_margin = (bounds[5] - bounds[4]) * margin if bounds[5] != bounds[4] else 0
            
            # Get all points as numpy array (vectorized)
            from vtk.util.numpy_support import vtk_to_numpy
            points = vtk_to_numpy(data.GetPoints().GetData())
            
            # Vectorized boundary check
            valid_mask = (
                (points[:, 0] >= bounds[0] + x_margin) & (points[:, 0] <= bounds[1] - x_margin) &
                (points[:, 1] >= bounds[2] + y_margin) & (points[:, 1] <= bounds[3] - y_margin)
            )
            if z_margin > 0:
                valid_mask &= (points[:, 2] >= bounds[4] + z_margin) & (points[:, 2] <= bounds[5] - z_margin)
            
            valid_mask &= (mag > 1e-10)
            
            if not np.any(valid_mask):
                idx = np.argmin(mag)
            else:
                masked_mag = np.where(valid_mask, mag, np.inf)
                idx = np.argmin(masked_mag)
        else:
            idx = np.argmin(mag)
        
        location = list(data.GetPoint(idx))
        value = float(mag[idx])
        
        return {
            "location": location,
            "value": value,
            "field": field_name,
            "type": "minimum"
        }
    
    def find_maximum(self, field: str, proxy_name: str = None) -> dict:
        """
        Find location where a field has maximum value/magnitude.
        
        For vector fields, finds maximum magnitude.
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with location [x,y,z] and value
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
        else:
            mag = arr.flatten()
        
        idx = np.argmax(mag)
        location = list(data.GetPoint(idx))
        value = float(mag[idx])
        
        return {
            "location": location,
            "value": value,
            "field": field_name,
            "type": "maximum"
        }
    
    def find_high_gradient(self, field: str, proxy_name: str = None) -> dict:
        """
        Find location of maximum gradient magnitude.
        
        Uses ParaView's Gradient filter to compute the gradient field,
        then finds where gradient magnitude is highest.
        
        Useful for finding:
        - Shear layers (high velocity gradient)
        - Boundary layers
        - Mixing zones
        - Wake edges
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with location [x,y,z] and gradient_magnitude
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        resolved_field = self._resolve_field_type(field, proxy)
        
        # Remember active source
        original_active = simple.GetActiveSource()
        
        try:
            # Check if multiblock by trying to get the output type
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutput()
            
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                input_for_gradient = merge
                cleanup_merge = merge
            else:
                input_for_gradient = proxy
                cleanup_merge = None
            
            # Create Gradient filter
            gradient = simple.Gradient(Input=input_for_gradient)
            gradient.ScalarArray = ['POINTS', resolved_field]
            gradient.ComputeGradient = 1
            gradient.ResultArrayName = "Gradient"
            simple.UpdatePipeline(proxy=gradient)
            
            # Get gradient array
            arr, grad_data = self._get_array(gradient, "Gradient")
            
            if arr is None:
                simple.Delete(gradient)
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                return {"error": f"Could not compute gradient of '{resolved_field}'"}
            
            # Compute gradient magnitude
            if arr.ndim > 1:
                grad_mag = np.linalg.norm(arr, axis=1)
            else:
                grad_mag = np.abs(arr.flatten())
            
            idx = np.argmax(grad_mag)
            location = list(grad_data.GetPoint(idx))
            value = float(grad_mag[idx])
            
            # Cleanup
            simple.Delete(gradient)
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            
            # Restore active source
            simple.SetActiveSource(original_active)
            
            return {
                "location": location,
                "gradient_magnitude": value,
                "field": resolved_field,
                "type": "high_gradient"
            }
        except Exception as e:
            simple.SetActiveSource(original_active)
            return {"error": str(e), "field": field}
    
    def field_statistics(self, field: str, proxy_name: str = None) -> dict:
        """
        Get statistics for a field (min, max, mean, std).
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with min, max, mean, std
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        result = {"field": field_name, "num_points": len(arr)}
        
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
            result["magnitude"] = {
                "min": float(np.min(mag)),
                "max": float(np.max(mag)),
                "mean": float(np.mean(mag)),
                "std": float(np.std(mag)),
            }
            result["components"] = arr.shape[1]
        else:
            arr = arr.flatten()
            result["min"] = float(np.min(arr))
            result["max"] = float(np.max(arr))
            result["mean"] = float(np.mean(arr))
            result["std"] = float(np.std(arr))
            result["components"] = 1
        
        return result
    
    def field_histogram(
        self,
        field: str,
        num_bins: int = 20,
        proxy_name: str = None
    ) -> dict:
        """
        Get histogram data for a field.
        
        Returns bin edges and counts that can be used for plotting.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with bins, counts, and statistics
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        field_name = self._resolve_field_type(field, proxy)
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' not found"}
        
        # Use magnitude for vectors
        if arr.ndim > 1 and arr.shape[1] > 1:
            arr = np.linalg.norm(arr, axis=1)
            field_name = f"{field_name} Magnitude"
        else:
            arr = arr.flatten()
        
        counts, bin_edges = np.histogram(arr, bins=num_bins)
        
        return {
            "field": field_name,
            "num_points": len(arr),
            "bins": bin_edges.tolist(),
            "counts": counts.tolist(),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
        }
    
    def compute_forces(
        self,
        freestream_velocity: float = None,
        reference_area: float = None,
        density: float = 1.0,
        streamwise_axis: str = "x",
        lift_axis: str = "y",
        proxy_name: str = None
    ) -> dict:
        """
        Compute aerodynamic forces (drag/lift) by integrating pressure on surfaces.
        
        Integrates pressure × surface_normal over all surfaces (walls).
        Reports both dimensional forces and non-dimensional coefficients.
        
        Args:
            freestream_velocity: Reference velocity for Cd/Cl (auto-detected if None)
            reference_area: Reference area for Cd/Cl (auto-detected from bounds if None)
            density: Fluid density (default: 1.0 for non-dimensional pressure)
            streamwise_axis: Axis for drag force ("x", "y", or "z", default: "x")
            lift_axis: Axis for lift force ("x", "y", or "z", default: "y")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with drag, lift forces and coefficients
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Merge blocks if multiblock
            data = proxy.GetClientSideObject().GetOutput()
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
            else:
                merge_input = proxy
            
            # Extract surfaces
            surface = simple.ExtractSurface(Input=merge_input)
            simple.UpdatePipeline(proxy=surface)
            
            # Compute normals
            normals = simple.SurfaceNormals(Input=surface)
            normals.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals)
            
            surf_data = normals.GetClientSideObject().GetOutput()
            
            # Handle multiblock by merging
            if surf_data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=normals)
                simple.UpdatePipeline(proxy=merge)
                surf_data = merge.GetClientSideObject().GetOutput()
            else:
                merge = None
            
            # Get pressure (cell data after surface extraction)
            pressure_array = surf_data.GetCellData().GetArray("p")
            if pressure_array is None:
                pressure_array = surf_data.GetCellData().GetArray("Pressure")
            if pressure_array is None:
                # Try point data and use cell centers
                pressure_array = surf_data.GetPointData().GetArray("p")
                if pressure_array is None:
                    pressure_array = surf_data.GetPointData().GetArray("Pressure")
            
            if pressure_array is None:
                if merge:
                    simple.Delete(merge)
                simple.Delete(normals)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No pressure field found (tried 'p' and 'Pressure')"}
            
            pressure = vtk_to_numpy(pressure_array)
            
            # Get surface normals (cell data)
            normal_array = surf_data.GetCellData().GetArray("Normals")
            if normal_array is None:
                if merge:
                    simple.Delete(merge)
                simple.Delete(normals)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "Could not compute surface normals"}
            
            surf_normals = vtk_to_numpy(normal_array)
            
            # Compute cell areas
            num_cells = surf_data.GetNumberOfCells()
            areas = np.zeros(num_cells)
            for i in range(num_cells):
                cell = surf_data.GetCell(i)
                if cell.GetCellType() == 5:  # VTK_TRIANGLE
                    pts = vtk_to_numpy(cell.GetPoints().GetData())
                    v1 = pts[1] - pts[0]
                    v2 = pts[2] - pts[0]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                elif cell.GetCellType() == 9:  # VTK_QUAD
                    pts = vtk_to_numpy(cell.GetPoints().GetData())
                    v1 = pts[2] - pts[0]
                    v2 = pts[3] - pts[1]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                else:
                    # Approximate with bounding box for other types
                    bounds = [0.0] * 6
                    cell.GetBounds(bounds)
                    areas[i] = (bounds[1]-bounds[0]) * (bounds[3]-bounds[2])
            
            # Handle pressure being point data (interpolate to cells)
            if len(pressure) != num_cells:
                # Point data - need to average to cells
                cell_pressure = np.zeros(num_cells)
                for i in range(num_cells):
                    cell = surf_data.GetCell(i)
                    pt_ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
                    cell_pressure[i] = np.mean([pressure[pid] for pid in pt_ids])
                pressure = cell_pressure
            
            # Axis mapping
            axis_map = {"x": 0, "y": 1, "z": 2}
            drag_idx = axis_map.get(streamwise_axis.lower(), 0)
            lift_idx = axis_map.get(lift_axis.lower(), 1)
            
            # Integrate: F = -∫ p * n * dA (negative because pressure acts inward)
            # Drag = force in streamwise direction
            # Lift = force in lift direction
            force_x = -np.sum(pressure * surf_normals[:, 0] * areas)
            force_y = -np.sum(pressure * surf_normals[:, 1] * areas)
            force_z = -np.sum(pressure * surf_normals[:, 2] * areas)
            
            forces = [force_x, force_y, force_z]
            drag = forces[drag_idx]
            lift = forces[lift_idx]
            
            # Get reference values if not provided
            if freestream_velocity is None:
                # Use max velocity magnitude as reference
                vel_array = surf_data.GetPointData().GetArray("Velocity")
                if vel_array is None:
                    # Try from original proxy
                    orig_data = proxy.GetClientSideObject().GetOutput()
                    if orig_data.IsA("vtkMultiBlockDataSet"):
                        orig_data = orig_data.GetBlock(0)
                    vel_array = orig_data.GetPointData().GetArray("Velocity")
                
                if vel_array is not None:
                    vel = vtk_to_numpy(vel_array)
                    freestream_velocity = float(np.max(np.linalg.norm(vel, axis=1)))
                else:
                    freestream_velocity = 1.0
            
            if reference_area is None:
                # Use frontal area (projected area perpendicular to streamwise)
                bounds = surf_data.GetBounds()
                if drag_idx == 0:  # streamwise = x
                    reference_area = (bounds[3] - bounds[2]) * (bounds[5] - bounds[4])
                elif drag_idx == 1:  # streamwise = y
                    reference_area = (bounds[1] - bounds[0]) * (bounds[5] - bounds[4])
                else:  # streamwise = z
                    reference_area = (bounds[1] - bounds[0]) * (bounds[3] - bounds[2])
            
            # Compute coefficients: C = F / (0.5 * ρ * V² * A)
            dynamic_pressure = 0.5 * density * freestream_velocity ** 2
            if dynamic_pressure > 1e-10 and reference_area > 1e-10:
                Cd = drag / (dynamic_pressure * reference_area)
                Cl = lift / (dynamic_pressure * reference_area)
            else:
                Cd = Cl = float('nan')
            
            # Cleanup
            if merge:
                simple.Delete(merge)
            simple.Delete(normals)
            simple.Delete(surface)
            if merge_input != proxy:
                simple.Delete(merge_input)
            
            return {
                "drag_force": float(drag),
                "lift_force": float(lift),
                "force_x": float(force_x),
                "force_y": float(force_y),
                "force_z": float(force_z),
                "Cd": float(Cd),
                "Cl": float(Cl),
                "freestream_velocity": float(freestream_velocity),
                "reference_area": float(reference_area),
                "density": float(density),
                "total_surface_area": float(np.sum(areas)),
                "num_surface_cells": int(num_cells),
                "streamwise_axis": streamwise_axis,
                "lift_axis": lift_axis,
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def create_histogram_chart(
        self,
        field: str,
        num_bins: int = 20,
        proxy_name: str = None
    ) -> dict:
        """
        Create a histogram chart showing field value distribution.
        
        Uses ParaView's Histogram filter and BarChartView.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with chart info and statistics
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            field_name = self._resolve_field_type(field, proxy)
            
            # Merge if multiblock
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutput()
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                hist_input = merge
            else:
                merge = None
                hist_input = proxy
            
            # Create histogram
            hist = simple.Histogram(Input=hist_input)
            hist.SelectInputArray = ['POINTS', field_name]
            hist.BinCount = num_bins
            
            # Check if vector - use magnitude
            arr, _ = self._get_array(proxy, field_name)
            if arr is not None and arr.ndim > 1 and arr.shape[1] > 1:
                hist.Component = 'Magnitude'
                display_name = f"{field_name} Magnitude"
            else:
                display_name = field_name
            
            simple.UpdatePipeline(proxy=hist)
            
            # Create bar chart view
            chart_view = simple.CreateBarChartView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Distribution of {display_name}'
            
            display = simple.Show(hist, chart_view)
            simple.Render(chart_view)
            
            # Get statistics
            if arr is not None:
                if arr.ndim > 1 and arr.shape[1] > 1:
                    arr = np.linalg.norm(arr, axis=1)
                stats = {
                    "min": float(arr.min()),
                    "max": float(arr.max()),
                    "mean": float(arr.mean()),
                    "std": float(arr.std()),
                }
            else:
                stats = {}
            
            # Cleanup merge if created
            if merge:
                simple.Delete(merge)
            
            return {
                "status": "created",
                "chart_type": "histogram",
                "field": display_name,
                "num_bins": num_bins,
                **stats
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def create_force_distribution_chart(
        self,
        force_axis: str = "auto",
        distribution_axis: str = "auto",
        num_bins: int = 40,
        proxy_name: str = None
    ) -> dict:
        """
        Create a chart showing accumulated force distribution along an axis.
        
        Integrates pressure forces on body surfaces and shows:
        - Sectional force: Local force contribution per station
        - Accumulated force: Cumulative sum along the distribution axis
        
        Useful for spanwise loading, chordwise pressure distribution, etc.
        
        Args:
            force_axis: Force component direction:
                - "auto" or "streamwise" or "drag": Auto-detect streamwise (drag direction)
                - "lift": Perpendicular to streamwise (typically y)
                - "x", "y", "z": Explicit axis
            distribution_axis: Axis to distribute along:
                - "auto" or "streamwise": Along flow direction (chordwise)
                - "span": Perpendicular to flow, largest extent (spanwise)
                - "x", "y", "z": Explicit axis
            num_bins: Number of stations along distribution axis (default: 40)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with chart info and force data
            
        Examples:
            # Chordwise drag distribution (auto-detect flow direction)
            create_force_distribution_chart(force_axis="drag", distribution_axis="streamwise")
            
            # Spanwise lift distribution
            create_force_distribution_chart(force_axis="lift", distribution_axis="span")
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Auto-detect streamwise and span directions if needed
            streamwise_axis = None
            span_axis = None
            
            if force_axis in ("auto", "streamwise", "drag") or distribution_axis in ("auto", "streamwise", "span"):
                streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
                if "error" in streamwise_result:
                    return {"error": f"Could not detect streamwise direction: {streamwise_result['error']}"}
                
                streamwise = streamwise_result["streamwise"]  # e.g., "+x", "-y"
                streamwise_axis = streamwise[-1].lower()  # "x", "y", or "z"
                
                # Detect span: perpendicular axis with largest domain extent
                bounds = proxy.GetDataInformation().GetBounds()
                extents = {
                    "x": bounds[1] - bounds[0],
                    "y": bounds[3] - bounds[2],
                    "z": bounds[5] - bounds[4],
                }
                # Find largest extent among non-streamwise axes
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                span_axis = max(perp_axes, key=lambda a: extents[a])
            
            # Resolve force_axis
            if force_axis in ("auto", "streamwise", "drag"):
                force_axis = streamwise_axis
            elif force_axis == "lift":
                # Lift is perpendicular to streamwise, typically vertical (y) or the non-span perp axis
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                # Prefer y for lift if available, otherwise use the non-span axis
                if "y" in perp_axes:
                    force_axis = "y"
                else:
                    force_axis = [a for a in perp_axes if a != span_axis][0] if span_axis else perp_axes[0]
            
            # Resolve distribution_axis
            if distribution_axis in ("auto", "streamwise"):
                distribution_axis = streamwise_axis
            elif distribution_axis == "span":
                distribution_axis = span_axis
            
            # Merge if multiblock
            data = proxy.GetClientSideObject().GetOutput()
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
            else:
                merge_input = proxy
            
            # Extract surface and compute normals
            surface = simple.ExtractSurface(Input=merge_input)
            simple.UpdatePipeline(proxy=surface)
            
            normals_filter = simple.SurfaceNormals(Input=surface)
            normals_filter.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals_filter)
            
            surf_data = normals_filter.GetClientSideObject().GetOutput()
            num_cells = surf_data.GetNumberOfCells()
            
            # Get pressure
            pressure = surf_data.GetPointData().GetArray('p')
            if pressure is None:
                pressure = surf_data.GetPointData().GetArray('Pressure')
            if pressure is None:
                simple.Delete(normals_filter)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No pressure field found"}
            
            pressure = vtk_to_numpy(pressure)
            surf_normals = vtk_to_numpy(surf_data.GetCellData().GetArray('Normals'))
            
            # Compute cell centers, areas, and pressures
            centers = np.zeros((num_cells, 3))
            areas = np.zeros(num_cells)
            cell_pressure = np.zeros(num_cells)
            
            for i in range(num_cells):
                cell = surf_data.GetCell(i)
                pts = vtk_to_numpy(cell.GetPoints().GetData())
                centers[i] = pts.mean(axis=0)
                
                # Area
                if cell.GetCellType() == 5:  # Triangle
                    v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                elif cell.GetCellType() == 9:  # Quad
                    v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                
                # Cell pressure
                pt_ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
                cell_pressure[i] = np.mean([pressure[pid] for pid in pt_ids])
            
            # Filter for body cells (not at domain boundaries)
            bounds = surf_data.GetBounds()
            eps = 0.3
            body_mask = (
                (centers[:, 0] > bounds[0] + eps) & (centers[:, 0] < bounds[1] - eps) &
                (centers[:, 1] > bounds[2] + eps) & (centers[:, 1] < bounds[3] - eps) &
                (centers[:, 2] > bounds[4] + eps) & (centers[:, 2] < bounds[5] - eps)
            )
            
            if body_mask.sum() == 0:
                simple.Delete(normals_filter)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No body cells found (all cells at boundaries)"}
            
            # Axis mapping
            axis_map = {"x": 0, "y": 1, "z": 2}
            force_idx = axis_map.get(force_axis.lower(), 0)
            dist_idx = axis_map.get(distribution_axis.lower(), 0)
            
            # Local force = -p * n_i * dA
            force_per_cell = -cell_pressure * surf_normals[:, force_idx] * areas
            
            pos_body = centers[body_mask, dist_idx]
            force_body = force_per_cell[body_mask]
            
            # Bin by position
            pos_min, pos_max = pos_body.min(), pos_body.max()
            bin_edges = np.linspace(pos_min, pos_max, num_bins + 1)
            bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
            
            binned_force = np.zeros(num_bins)
            for i in range(num_bins):
                mask = (pos_body >= bin_edges[i]) & (pos_body < bin_edges[i+1])
                binned_force[i] = force_body[mask].sum()
            
            accumulated = np.cumsum(binned_force)
            
            # Write CSV for plotting
            import tempfile
            import os
            csv_path = os.path.join(tempfile.gettempdir(), 'force_distribution.csv')
            with open(csv_path, 'w') as f:
                f.write('Position,Sectional_Force,Accumulated_Force\n')
                for i in range(num_bins):
                    f.write(f'{bin_centers[i]:.6f},{binned_force[i]:.8f},{accumulated[i]:.8f}\n')
            
            # Create XY plot
            table = simple.CSVReader(FileName=[csv_path])
            simple.UpdatePipeline(proxy=table)
            
            force_names = {"x": "Drag", "y": "Lift", "z": "Side Force"}
            force_name = force_names.get(force_axis.lower(), "Force")
            
            chart_view = simple.CreateXYPlotView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Accumulated {force_name} Distribution'
            chart_view.BottomAxisTitle = f'{distribution_axis.upper()} Position'
            chart_view.LeftAxisTitle = f'{force_name}'
            
            display = simple.Show(table, chart_view)
            display.XArrayName = 'Position'
            display.UseIndexForXAxis = 0
            display.SeriesVisibility = ['Accumulated_Force', 'Sectional_Force']
            display.SeriesColor = ['Accumulated_Force', '0', '0', '0.8', 'Sectional_Force', '0.8', '0', '0']
            display.SeriesLineThickness = ['Accumulated_Force', '2', 'Sectional_Force', '2']
            
            simple.Render(chart_view)
            
            # Cleanup
            simple.Delete(normals_filter)
            simple.Delete(surface)
            if merge_input != proxy:
                simple.Delete(merge_input)
            
            return {
                "status": "created",
                "chart_type": "force_distribution",
                "force_axis": force_axis,
                "distribution_axis": distribution_axis,
                "position_range": [float(pos_min), float(pos_max)],
                "total_force": float(accumulated[-1]),
                "num_body_cells": int(body_mask.sum()),
                "num_bins": num_bins,
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def create_vortex_isosurface(
        self,
        method: str = "q_criterion",
        threshold: float = None,
        percentile: float = 50.0,
        normalize: bool = True,
        color_field: str = "Velocity",
        proxy_name: str = None
    ) -> dict:
        """
        Create isosurface to visualize vortical structures using various methods.
        
        Methods:
        - "q_criterion": Q = 0.5*(||Ω||² - ||S||²). Positive Q = vortex. (default, fast)
        - "vorticity": Vorticity magnitude ||ω||. High = rotation. (simple but includes shear)
        - "lambda2": Second eigenvalue of S² + Ω². Negative λ2 = vortex core. (accurate)
        - "swirling_strength": Max imaginary eigenvalue of ∇u. Positive = rotation.
        - "helicity": Normalized helicity Hn = (u·ω)/(|u||ω|). |Hn|≈1 = helical vortex.
        
        Threshold selection:
        - Q-criterion, vorticity, swirl: percentile of positive values
        - Lambda2: Uses 1% of min(λ2) by default (small negative, close to 0)
        - Helicity: |Hn| > 0.7 by default (strongly aligned)
        
        Normalization (when normalize=True):
        - Scales by (U_ref)² where U_ref = max|velocity|
        - Makes thresholds more transferable across flow conditions
        
        After creation, use focus_on(name) to focus camera on the isosurface.
        
        Args:
            method: "q_criterion", "vorticity", "lambda2", "swirling_strength", or "helicity"
            threshold: Explicit value for isosurface. If None, auto-computed.
            percentile: Percentile for auto-threshold (default: 50). Not used for lambda2/helicity.
            normalize: If True, normalize by characteristic velocity (default: True)
            color_field: Field to color the isosurface by (default: Velocity)
            proxy_name: Source proxy name (required for explicit input)
            
        Returns:
            Dict with field range, threshold, method, and isosurface name
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Need to merge blocks first for gradient computation
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            
            # Compute gradient with appropriate fields
            gradient = simple.Gradient(Input=merge)
            gradient.ScalarArray = ['POINTS', 'Velocity']
            
            if method == "q_criterion":
                gradient.ComputeQCriterion = 1
                gradient.QCriterionArrayName = "Q"
                field_name = "Q"
                positive_is_vortex = True
            elif method == "vorticity":
                gradient.ComputeVorticity = 1
                gradient.VorticityArrayName = "Vorticity"
                field_name = "Vorticity"  # Will use magnitude
                positive_is_vortex = True
            elif method == "helicity":
                # Need both vorticity and velocity for helicity
                gradient.ComputeVorticity = 1
                gradient.VorticityArrayName = "Vorticity"
                field_name = "NormalizedHelicity"
                positive_is_vortex = True  # We'll use |Hn|
            elif method in ("lambda2", "swirling_strength"):
                # Both require velocity gradient tensor
                gradient.ComputeGradient = 1
                gradient.ResultArrayName = "VelocityGradient"
                field_name = "Lambda2" if method == "lambda2" else "SwirlingStrength"
                positive_is_vortex = (method == "swirling_strength")  # lambda2 uses negative
            else:
                simple.Delete(merge)
                return {"error": f"Unknown method: {method}. Use 'q_criterion', 'vorticity', 'lambda2', 'swirling_strength', or 'helicity'"}
            
            simple.UpdatePipeline(proxy=gradient)
            grad_data = gradient.GetClientSideObject().GetOutput()
            
            # For methods needing custom computation, use ProgrammableFilter
            # This ensures arrays are properly in the pipeline (not just client-side)
            programmable = None
            
            if method == "vorticity":
                # Use Calculator for vorticity magnitude (simpler than ProgrammableFilter)
                calc = simple.Calculator(Input=gradient)
                calc.ResultArrayName = "VorticityMagnitude"
                calc.Function = "mag(Vorticity)"
                simple.UpdatePipeline(proxy=calc)
                
                # Get the data for threshold calculation
                calc_data = calc.GetClientSideObject().GetOutput()
                field_vtk = calc_data.GetPointData().GetArray("VorticityMagnitude")
                field_array = vtk_to_numpy(field_vtk)
                field_name = "VorticityMagnitude"
                contour_input = calc
            
            elif method == "helicity":
                # Normalized helicity needs ProgrammableFilter for dot product
                # Mask low |u| and |ω| regions to avoid noise
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output

# Copy input to output
out.ShallowCopy(inp.VTKObject)

vort = np.ascontiguousarray(vtk_to_numpy(inp.PointData["Vorticity"]))
vel = np.ascontiguousarray(vtk_to_numpy(inp.PointData["Velocity"]))

vel_mag = np.linalg.norm(vel, axis=1)
vort_mag = np.linalg.norm(vort, axis=1)

# Compute thresholds - 10th percentile to filter noise
vel_thresh = np.percentile(vel_mag[vel_mag > 0], 10) if np.any(vel_mag > 0) else 0.01
vort_thresh = np.percentile(vort_mag[vort_mag > 0], 10) if np.any(vort_mag > 0) else 0.01

# Mask low magnitude regions
valid_mask = (vel_mag > vel_thresh) & (vort_mag > vort_thresh)

denom = np.maximum(vel_mag * vort_mag, 1e-10)
helicity = np.abs(np.sum(vel * vort, axis=1) / denom)

# Set invalid regions to 0
helicity = np.where(valid_mask, helicity, 0.0)
helicity = np.ascontiguousarray(helicity)

arr = numpy_to_vtk(helicity)
arr.SetName("NormalizedHelicity")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("NormalizedHelicity")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            elif method == "lambda2":
                # Lambda2 needs eigenvalue computation
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output
out.ShallowCopy(inp.VTKObject)

# Get velocity gradient - handle non-contiguous VTK arrays
grad_vtk = inp.PointData.GetArray("VelocityGradient")
n = grad_vtk.GetNumberOfTuples()
G = np.array([grad_vtk.GetTuple(i) for i in range(n)]).reshape(-1, 3, 3)

# Compute lambda2: second eigenvalue of S^2 + Omega^2 (vectorized)
S = 0.5 * (G + np.transpose(G, (0, 2, 1)))
Omega = 0.5 * (G - np.transpose(G, (0, 2, 1)))
M = np.matmul(S, S) + np.matmul(Omega, Omega)
eigvals = np.linalg.eigvalsh(M)
lambda2 = np.ascontiguousarray(eigvals[:, 1])

arr = numpy_to_vtk(lambda2)
arr.SetName("Lambda2")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("Lambda2")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            elif method == "swirling_strength":
                # Swirling strength needs complex eigenvalues
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output
out.ShallowCopy(inp.VTKObject)

# Get velocity gradient - handle non-contiguous VTK arrays
grad_vtk = inp.PointData.GetArray("VelocityGradient")
n = grad_vtk.GetNumberOfTuples()
G = np.array([grad_vtk.GetTuple(i) for i in range(n)]).reshape(-1, 3, 3)

# Compute swirling strength: max imaginary eigenvalue of grad(u) (vectorized)
eigvals = np.linalg.eigvals(G)
swirl = np.ascontiguousarray(np.max(np.abs(eigvals.imag), axis=1))

arr = numpy_to_vtk(swirl)
arr.SetName("SwirlingStrength")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("SwirlingStrength")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            else:  # q_criterion
                field_vtk = grad_data.GetPointData().GetArray(field_name)
                if field_vtk is None:
                    simple.Delete(gradient)
                    simple.Delete(merge)
                    return {"error": f"Could not compute {field_name}"}
                field_array = vtk_to_numpy(field_vtk)
                contour_input = gradient
            
            field_min, field_max = float(field_array.min()), float(field_array.max())
            
            # Get characteristic velocity and length for normalization
            vel_array = grad_data.GetPointData().GetArray("Velocity")
            if vel_array is not None:
                vel = vtk_to_numpy(vel_array)
                U_ref = float(np.max(np.linalg.norm(vel, axis=1)))
            else:
                U_ref = 1.0
                normalize = False
            
            # Get characteristic length from bounding box
            bounds = grad_data.GetBounds()  # (xmin, xmax, ymin, ymax, zmin, zmax)
            L_ref = float(np.sqrt((bounds[1]-bounds[0])**2 + 
                                  (bounds[3]-bounds[2])**2 + 
                                  (bounds[5]-bounds[4])**2))  # diagonal
            if L_ref < 1e-10:
                L_ref = 1.0
            
            # Compute threshold if not provided
            auto_threshold = threshold is None
            if auto_threshold:
                if method == "lambda2":
                    # Lambda2: use 1% of min (small negative, captures vortex boundary)
                    threshold = 0.01 * field_min
                elif method == "helicity":
                    # Normalized helicity: |Hn| > 0.7 means strongly aligned
                    threshold = 0.7
                elif positive_is_vortex:
                    # Q-criterion, vorticity, swirling strength: use percentile
                    positive_vals = field_array[field_array > 0]
                    if len(positive_vals) > 0:
                        threshold = float(np.percentile(positive_vals, percentile))
                    else:
                        threshold = max(0.0, field_max * 0.01)
                else:
                    # Fallback for negative-indicates-vortex
                    negative_vals = field_array[field_array < 0]
                    if len(negative_vals) > 0:
                        threshold = float(np.percentile(negative_vals, 100 - percentile))
                    else:
                        threshold = min(0.0, field_min * 0.01)
            
            # Create isosurface
            contour = simple.Contour(Input=contour_input)
            contour.ContourBy = ['POINTS', field_name]
            contour.Isosurfaces = [threshold]
            simple.UpdatePipeline(proxy=contour)
            
            # Show and color
            view = simple.GetActiveView()
            if view is None:
                view = simple.CreateRenderView()
            
            # Hide intermediate filters
            simple.Hide(merge, view)
            simple.Hide(gradient, view)
            if contour_input != gradient:
                simple.Hide(contour_input, view)
            
            display = simple.Show(contour, view)
            
            # Color by field
            resolved_field = self._resolve_field_name(color_field, contour)
            try:
                simple.ColorBy(display, ('POINTS', resolved_field))
                display.SetScalarBarVisibility(view, True)
            except:
                pass
            
            # Get contour name
            contour_name = None
            for name, p in simple.GetSources().items():
                if p == contour:
                    contour_name = name[0]
                    break
            
            # Focus camera on the isosurface
            if contour_name:
                self.base_mcp.focus_on(contour_name)
            
            simple.Render(view)
            
            return {
                "status": "created",
                "name": contour_name,
                "method": method,
                "field_name": field_name,
                "field_range": [field_min, field_max],
                "threshold": float(threshold),
                "U_ref": U_ref,
                "L_ref": L_ref,
                "auto_threshold": auto_threshold
            }
        except Exception as e:
            return {"error": str(e)}
    
    def create_slice(
        self,
        origin: list[float] = None,
        normal: str = "x",
        color_field: str = "Velocity",
        proxy_name: str = None
    ) -> dict:
        """
        Create a slice plane and set camera to view it face-on.
        
        This is preferred over the generic 'create' tool for slices because
        it automatically sets the camera normal to the slice plane.
        
        Args:
            origin: [x, y, z] slice origin. If None, uses data center.
            normal: Slice normal direction - "x", "y", or "z"
            color_field: Field to color the slice by (default: Velocity)
            proxy_name: Source proxy name (required for explicit input)
            
        Returns:
            Dict with slice name and view direction
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Get data bounds for default origin using ParaView's data information
            simple.UpdatePipeline(proxy=proxy)
            bounds = proxy.GetDataInformation().GetBounds()
            
            # Default origin is center of bounds
            if origin is None:
                origin = [
                    (bounds[0] + bounds[1]) / 2,
                    (bounds[2] + bounds[3]) / 2,
                    (bounds[4] + bounds[5]) / 2
                ]
            
            # Set normal vector based on direction
            normal_lower = normal.lower()
            if normal_lower in ("x", "+x", "-x"):
                slice_normal = [1, 0, 0]
                view_direction = "+x" if normal_lower != "-x" else "-x"
            elif normal_lower in ("y", "+y", "-y"):
                slice_normal = [0, 1, 0]
                view_direction = "+y" if normal_lower != "-y" else "-y"
            elif normal_lower in ("z", "+z", "-z"):
                slice_normal = [0, 0, 1]
                view_direction = "+z" if normal_lower != "-z" else "-z"
            else:
                return {"error": f"Invalid normal '{normal}'. Use 'x', 'y', or 'z'"}
            
            # Create slice
            slice_filter = simple.Slice(Input=proxy)
            slice_filter.SliceType = 'Plane'
            slice_filter.SliceType.Origin = origin
            slice_filter.SliceType.Normal = slice_normal
            simple.UpdatePipeline(proxy=slice_filter)
            
            # Show and color
            view = simple.GetActiveView()
            if view is None:
                view = simple.CreateRenderView()
            
            display = simple.Show(slice_filter, view)
            
            # Color by field
            resolved_field = self._resolve_field_name(color_field, slice_filter)
            try:
                simple.ColorBy(display, ('POINTS', resolved_field))
                display.SetScalarBarVisibility(view, True)
            except:
                pass
            
            # Get slice name
            slice_name = None
            for name, p in simple.GetSources().items():
                if p == slice_filter:
                    slice_name = name[0]
                    break
            
            # Set view normal to slice plane
            self.set_view(direction=view_direction, proxy_name=slice_name)
            
            return {
                "status": "created",
                "name": slice_name,
                "origin": origin,
                "normal": normal,
                "view_direction": view_direction
            }
        except Exception as e:
            return {"error": str(e)}
    
    def set_view(
        self,
        direction: str = "iso",
        proxy_name: str = None
    ) -> dict:
        """
        Set camera to a standard view direction and focus on a proxy.
        
        Use this after creating visualizations like slices to ensure proper viewing angle.
        For slices, the view should be NORMAL to the slice plane.
        
        Args:
            direction: View direction - one of:
                - "front" or "+x": View from +X (looking at YZ plane)
                - "back" or "-x": View from -X
                - "top" or "+y": View from +Y (looking at XZ plane)
                - "bottom" or "-y": View from -Y
                - "right" or "+z": View from +Z (looking at XY plane)
                - "left" or "-z": View from -Z
                - "iso": Isometric view (default)
            proxy_name: Proxy to focus on (uses its bounds for framing)
            
        Returns:
            Dict with camera settings applied
        """
        view = simple.GetActiveView()
        if view is None:
            view = simple.CreateRenderView()
        
        # Get proxy for bounds
        proxy = self._get_proxy(proxy_name)
        if proxy:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            cx = (bounds[0] + bounds[1]) / 2
            cy = (bounds[2] + bounds[3]) / 2
            cz = (bounds[4] + bounds[5]) / 2
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            distance = max(dx, dy, dz) * 2.0
        else:
            cx, cy, cz = 0, 0, 0
            distance = 5.0
        
        # Set camera based on direction
        dir_lower = direction.lower()
        
        if dir_lower in ["front", "+x", "x"]:
            pos = [cx + distance, cy, cz]
            up = [0, 1, 0]
        elif dir_lower in ["back", "-x"]:
            pos = [cx - distance, cy, cz]
            up = [0, 1, 0]
        elif dir_lower in ["top", "+y", "y"]:
            pos = [cx, cy + distance, cz]
            up = [0, 0, -1]
        elif dir_lower in ["bottom", "-y"]:
            pos = [cx, cy - distance, cz]
            up = [0, 0, 1]
        elif dir_lower in ["right", "+z", "z"]:
            pos = [cx, cy, cz + distance]
            up = [0, 1, 0]
        elif dir_lower in ["left", "-z"]:
            pos = [cx, cy, cz - distance]
            up = [0, 1, 0]
        else:  # iso
            pos = [cx + distance*0.7, cy + distance*0.5, cz + distance*0.7]
            up = [0, 1, 0]
        
        # Apply camera settings
        view.CameraPosition = pos
        view.CameraFocalPoint = [cx, cy, cz]
        view.CameraViewUp = up
        view.CenterOfRotation = [cx, cy, cz]
        
        # Reset to fit bounds
        if proxy:
            view.ResetCamera(*bounds, False, 0.9)
        
        simple.Render(view)
        
        return {
            "status": "view_set",
            "direction": direction,
            "focal_point": [cx, cy, cz]
        }
    
    def detect_streamwise_direction(self, proxy_name: str = None) -> dict:
        """
        Detect the principal flow (streamwise) direction from velocity field.
        
        Uses magnitude-weighted average of velocity vectors to find the dominant
        flow direction. Returns the closest axis-aligned direction.
        
        Returns:
            Dict with streamwise direction (+x, -x, +y, -y, +z, -z) and confidence
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Merge blocks if needed
            cso = proxy.GetClientSideObject()
            if hasattr(cso, 'GetOutput'):
                data = cso.GetOutput()
            else:
                data = cso.GetOutputDataObject(0)
            
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutput()
            else:
                merge = None
            
            # Get velocity array
            vel_array = data.GetPointData().GetArray("Velocity")
            if vel_array is None:
                if merge:
                    simple.Delete(merge)
                return {"error": "No Velocity field found"}
            
            vel = vtk_to_numpy(vel_array)
            
            # Compute magnitude-weighted average direction
            mag = np.linalg.norm(vel, axis=1, keepdims=True)
            mag = np.where(mag > 1e-10, mag, 1e-10)  # avoid division by zero
            
            # Weight by magnitude squared (emphasize high-speed regions)
            weights = mag.flatten() ** 2
            weighted_vel = vel * weights[:, np.newaxis]
            avg_direction = np.sum(weighted_vel, axis=0) / np.sum(weights)
            avg_direction = avg_direction / np.linalg.norm(avg_direction)
            
            if merge:
                simple.Delete(merge)
            
            # Find closest axis-aligned direction
            axes = {
                "+x": np.array([1, 0, 0]),
                "-x": np.array([-1, 0, 0]),
                "+y": np.array([0, 1, 0]),
                "-y": np.array([0, -1, 0]),
                "+z": np.array([0, 0, 1]),
                "-z": np.array([0, 0, -1]),
            }
            
            best_dir = None
            best_dot = -1
            for name, axis in axes.items():
                dot = np.dot(avg_direction, axis)
                if dot > best_dot:
                    best_dot = dot
                    best_dir = name
            
            return {
                "streamwise": best_dir,
                "direction_vector": avg_direction.tolist(),
                "confidence": float(best_dot)  # 1.0 = perfectly aligned with axis
            }
        except Exception as e:
            return {"error": str(e)}
    
    def set_streamwise_view(self, proxy_name: str = None) -> dict:
        """
        Set camera to an isometric view oriented along the streamwise direction.
        
        Detects flow direction and positions camera so:
        - Streamwise direction is left-to-right
        - View is from above and to the side (isometric)
        
        Returns:
            Dict with view settings and detected streamwise direction
        """
        # Detect streamwise direction
        result = self.detect_streamwise_direction(proxy_name)
        if "error" in result:
            return result
        
        streamwise = result["streamwise"]
        
        # Get proxy bounds
        proxy = self._get_proxy(proxy_name)
        if proxy:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            cx = (bounds[0] + bounds[1]) / 2
            cy = (bounds[2] + bounds[3]) / 2
            cz = (bounds[4] + bounds[5]) / 2
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            distance = max(dx, dy, dz) * 2.0
        else:
            cx, cy, cz = 0, 0, 0
            distance = 5.0
        
        view = simple.GetActiveView()
        if view is None:
            view = simple.CreateRenderView()
        
        # Position camera based on streamwise direction
        # Goal: streamwise is left-to-right, slight elevation
        if streamwise in ["+x", "-x"]:
            # Flow along X - view from +Z+Y quadrant
            sign = 1 if streamwise == "+x" else -1
            pos = [cx - sign * distance * 0.3, cy + distance * 0.5, cz + distance * 0.8]
            up = [0, 1, 0]
        elif streamwise in ["+y", "-y"]:
            # Flow along Y - view from +X+Z quadrant
            sign = 1 if streamwise == "+y" else -1
            pos = [cx + distance * 0.8, cy - sign * distance * 0.3, cz + distance * 0.5]
            up = [0, 0, 1] if streamwise == "+y" else [0, 0, -1]
        else:  # +z or -z
            # Flow along Z - view from +X+Y quadrant
            sign = 1 if streamwise == "+z" else -1
            pos = [cx + distance * 0.8, cy + distance * 0.5, cz - sign * distance * 0.3]
            up = [0, 1, 0]
        
        view.CameraPosition = pos
        view.CameraFocalPoint = [cx, cy, cz]
        view.CameraViewUp = up
        view.CenterOfRotation = [cx, cy, cz]
        
        if proxy:
            view.ResetCamera(*bounds, False, 0.9)
        
        simple.Render(view)
        
        return {
            "status": "view_set",
            "streamwise": streamwise,
            "confidence": result["confidence"],
            "focal_point": [cx, cy, cz]
        }
    
    def hide_all(self) -> dict:
        """
        Hide all proxies in the pipeline.
        
        Call this before creating new visualizations to start with a clean view.
        Then use show_data_context() to show base geometry, and visualization
        tools will show their results.
        
        Returns:
            Dict with count of hidden proxies
        """
        view = simple.GetActiveView()
        if view is None:
            return {"status": "no_view", "hidden": 0}
        
        count = 0
        for name, proxy in simple.GetSources().items():
            try:
                simple.Hide(proxy, view)
                count += 1
            except:
                pass
        
        simple.Render(view)
        return {"status": "hidden_all", "count": count}
    
    def show_data_context(
        self,
        proxy_name: str = None,
        opacity: float = 0.15,
        color: list[float] = None
    ) -> dict:
        """
        Show the base data as semi-transparent context geometry.
        
        Call this after hide_all() and before creating visualizations to provide
        spatial context (body surface, domain bounds) without obscuring the
        visualization results.
        
        Args:
            proxy_name: Data source to show. If None, shows first XMLMultiBlockDataReader or XMLUnstructuredGridReader.
            opacity: Transparency level (0.0 = invisible, 1.0 = opaque). Default 0.15.
            color: RGB color [r, g, b] each 0-1. If None, uses solid gray [0.7, 0.7, 0.7].
            
        Returns:
            Dict with proxy shown and display settings
        """
        view = simple.GetActiveView()
        if view is None:
            view = simple.CreateRenderView()
        
        # Find the data source
        proxy = None
        if proxy_name:
            proxy = self._get_proxy(proxy_name)
        else:
            # Auto-find data reader
            for name, p in simple.GetSources().items():
                if any(x in name[0] for x in ['XMLMultiBlockDataReader', 'XMLUnstructuredGridReader', 
                                               'OpenFOAMReader', 'EnSightReader', 'CGNSReader']):
                    proxy = p
                    proxy_name = name[0]
                    break
        
        if proxy is None:
            return {"error": "No data source found"}
        
        # Show with context styling
        display = simple.Show(proxy, view)
        display.Opacity = opacity
        
        # Set solid color (no field coloring for context)
        if color is None:
            color = [0.7, 0.7, 0.7]  # Light gray
        display.DiffuseColor = color
        display.AmbientColor = color
        simple.ColorBy(display, None)  # Solid color mode
        
        # Surface representation
        display.SetRepresentationType('Surface')
        
        simple.Render(view)
        
        return {
            "status": "context_shown",
            "proxy": proxy_name,
            "opacity": opacity,
            "color": color
        }
    
    # Helper methods
    
    # Common field name aliases
    FIELD_ALIASES = {
        "pressure": "p",
        "Pressure": "p",
        "velocity": "Velocity",
        "U": "Velocity",
        "density": "Density",
        "rho": "Density",
    }
    
    def _resolve_field_name(self, field_name: str, proxy) -> str:
        """Resolve field name aliases and find actual field name."""
        # First check if exact name exists using ParaView's data information API
        simple.UpdatePipeline(proxy=proxy)
        
        # Use GetDataInformation for array names - works for all proxy types
        di = proxy.GetDataInformation()
        point_info = di.GetPointDataInformation()
        cell_info = di.GetCellDataInformation()
        
        # Check point data
        for i in range(point_info.GetNumberOfArrays()):
            name = point_info.GetArrayInformation(i).GetName()
            if name == field_name:
                return field_name
            if name.lower() == field_name.lower():
                return name
        
        # Check cell data
        for i in range(cell_info.GetNumberOfArrays()):
            name = cell_info.GetArrayInformation(i).GetName()
            if name == field_name:
                return field_name
            if name.lower() == field_name.lower():
                return name
        
        # Try alias
        if field_name in self.FIELD_ALIASES:
            return self._resolve_field_name(self.FIELD_ALIASES[field_name], proxy)
        
        return field_name  # Return original if not found
    
    def _get_proxy(self, proxy_name: str = None):
        """Get proxy by name or active source."""
        if proxy_name:
            return simple.FindSource(proxy_name)
        return simple.GetActiveSource()
    
    def _get_array(self, proxy, field_name: str):
        """Get VTK array as numpy array."""
        from vtk.util.numpy_support import vtk_to_numpy
        
        simple.UpdatePipeline(proxy=proxy)
        data = proxy.GetClientSideObject().GetOutput()
        
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            data = merge.GetClientSideObject().GetOutput()
        
        arr = data.GetPointData().GetArray(field_name)
        if arr is None:
            arr = data.GetCellData().GetArray(field_name)
        
        if arr is None:
            return None, None
        
        return vtk_to_numpy(arr), data
