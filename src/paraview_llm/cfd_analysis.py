"""
CFD Analysis MCP - Pure analysis tools for trame_llm.

Design principle: Resources = Read (state), Tools = Write (compute/mutate)

Resources (cheap, read-only state):
  resource://dataset/summary     - Quick overview
  resource://dataset/fields      - Available fields  
  resource://dataset/bounds      - Spatial bounds
  resource://pipeline/state      - Current filters
  resource://computed/fields     - Derived fields (Q, vorticity)

Tools (actions that compute or mutate):
  compute_vortex_field()         - Adds Q/λ2 array
  detect_wake_region()           - Analyzes flow
  compute_forces()               - Calculates drag/lift
"""

from paraview import simple
import numpy as np


class CFDAnalysisMCP:
    """
    CFD analysis tools following MCP patterns.
    
    Resources provide read-only state inspection.
    Tools perform analysis and computation.
    """
    
    def __init__(self, app, extended_mcp):
        self.app = app
        self.ext = extended_mcp
        self._data_source_name = None
    
    def _get_data_source(self) -> str:
        """Find and cache the primary data source (reader) name."""
        if self._data_source_name:
            if simple.FindSource(self._data_source_name):
                return self._data_source_name
            self._data_source_name = None
        
        reader_patterns = ['Reader', 'OpenFOAM', 'EnSight', 'CGNS', 'XMLMultiBlock', 'ExodusII', 'XDMF']
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            for pattern in reader_patterns:
                if pattern in proxy_name:
                    self._data_source_name = proxy_name
                    return proxy_name
        
        filter_patterns = ['Contour', 'Clip', 'Slice', 'Gradient', 'Calculator', 
                          'Threshold', 'Extract', 'Merge', 'Stream', 'Glyph']
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            if not any(f in proxy_name for f in filter_patterns):
                self._data_source_name = proxy_name
                return proxy_name
        
        return None
    
    @property
    def mcp(self):
        return {
            "name": "CFD Analysis",
            "instructions": """CFD analysis - resources for state, tools for computation.

READ STATE via resources (auto-included in context):
  dataset/summary  - cells, bounds, simulation type
  dataset/fields   - available field names
  computed/fields  - derived fields (Q, vorticity if computed)
  pipeline/filters - current visualization filters

COMPUTE via tools:
  compute_vortex_field(method) → adds Q/λ2/vorticity array
  suggest_threshold(field)     → returns good isosurface value  
  detect_wake_region()         → returns seed location for streamlines
  compute_forces()             → returns drag/lift

WORKFLOW - Vortex visualization:
  1. Read resource://dataset/fields to see available data
  2. compute_vortex_field("q_criterion") → adds "Q" array
  3. suggest_threshold("Q") → returns value like 28.0
  4. [ParaView Contour] on Gradient1, by Q, at 28.0
""",
            "tools": [
                # Dataset inspection (reads resources internally)
                self.describe_dataset,
                
                # Field computation (adds arrays)
                self.compute_vortex_field,
                self.ensure_velocity_vector,
                
                # Value finding (returns numbers/locations)
                self.suggest_threshold,
                self.detect_wake_region,
                self.detect_streamwise_direction,
                self.find_stagnation_point,
                self.find_extremum,
                self.get_field_statistics,
                
                # Force analysis
                self.compute_forces,
            ],
            "resources": {
                # Dataset state - small, cheap reads
                "resource://dataset/summary": self._resource_dataset_summary,
                "resource://dataset/fields": self._resource_dataset_fields,
                "resource://dataset/bounds": self._resource_dataset_bounds,
                
                # Computed state
                "resource://computed/fields": self._resource_computed_fields,
                
                # Pipeline state
                "resource://pipeline/filters": self._resource_pipeline_filters,
                
                # Suggested operations based on data
                "resource://cfd/suggested_operations": self._resource_suggested_operations,
            },
        }
    
    # =========================================================================
    # Resources - Cheap, read-only state inspection
    # =========================================================================
    
    def _resource_dataset_summary(self) -> str:
        """Quick dataset overview: type, cells, timesteps."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return "No dataset loaded"
        
        proxy = simple.FindSource(proxy_name)
        simple.UpdatePipeline(proxy=proxy)
        info = proxy.GetDataInformation()
        
        cells = info.GetNumberOfCells()
        points = info.GetNumberOfPoints()
        bounds = info.GetBounds()
        
        # Detect simulation type
        sim_type = "unknown"
        result = self.ext.characterize_dataset(proxy_name=proxy_name)
        if "simulation_type" in result:
            sim_type = result["simulation_type"]
        
        return f"""Dataset: {proxy_name}
