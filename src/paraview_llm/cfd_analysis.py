"""
CFD Analysis Tools MCP - Pure analysis tools for trame_llm.

Design principle: CFD knowledge in analysis, ParaView operations in base tools.

These tools compute CFD-meaningful information. Visualization is done by
base ParaView tools (Contour, StreamTracer, Slice, etc.).

Architecture:
    "Show vortices"
    → compute_vortex_field("q_criterion")     # Analysis: adds Q array
    → suggest_threshold("Q", percentile=50)   # Analysis: finds good value
    → [ParaView] Contour on Q at threshold    # Base tool: visualization
"""

from paraview import simple
import numpy as np


class CFDAnalysisMCP:
    """
    Pure CFD analysis tools - no visualization.
    
    Query tools return data that guides ParaView tool usage.
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
            "name": "CFD Analysis Tools",
            "instructions": """CFD analysis tools - compute fields and find values.

These tools add arrays or return values. Use base ParaView tools for visualization.

WORKFLOW EXAMPLE - Vortex visualization:
  1. vortex = compute_vortex_field("q_criterion")  → adds "Q" array
  2. thresh = suggest_threshold("Q", 50)           → returns threshold value
  3. [ParaView Contour] on vortex.proxy_name, by "Q", at thresh.value

WORKFLOW EXAMPLE - Wake streamlines:
  1. wake = detect_wake_region()                   → returns center, radius
  2. [ParaView StreamTracer] with PointSource at wake.center, wake.radius
