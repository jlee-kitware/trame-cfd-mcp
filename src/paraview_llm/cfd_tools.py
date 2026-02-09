"""
CFD Tools MCP - Exposes CFD analysis tools to trame_llm.

This MCP wraps ExtendedParaViewMCP methods and exposes them as tools
that the LLM can discover and chain together.

Architecture:
    llm_client = LLMClient()
    llm_client.register_mcp(ParaViewMCP(app))     # Base: create, update_property, etc.
    llm_client.register_mcp(CFDToolsMCP(app))    # CFD: detect_wake, compute_forces, etc.
    
    # LLM sees ALL tools and chains them:
    # "Show wake streamlines" → 
    #   1. detect_wake_region() → wake_info
    #   2. create_streamlines(center=wake_info.wake_centroid)
"""

from paraview import simple


class CFDToolsMCP:
    """
    MCP wrapper for CFD analysis tools.
    
    These tools are designed to be composable:
    - Query tools return data (bounds, locations, statistics)
    - Action tools take explicit parameters
    - Docstrings tell LLM how to chain them
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
        
        # Find a reader in the pipeline
        reader_patterns = ['Reader', 'OpenFOAM', 'EnSight', 'CGNS', 'XMLMultiBlock', 'ExodusII', 'XDMF']
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            for pattern in reader_patterns:
                if pattern in proxy_name:
                    self._data_source_name = proxy_name
                    return proxy_name
        
        # Fallback: first source that isn't a filter
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
            "instructions": """CFD-specific tools for aerodynamic analysis.

WORKFLOW: Call query tools first, then use results in action tools.

Example - wake visualization:
  wake = detect_wake_region()
  create_streamlines(center=wake["wake_centroid"], radius=wake["suggested_radius"])
""",
            "tools": [
                # Query tools
                self.describe_dataset,
                self.detect_wake_region,
                self.detect_streamwise_direction,
                self.find_stagnation_point,
                self.find_maximum,
                self.find_minimum,
                self.get_field_statistics,
                # Action tools
                self.create_streamlines,
                self.create_vortex_isosurface,
                self.create_body_slice,
                self.compute_forces,
                self.set_streamwise_view,
                self.hide_all,
                self.show_body_context,
            ],
        }
    
    # === Query Tools ===
    
    def describe_dataset(self) -> dict:
        """Describe the loaded CFD dataset (bounds, fields, mesh stats).
        CALL THIS FIRST to understand what data is available."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.characterize_dataset(proxy_name=proxy_name)
    
    def detect_wake_region(self) -> dict:
        """Detect the wake region (velocity deficit behind body).
        
        Returns: wake_centroid, wake_bounds, suggested_radius
        
        USE RESULT FOR: create_streamlines(center=result["wake_centroid"])"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.detect_wake_region(proxy_name=proxy_name)
    
    def detect_streamwise_direction(self) -> dict:
        """Detect primary flow direction.
        
        Returns: streamwise axis (+x, -x, +y, etc.), freestream_velocity"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.detect_streamwise_direction(proxy_name=proxy_name)
    
    def find_stagnation_point(self) -> dict:
        """Find stagnation point (minimum velocity location).
        
        Returns: location [x,y,z], value"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        result = self.ext.find_minimum(field="Velocity", proxy_name=proxy_name, exclude_boundaries=True)
        return {
            "location": result.get("location"),
            "value": result.get("value"),
            "status": "found" if "location" in result else "not_found"
        }
    
    def find_maximum(self, field: str = "pressure") -> dict:
        """Find location of maximum value for a field."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.find_maximum(field=field, proxy_name=proxy_name)
    
    def find_minimum(self, field: str = "pressure") -> dict:
        """Find location of minimum value for a field."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.find_minimum(field=field, proxy_name=proxy_name)
    
    def get_field_statistics(self, field: str = "pressure") -> dict:
        """Get statistics for a field (min, max, mean, std)."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.field_statistics(field=field, proxy_name=proxy_name)
    
    # === Action Tools ===
    
    def create_streamlines(
        self,
        center: list = None,
        radius: float = None,
        num_points: int = 100,
        direction: str = "both"
    ) -> dict:
        """Create streamlines to visualize flow patterns.
        
        Args:
            center: [x,y,z] seed center. If None, auto-detects from wake.
            radius: Seed sphere radius. If None, auto-sized.
            num_points: Number of seed points (default 100)
            direction: "forward", "backward", or "both"
            
        BEST PRACTICE: wake = detect_wake_region(); create_streamlines(center=wake["wake_centroid"])"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.create_streamlines(
            center=center, radius=radius, num_points=num_points,
            direction=direction, proxy_name=proxy_name
        )
    
    def create_vortex_isosurface(
        self,
        method: str = "q_criterion",
        threshold_percentile: float = 50.0
    ) -> dict:
        """Create isosurface showing vortical structures.
        
        Args:
            method: "q_criterion" (default), "lambda2", or "vorticity"
            threshold_percentile: Higher = fewer/stronger vortices (default 50)"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.create_vortex_isosurface(
            method=method, percentile=threshold_percentile, proxy_name=proxy_name
        )
    
    def create_body_slice(
        self,
        location: float = None,
        normal: str = "z",
        color_by: str = "Velocity"
    ) -> dict:
        """Create a slice through the body region (clipped to exclude farfield).
        
        Args:
            location: Position along normal axis. If None, uses body center.
            normal: Slice normal - "x", "y", or "z" (default "z" for top view)
            color_by: Field to color by (default "Velocity")
            
        BEST PRACTICE: wake = detect_wake_region(); create_body_slice(location=wake["wake_centroid"][0])"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        
        # Convert string normal to vector
        normal_map = {
            "x": [1, 0, 0], "-x": [-1, 0, 0],
            "y": [0, 1, 0], "-y": [0, -1, 0],
            "z": [0, 0, 1], "-z": [0, 0, -1],
        }
        normal_vec = normal_map.get(normal.lower(), [0, 0, 1])
        
        return self.ext.create_body_slice(
            normal=normal_vec, color_field=color_by, proxy_name=proxy_name
        )
    
    def compute_forces(
        self,
        freestream_velocity: float = None,
        reference_area: float = None
    ) -> dict:
        """Compute drag and lift forces.
        
        Returns: drag_force, lift_force, and coefficients if reference values provided."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        kwargs = {"proxy_name": proxy_name}
        if freestream_velocity is not None:
            kwargs["freestream_velocity"] = freestream_velocity
        if reference_area is not None:
            kwargs["reference_area"] = reference_area
        return self.ext.compute_forces(**kwargs)
    
    def set_streamwise_view(self) -> dict:
        """Set camera to look along flow direction."""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.set_streamwise_view(proxy_name=proxy_name)
    
    def hide_all(self) -> dict:
        """Hide all visualizations. Call before creating new ones for clean view."""
        return self.ext.hide_all()
    
    def show_body_context(self, opacity: float = 0.15) -> dict:
        """Show body surface as transparent context.
        
        Args:
            opacity: Surface opacity (default 0.15 = very transparent)"""
        proxy_name = self._get_data_source()
        if not proxy_name:
            return {"error": "No data source found"}
        return self.ext.show_data_context(opacity=opacity, proxy_name=proxy_name)