Type: {sim_type}
Cells: {cells:,}
Points: {points:,}
Bounds: [{bounds[0]:.3f}, {bounds[1]:.3f}] x [{bounds[2]:.3f}, {bounds[3]:.3f}] x [{bounds[4]:.3f}, {bounds[5]:.3f}]"""
    
    def _resource_dataset_fields(self) -> str:
        """List available fields."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return "No dataset loaded"
        
        proxy = simple.FindSource(proxy_name)
        simple.UpdatePipeline(proxy=proxy)
        info = proxy.GetDataInformation()
        
        lines = ["Point fields:"]
        point_info = info.GetPointDataInformation()
        for i in range(point_info.GetNumberOfArrays()):
            arr = point_info.GetArrayInformation(i)
            name = arr.GetName()
            components = arr.GetNumberOfComponents()
            lines.append(f"  {name} ({components}D)")
        
        lines.append("\nCell fields:")
        cell_info = info.GetCellDataInformation()
        for i in range(cell_info.GetNumberOfArrays()):
            arr = cell_info.GetArrayInformation(i)
            name = arr.GetName()
            components = arr.GetNumberOfComponents()
            lines.append(f"  {name} ({components}D)")
        
        return "\n".join(lines)
    
    def _resource_dataset_bounds(self) -> str:
        """Spatial bounds for positioning slices/seeds."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return "No dataset loaded"
        
        proxy = simple.FindSource(proxy_name)
        bounds, diag = self.ext._get_body_bounds(proxy)
        center = [
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2,
        ]
        
        return f"""Bounds: x=[{bounds[0]:.4f}, {bounds[1]:.4f}], y=[{bounds[2]:.4f}, {bounds[3]:.4f}], z=[{bounds[4]:.4f}, {bounds[5]:.4f}]
