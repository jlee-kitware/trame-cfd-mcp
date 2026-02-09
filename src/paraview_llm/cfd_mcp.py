"""
CFD MCP - Exposes CFD-specific tools to trame_llm.

This is designed to be registered alongside ParaViewMCP, giving the LLM
access to both base ParaView tools AND CFD-specific tools. The LLM
decides what to use based on the user's request.

Architecture:
    llm_client = LLMClient()
    llm_client.register_mcp(ParaViewMCP(app))   # Base: create, update_property, etc.
    llm_client.register_mcp(CFDMCP(app))        # CFD: visualize_vortices, compute_forces, etc.
    
    # LLM sees ALL tools and picks appropriately:
    # "Create a slice" → uses base create tool
    # "Show vortices" → uses CFD visualize_vortices tool
"""

from paraview import simple


class CFDMCP:
    """
    CFD-specific MCP tools for trame_llm.
    
    These tools encode domain knowledge - the LLM doesn't need to know
    HOW to visualize vortices, it just calls the tool.
    """
    
    def __init__(self, app, extended_mcp=None):
        self.app = app
        self.extended = extended_mcp
        self._data_source = None
    
    def _get_data_source(self):
        """Find the data source proxy."""
        if self._data_source:
            return self._data_source
        for name, proxy in simple.GetSources().items():
            if any(x in name[0] for x in ['Reader', 'OpenFOAM', 'EnSight', 'CGNS', 'XMLMultiBlock']):
                self._data_source = name[0]
                return self._data_source
        return None
    
    @property
    def mcp(self):
        return {
            "name": "CFD Analysis Tools",
            "instructions": """
                CFD-specific visualization and analysis tools.
                Use these for aerodynamic analysis tasks like vortex detection,
                force computation, wake visualization, and flow feature analysis.
                
                For basic ParaView operations (create filter, change color, etc.),
                use the ParaView tools instead.
            """,
            "tools": [
                self.visualize_vortices,
                self.visualize_wake,
                self.visualize_streamlines,
                self.compute_forces,
                self.find_stagnation_point,
                self.analyze_drag_distribution,
                self.analyze_lift_distribution,
                self.describe_data,
                self.show_field_histogram,
            ],
        }
    
    def visualize_vortices(self, method: str = "q_criterion") -> dict:
        """
        Visualize vortical structures in the flow.
        
        Creates an isosurface showing vortex cores. The threshold is
        automatically determined from the data.
        
        Args:
            method: Detection method - one of:
                - "q_criterion": Q-criterion (default, good general choice)
                - "lambda2": Lambda2 criterion (vortex cores)
                - "helicity": Helicity (helical/corkscrew structures)
                - "vorticity": Vorticity magnitude (includes shear)
        
        Returns:
            Dict with created filter name and threshold used.
            
        Example:
            "Show me the vortices" → visualize_vortices()
            "Visualize helical structures" → visualize_vortices(method="helicity")
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        # Hide everything, show context
        self.extended.hide_all()
        self.extended.show_data_context(opacity=0.15)
        
        # Ensure velocity vector exists
        self.extended.ensure_velocity_vector(proxy_name=self._get_data_source())
        
        # Create vortex isosurface with auto threshold
        result = self.extended.create_vortex_isosurface(
            method=method,
            percentile=50,
            proxy_name=self._get_data_source()
        )
        
        # Focus on result
        if "contour_name" in result:
            simple.ResetCamera()
            self.app.update()
        
        return result
    
    def visualize_wake(self) -> dict:
        """
        Visualize the wake region behind a body.
        
        Shows velocity deficit region with streamlines. Automatically
        detects wake by finding low velocity regions downstream.
        
        Returns:
            Dict with wake bounds and streamline info.
            
        Example:
            "Show me the wake" → visualize_wake()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        self.extended.hide_all()
        self.extended.show_data_context(opacity=0.15)
        self.extended.ensure_velocity_vector(proxy_name=self._get_data_source())
        
        # Detect wake and create streamlines
        wake_result = self.extended.detect_wake_region(proxy_name=self._get_data_source())
        stream_result = self.extended.create_streamlines(
            proxy_name=self._get_data_source(),
            seed_type="Point Cloud"
        )
        
        simple.ResetCamera()
        self.app.update()
        
        return {
            "wake": wake_result,
            "streamlines": stream_result
        }
    
    def visualize_streamlines(self, seed_type: str = "Point Cloud", num_points: int = 100) -> dict:
        """
        Create streamlines showing flow paths.
        
        Args:
            seed_type: How to seed streamlines - "Point Cloud" or "Line"
            num_points: Number of seed points
        
        Returns:
            Dict with streamline filter info.
            
        Example:
            "Show streamlines" → visualize_streamlines()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        self.extended.hide_all()
        self.extended.show_data_context(opacity=0.15)
        self.extended.ensure_velocity_vector(proxy_name=self._get_data_source())
        
        result = self.extended.create_streamlines(
            proxy_name=self._get_data_source(),
            seed_type=seed_type,
            num_points=num_points
        )
        
        simple.ResetCamera()
        self.app.update()
        
        return result
    
    def compute_forces(self, freestream_velocity: float = 1.0, reference_area: float = 1.0) -> dict:
        """
        Compute drag and lift forces on the body.
        
        Integrates pressure over surfaces to compute aerodynamic forces.
        
        Args:
            freestream_velocity: Reference velocity for force coefficients
            reference_area: Reference area for force coefficients
        
        Returns:
            Dict with drag, lift, and force coefficients.
            
        Example:
            "What are the forces?" → compute_forces()
            "Calculate drag and lift" → compute_forces()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        return self.extended.compute_forces(
            freestream_velocity=freestream_velocity,
            reference_area=reference_area,
            proxy_name=self._get_data_source()
        )
    
    def find_stagnation_point(self) -> dict:
        """
        Find the stagnation point where flow velocity is zero.
        
        Returns:
            Dict with location and pressure at stagnation point.
            
        Example:
            "Where is the stagnation point?" → find_stagnation_point()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        result = self.extended.find_minimum(
            field_name="Velocity",
            proxy_name=self._get_data_source()
        )
        
        # Add marker
        if "location" in result:
            self.extended.create_point_marker(
                location=result["location"],
                color=[1, 0, 0],
                size=0.05
            )
            self.app.update()
        
        return result
    
    def analyze_drag_distribution(self) -> dict:
        """
        Analyze how drag is distributed along the body.
        
        Creates a chart showing accumulated drag vs. streamwise position.
        
        Returns:
            Dict with drag distribution data and chart.
            
        Example:
            "Show drag distribution" → analyze_drag_distribution()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        return self.extended.drag_distribution(proxy_name=self._get_data_source())
    
    def analyze_lift_distribution(self) -> dict:
        """
        Analyze how lift is distributed along the span.
        
        Creates a chart showing lift distribution (like an elliptic loading diagram).
        
        Returns:
            Dict with lift distribution data and chart.
            
        Example:
            "Show lift distribution" → analyze_lift_distribution()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        return self.extended.lift_distribution(proxy_name=self._get_data_source())
    
    def describe_data(self) -> dict:
        """
        Describe the loaded CFD dataset.
        
        Returns information about bounds, fields, mesh statistics.
        
        Returns:
            Dict with dataset characterization.
            
        Example:
            "What data is loaded?" → describe_data()
            "Describe the dataset" → describe_data()
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        return self.extended.characterize_dataset(proxy_name=self._get_data_source())
    
    def show_field_histogram(self, field_name: str = "pressure", num_bins: int = 50) -> dict:
        """
        Show histogram of a field's value distribution.
        
        Args:
            field_name: Field to analyze (pressure, velocity, etc.)
            num_bins: Number of histogram bins
        
        Returns:
            Dict with histogram data and statistics.
            
        Example:
            "Show pressure histogram" → show_field_histogram("pressure")
        """
        if self.extended is None:
            return {"error": "Extended MCP not configured"}
        
        return self.extended.create_histogram(
            field_name=field_name,
            num_bins=num_bins,
            proxy_name=self._get_data_source()
        )
