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
        """
        Args:
            app: Trame application instance
            extended_mcp: ExtendedParaViewMCP instance with the actual implementations
        """
        self.app = app
        self.ext = extended_mcp
    
    @property
    def mcp(self):
        return {
            "name": "CFD Analysis Tools",
            "instructions": """
CFD-specific tools for aerodynamic analysis and visualization.

QUERY TOOLS (return data to use in subsequent calls):
- detect_wake_region: Find wake location and bounds
- detect_streamwise_direction: Find flow direction  
- find_stagnation_point: Find where velocity is minimum
- get_field_statistics: Get min/max/mean of a field
- describe_dataset: Get overview of loaded data

ACTION TOOLS (create visualizations using query results):
- create_streamlines: Visualize flow paths (pass center from detect_wake_region)
- create_vortex_isosurface: Show vortex structures
- create_body_slice: Create slice through body region
- compute_forces: Calculate drag and lift

WORKFLOW PATTERN:
1. Call query tool to get location/bounds
2. Use result to parameterize action tool

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
    
    # =========================================================================
    # Query Tools - Return data for LLM to use
    # =========================================================================
    
    def describe_dataset(self) -> dict:
        """
        Describe the loaded CFD dataset.
        
        Returns overview including:
        - Bounds and dimensions
        - Available fields (velocity, pressure, etc.)
        - Number of cells/points
        - Body location (if detected)
        
        CALL THIS FIRST to understand what data is available.
        
        Returns:
            Dict with dataset characterization
        """
        return self.ext.characterize_dataset()
    
    def detect_wake_region(self) -> dict:
        """
        Detect the wake region behind a body.
        
        Finds where velocity is significantly lower than freestream,
        indicating the wake/deficit region.
        
        Returns:
            Dict with:
            - wake_centroid: [x, y, z] center of wake region
            - wake_bounds: [xmin, xmax, ymin, ymax, zmin, zmax]
            - velocity_threshold: velocity value used for detection
            - suggested_radius: good radius for seeding streamlines
            
        USE THE RESULT TO:
        - create_streamlines(center=result["wake_centroid"])
        - create_body_slice(location=result["wake_centroid"][0])
        """
        return self.ext.detect_wake_region()
    
    def detect_streamwise_direction(self) -> dict:
        """
        Detect the primary flow direction (streamwise axis).
        
        Analyzes the velocity field to determine which axis
        aligns with the main flow direction.
        
        Returns:
            Dict with:
            - streamwise: axis name ("+x", "-x", "+y", etc.)
            - freestream_velocity: magnitude of freestream
            
        USE THE RESULT TO:
        - set_streamwise_view() to look along flow
        - interpret wake_bounds from detect_wake_region()
        """
        return self.ext.detect_streamwise_direction()
    
    def find_stagnation_point(self) -> dict:
        """
        Find the stagnation point where flow velocity is zero/minimum.
        
        Returns:
            Dict with:
            - location: [x, y, z] coordinates
            - value: velocity magnitude at that point
            
        USE THE RESULT TO:
        - create_point_marker(location=result["location"]) to mark it
        - understand leading edge location
        """
        result = self.ext.find_minimum(field="Velocity", exclude_boundaries=True)
        return {
            "location": result.get("location"),
            "value": result.get("value"),
            "status": "found" if "location" in result else "not_found"
        }
    
    def find_maximum(self, field: str = "pressure") -> dict:
        """
        Find location of maximum value for a field.
        
        Args:
            field: Field name (pressure, Velocity, etc.)
            
        Returns:
            Dict with location and value
        """
        return self.ext.find_maximum(field=field)
    
    def find_minimum(self, field: str = "pressure") -> dict:
        """
        Find location of minimum value for a field.
        
        Args:
            field: Field name (pressure, Velocity, etc.)
            
        Returns:
            Dict with location and value
        """
        return self.ext.find_minimum(field=field)
    
    def get_field_statistics(self, field: str = "pressure") -> dict:
        """
        Get statistics for a field (min, max, mean, std).
        
        Args:
            field: Field name to analyze
            
        Returns:
            Dict with min, max, mean, std, and percentiles
        """
        return self.ext.field_statistics(field=field)
    
    # =========================================================================
    # Action Tools - Create visualizations
    # =========================================================================
    
    def create_streamlines(
        self,
        center: list = None,
        radius: float = None,
        num_points: int = 100,
        direction: str = "both"
    ) -> dict:
        """
        Create streamlines to visualize flow patterns.
        
        Seeds streamlines from a spherical point cloud centered at
        the specified location.
        
        Args:
            center: [x, y, z] seed center. If None, auto-detects from wake.
            radius: Seed sphere radius. If None, auto-sized to wake.
            num_points: Number of seed points (default 100)
            direction: "forward", "backward", or "both"
            
        Returns:
            Dict with streamline info
            
        BEST PRACTICE - get location first:
            wake = detect_wake_region()
            create_streamlines(
                center=wake["wake_centroid"],
                radius=wake["suggested_radius"]
            )
        """
        return self.ext.create_streamlines(
            center=center,
            radius=radius,
            num_points=num_points,
            direction=direction
        )
    
    def create_vortex_isosurface(
        self,
        method: str = "q_criterion",
        threshold_percentile: float = 50.0
    ) -> dict:
        """
        Create isosurface showing vortical structures.
        
        Args:
            method: Detection method
                - "q_criterion": Q-criterion (default, good general choice)
                - "lambda2": Lambda2 criterion (vortex cores)
                - "vorticity": Vorticity magnitude
            threshold_percentile: Percentile for threshold (default 50)
                Higher = fewer/stronger vortices shown
                
        Returns:
            Dict with isosurface info and threshold used
        """
        return self.ext.create_vortex_isosurface(
            method=method,
            percentile=threshold_percentile
        )
    
    def create_body_slice(
        self,
        location: float = None,
        normal: str = "x",
        color_by: str = "Velocity"
    ) -> dict:
        """
        Create a slice through the body region.
        
        The slice is automatically clipped to the body region
        (excluding farfield).
        
        Args:
            location: Position along normal axis. If None, uses body center.
            normal: Slice normal direction - "x", "y", or "z"
            color_by: Field to color by (default "Velocity")
            
        Returns:
            Dict with slice info
            
        BEST PRACTICE - use detected locations:
            wake = detect_wake_region()
            create_body_slice(location=wake["wake_centroid"][0])
        """
        return self.ext.create_body_slice(
            normal=normal,
            color_field=color_by
        )
    
    def compute_forces(
        self,
        freestream_velocity: float = None,
        reference_area: float = None
    ) -> dict:
        """
        Compute aerodynamic forces (drag and lift).
        
        Integrates pressure and skin friction over body surfaces.
        
        Args:
            freestream_velocity: Reference velocity for Cd/Cl (auto-detected if None)
            reference_area: Reference area for Cd/Cl (auto-detected if None)
            
        Returns:
            Dict with:
            - drag_force, lift_force: Absolute forces
            - cd, cl: Coefficients (if reference values provided)
            - pressure_drag, friction_drag: Drag breakdown
        """
        kwargs = {}
        if freestream_velocity is not None:
            kwargs["freestream_velocity"] = freestream_velocity
        if reference_area is not None:
            kwargs["reference_area"] = reference_area
        return self.ext.compute_forces(**kwargs)
    
    def set_streamwise_view(self) -> dict:
        """
        Set camera to look along the flow direction.
        
        Useful after creating visualizations to get a good view.
        
        Returns:
            Dict with camera info
        """
        return self.ext.set_streamwise_view()
    
    def hide_all(self) -> dict:
        """
        Hide all visualizations.
        
        Call before creating new visualizations for a clean view.
        
        Returns:
            Dict with status
        """
        return self.ext.hide_all()
    
    def show_body_context(self, opacity: float = 0.15) -> dict:
        """
        Show the body surface as transparent context.
        
        Useful as background when showing flow features.
        
        Args:
            opacity: Surface opacity (default 0.15 = very transparent)
            
        Returns:
            Dict with status
        """
        return self.ext.show_data_context(opacity=opacity)