""",
            "tools": [
                # Dataset info
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
                
                # Utility
                self.get_body_bounds,
            ],
        }
    
    # =========================================================================
    # Dataset Info
    # =========================================================================
    
    def describe_dataset(self) -> dict:
        """Describe loaded CFD dataset (bounds, fields, mesh stats).
        
        CALL FIRST to understand available data."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.characterize_dataset(proxy_name=proxy_name)
    
    # =========================================================================
    # Field Computation - These ADD arrays to the pipeline
    # =========================================================================
    
    def compute_vortex_field(self, method: str = "q_criterion") -> dict:
        """Compute vortex detection field and add to pipeline.
        
        Args:
            method: "q_criterion" (default), "lambda2", "vorticity", "helicity"
        
        Returns:
            field_name: Name of computed array (e.g., "Q")
            proxy_name: Name of filter with the array (e.g., "Gradient1")
            field_range: [min, max] of the field
            positive_is_vortex: True if positive values indicate vortices
        
        NEXT STEPS:
        - suggest_threshold(field_name) to get isosurface value
        - [ParaView Contour] on proxy_name, by field_name, at threshold
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
        
        # Compute gradient with requested field
        gradient = simple.Gradient(Input=merge)
        gradient.ScalarArray = ['POINTS', 'Velocity']
        
        method_config = {
            "q_criterion": {"attr": "ComputeQCriterion", "name_attr": "QCriterionArrayName", 
                          "field": "Q", "positive": True},
            "vorticity": {"attr": "ComputeVorticity", "name_attr": "VorticityArrayName",
                         "field": "Vorticity", "positive": True, "needs_mag": True},
            "lambda2": {"attr": "ComputeGradient", "name_attr": "ResultArrayName",
                       "field": "Lambda2", "positive": False},  # negative = vortex
        }
        
        if method not in method_config:
            return {"error": f"Unknown method: {method}. Use: {list(method_config.keys())}"}
        
        config = method_config[method]
        setattr(gradient, config["attr"], 1)
        if "name_attr" in config:
            setattr(gradient, config["name_attr"], config["field"])
        
        simple.UpdatePipeline(proxy=gradient)
        
        # For vorticity, compute magnitude
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
            "method": method,
        }
    
    def ensure_velocity_vector(self) -> dict:
        """Ensure velocity vector exists (compute from components if needed).
        
        Returns:
            velocity_field: Name of velocity array
            status: "exists" or "computed"
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.ensure_velocity_vector(proxy_name=proxy_name)
    
    # =========================================================================
    # Value Finding - Return numbers/locations for use in ParaView tools
    # =========================================================================
    
    def suggest_threshold(self, field: str, percentile: float = 50.0) -> dict:
        """Suggest isosurface threshold value for a field.
        
        Args:
            field: Field name (e.g., "Q", "VorticityMagnitude")
            percentile: Percentile of positive values (default 50)
        
        Returns:
            value: Suggested threshold
            percentile: Percentile used
            field_range: [min, max]
        
        USE FOR: [ParaView Contour] at this value
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        # Find proxy with this field
        proxy = None
        for name, p in simple.GetSources().items():
            simple.UpdatePipeline(proxy=p)
            try:
                data = p.GetClientSideObject().GetOutput()
                if data is None:
                    continue
                # Handle multiblock - get first leaf block
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
            return {"error": f"Field '{field}' not found in any proxy"}
        
        # Get data again for value extraction
        data = proxy.GetClientSideObject().GetOutput()
        if data.IsA("vtkMultiBlockDataSet"):
            # Merge blocks to get combined array
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            data = merge.GetClientSideObject().GetOutput()
        
        arr = data.GetPointData().GetArray(field)
        if arr is None:
            return {"error": f"Field '{field}' not found after merge"}
        
        values = vtk_to_numpy(arr)
        
        if len(values.shape) > 1:
            values = np.linalg.norm(values, axis=1)
        
        # Use positive values for percentile (typical for vortex fields)
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
        """Detect wake region (velocity deficit behind body).
        
        Returns:
            center: [x, y, z] wake centroid - USE FOR StreamTracer seed
            radius: Suggested seed radius
            bounds: [xmin, xmax, ymin, ymax, zmin, zmax]
            velocity_deficit: Fraction of freestream
        
        USE FOR: [ParaView StreamTracer] PointSource at center with radius
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.detect_wake_region(proxy_name=proxy_name)
        
        # Simplify output for tool chaining
        if "error" in result:
            return result
        
        return {
            "center": result.get("wake_centroid"),
            "radius": result.get("cross_stream_extent", 0.1) / 2,
            "bounds": result.get("wake_bounds"),
            "velocity_deficit": result.get("velocity_threshold"),
        }
    
    def detect_streamwise_direction(self) -> dict:
        """Detect primary flow direction.
        
        Returns:
            axis: "+x", "-x", "+y", "-y", "+z", "-z"
            vector: [vx, vy, vz] unit vector
            freestream_velocity: Magnitude
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.detect_streamwise_direction(proxy_name=proxy_name)
        return {
            "axis": result.get("streamwise"),
            "vector": result.get("direction_vector"),
            "freestream_velocity": result.get("freestream_velocity"),
        }
    
    def find_stagnation_point(self) -> dict:
        """Find stagnation point (minimum velocity).
        
        Returns:
            location: [x, y, z]
            velocity: Value at that point
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        result = self.ext.find_minimum(field="Velocity", proxy_name=proxy_name, exclude_boundaries=True)
        return {
            "location": result.get("location"),
            "velocity": result.get("value"),
        }
    
    def find_extremum(self, field: str, find_max: bool = True) -> dict:
        """Find location of field maximum or minimum.
        
        Args:
            field: Field name
            find_max: True for maximum, False for minimum
        
        Returns:
            location: [x, y, z]
            value: Field value there
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        if find_max:
            return self.ext.find_maximum(field=field, proxy_name=proxy_name)
        else:
            return self.ext.find_minimum(field=field, proxy_name=proxy_name)
    
    def get_field_statistics(self, field: str) -> dict:
        """Get statistics for a field.
        
        Returns:
            min, max, mean, std: Basic statistics
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.field_statistics(field=field, proxy_name=proxy_name)
    
    def get_body_bounds(self) -> dict:
        """Get bounds of body region (excluding farfield).
        
        Returns:
            bounds: [xmin, xmax, ymin, ymax, zmin, zmax]
            center: [x, y, z]
        
        USE FOR: Slice origin, Clip bounds, camera focus
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        proxy = simple.FindSource(proxy_name)
        bounds, diag = self.ext._get_body_bounds(proxy)
        
        return {
            "bounds": list(bounds),
            "center": [
                (bounds[0] + bounds[1]) / 2,
                (bounds[2] + bounds[3]) / 2,
                (bounds[4] + bounds[5]) / 2,
            ],
            "diagonal": diag,
        }
    
    # =========================================================================
    # Force Analysis
    # =========================================================================
    
    def compute_forces(self) -> dict:
        """Compute aerodynamic forces.
        
        Returns:
            drag: Drag force
            lift: Lift force  
            streamwise_axis: Which axis is streamwise
        """
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.compute_forces(proxy_name=proxy_name)