Center: [{center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f}]
Diagonal: {diag:.4f}"""
    
    def _resource_computed_fields(self) -> str:
        """List derived fields that have been computed."""
        computed = []
        
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            if "Gradient" in proxy_name or "Calculator" in proxy_name:
                try:
                    simple.UpdatePipeline(proxy=proxy)
                    data = proxy.GetClientSideObject().GetOutput()
                    if data and hasattr(data, 'GetPointData'):
                        pd = data.GetPointData()
                        for i in range(pd.GetNumberOfArrays()):
                            arr_name = pd.GetArrayName(i)
                            if arr_name in ["Q", "QCriterion", "Vorticity", "VorticityMagnitude", "Lambda2"]:
                                computed.append(f"{arr_name} (in {proxy_name})")
                except:
                    pass
        
        if not computed:
            return "No derived fields. Use compute_vortex_field() to add Q-criterion."
        
        return "Computed fields:\n  " + "\n  ".join(computed)
    
    def _resource_pipeline_filters(self) -> str:
        """List current pipeline filters."""
        filters = []
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            # Check if it's a filter (has input)
            if hasattr(proxy, 'Input') and proxy.Input is not None:
                try:
                    vis = simple.GetDisplayProperties(proxy)
                    visible = vis.Visibility if vis else "?"
                    filters.append(f"{proxy_name} (visible={visible})")
                except:
                    filters.append(proxy_name)
        
        if not filters:
            return "No filters in pipeline"
        
        return "Pipeline filters:\n  " + "\n  ".join(filters)
    
    def _resource_suggested_operations(self) -> str:
        """Suggest ParaView operations based on available data."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return "No dataset loaded"
        
        proxy = simple.FindSource(proxy_name)
        simple.UpdatePipeline(proxy=proxy)
        info = proxy.GetDataInformation()
        
        suggestions = []
        
        # Check for vector fields (velocity)
        pd = info.GetPointDataInformation()
        has_velocity = False
        scalar_fields = []
        for i in range(pd.GetNumberOfArrays()):
            arr = pd.GetArrayInformation(i)
            if arr.GetNumberOfComponents() == 3:
                has_velocity = True
            elif arr.GetNumberOfComponents() == 1:
                scalar_fields.append(arr.GetName())
        
        if has_velocity:
            suggestions.append("StreamTracer - visualize flow paths (needs seed point)")
            suggestions.append("Glyph - show velocity vectors")
            suggestions.append("Gradient + Calculator - compute vorticity, Q-criterion")
        
        if scalar_fields:
            suggestions.append(f"Contour - isosurfaces of {', '.join(scalar_fields[:3])}")
            suggestions.append(f"Threshold - extract regions by {', '.join(scalar_fields[:3])}")
        
        # 3D data operations
        bounds = info.GetBounds()
        is_3d = (bounds[5] - bounds[4]) > 1e-6
        if is_3d:
            suggestions.append("Slice - cut plane through data")
            suggestions.append("Clip - remove half of domain")
        
        suggestions.append("Calculator - compute derived quantities")
        suggestions.append("IntegrateVariables - compute totals (forces, mass flow)")
        suggestions.append("PlotOverLine - extract profile along a line")
        
        return "Suggested operations:\n  " + "\n  ".join(suggestions)
    
    # =========================================================================
    # Tools - Computation and analysis
    # =========================================================================
    
    def describe_dataset(self) -> dict:
        """Get dataset summary - type, cells, fields, bounds, and suggested operations.
        
        Call this first to understand what data is loaded and what you can do with it.
        
        Returns:
            summary: Dataset overview
            fields: Available field names
            bounds: Spatial extent
            suggestions: Recommended operations based on data
        """
        return {
            "summary": self._resource_dataset_summary(),
            "fields": self._resource_dataset_fields(),
            "bounds": self._resource_dataset_bounds(),
            "suggestions": self._resource_suggested_operations(),
        }
    
    def compute_vortex_field(self, method: str = "q_criterion") -> dict:
        """Compute vortex detection field and add to pipeline.
        
        Args:
            method: "q_criterion" (default), "lambda2", "vorticity"
        
        Returns:
            field_name: Name of computed array (e.g., "Q")
            proxy_name: Filter containing the array (e.g., "Gradient1")
            field_range: [min, max]
        
        NEXT: suggest_threshold(field_name) to get isosurface value
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        proxy = simple.FindSource(proxy_name)
        
        # Ensure velocity exists
        vel_result = self.ext.ensure_velocity_vector(proxy_name=proxy_name)
        if "error" in vel_result and "already" not in vel_result.get("error", ""):
            return vel_result
        
        # Merge blocks for gradient
        merge = simple.MergeBlocks(Input=proxy)
        simple.UpdatePipeline(proxy=merge)
        
        # Compute gradient
        gradient = simple.Gradient(Input=merge)
        gradient.ScalarArray = ['POINTS', 'Velocity']
        
        method_config = {
            "q_criterion": {"attr": "ComputeQCriterion", "name_attr": "QCriterionArrayName", 
                          "field": "Q", "positive": True},
            "vorticity": {"attr": "ComputeVorticity", "name_attr": "VorticityArrayName",
                         "field": "Vorticity", "positive": True, "needs_mag": True},
            "lambda2": {"attr": "ComputeGradient", "name_attr": "ResultArrayName",
                       "field": "Lambda2", "positive": False},
        }
        
        if method not in method_config:
            return {"error": f"Unknown method: {method}. Use: {list(method_config.keys())}"}
        
        config = method_config[method]
        setattr(gradient, config["attr"], 1)
        if "name_attr" in config:
            setattr(gradient, config["name_attr"], config["field"])
        
        simple.UpdatePipeline(proxy=gradient)
        
        output_proxy = gradient
        field_name = config["field"]
        
        if config.get("needs_mag"):
            calc = simple.Calculator(Input=gradient)
            calc.ResultArrayName = f"{field_name}Magnitude"
            calc.Function = f"mag({field_name})"
            simple.UpdatePipeline(proxy=calc)
            output_proxy = calc
            field_name = f"{field_name}Magnitude"
        
        # Get field range
        data = output_proxy.GetClientSideObject().GetOutput()
        arr = data.GetPointData().GetArray(field_name)
        if arr is None:
            return {"error": f"Field {field_name} not computed"}
        
        values = vtk_to_numpy(arr)
        if len(values.shape) > 1:
            values = np.linalg.norm(values, axis=1)
        
        # Get proxy name
        output_name = None
        for name, p in simple.GetSources().items():
            if p == output_proxy:
                output_name = name[0]
                break
        
        return {
            "field_name": field_name,
            "proxy_name": output_name,
            "field_range": [float(np.min(values)), float(np.max(values))],
            "positive_is_vortex": config["positive"],
        }
    
    def ensure_velocity_vector(self) -> dict:
        """Ensure velocity vector exists (compute from components if needed)."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.ensure_velocity_vector(proxy_name=proxy_name)
    
    def suggest_threshold(self, field: str, percentile: float = 50.0) -> dict:
        """Suggest isosurface threshold for a field.
        
        Args:
            field: Field name (e.g., "Q")
            percentile: Percentile of positive values (default 50)
        
        Returns:
            value: Suggested threshold for Contour filter
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        # Find proxy with this field
        proxy = None
        for name, p in simple.GetSources().items():
            try:
                simple.UpdatePipeline(proxy=p)
                data = p.GetClientSideObject().GetOutput()
                if data is None:
                    continue
                if data.IsA("vtkMultiBlockDataSet"):
                    block = data.GetBlock(0)
                    while block and block.IsA("vtkMultiBlockDataSet"):
                        block = block.GetBlock(0)
                    data = block
                if data and data.GetPointData().GetArray(field):
                    proxy = p
                    break
            except:
                continue
        
        if proxy is None:
            return {"error": f"Field '{field}' not found. Run compute_vortex_field() first."}
        
        data = proxy.GetClientSideObject().GetOutput()
        if data.IsA("vtkMultiBlockDataSet"):
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            data = merge.GetClientSideObject().GetOutput()
        
        arr = data.GetPointData().GetArray(field)
        values = vtk_to_numpy(arr)
        
        if len(values.shape) > 1:
            values = np.linalg.norm(values, axis=1)
        
        positive = values[values > 0]
        if len(positive) > 0:
            threshold = float(np.percentile(positive, percentile))
        else:
            threshold = float(np.percentile(values, percentile))
        
        return {
            "value": threshold,
            "percentile": percentile,
            "field_range": [float(np.min(values)), float(np.max(values))],
        }
    
    def detect_wake_region(self) -> dict:
        """Detect wake region for streamline seeding.
        
        Returns:
            center: [x, y, z] - use for StreamTracer seed
            radius: Suggested seed radius
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.detect_wake_region(proxy_name=proxy_name)
        if "error" in result:
            return result
        
        return {
            "center": result.get("wake_centroid"),
            "radius": result.get("cross_stream_extent", 0.1) / 2,
            "bounds": result.get("wake_bounds"),
        }
    
    def detect_streamwise_direction(self) -> dict:
        """Detect primary flow direction.
        
        Returns:
            axis: "+x", "-x", etc.
            vector: [vx, vy, vz] unit vector
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.detect_streamwise_direction(proxy_name=proxy_name)
        return {
            "axis": result.get("streamwise"),
            "vector": result.get("direction_vector"),
        }
    
    def find_stagnation_point(self) -> dict:
        """Find stagnation point (minimum velocity)."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.find_minimum(field="Velocity", proxy_name=proxy_name, exclude_boundaries=True)
        return {
            "location": result.get("location"),
            "velocity": result.get("value"),
        }
    
    def find_extremum(self, field: str, find_max: bool = True) -> dict:
        """Find field maximum or minimum location."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        if find_max:
            return self.ext.find_maximum(field=field, proxy_name=proxy_name)
        else:
            return self.ext.find_minimum(field=field, proxy_name=proxy_name)
    
    def get_field_statistics(self, field: str) -> dict:
        """Get min, max, mean, std for a field."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.field_statistics(field=field, proxy_name=proxy_name)
    
    def compute_forces(self) -> dict:
        """Compute aerodynamic forces (drag, lift)."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.compute_forces(proxy_name=proxy_name)
