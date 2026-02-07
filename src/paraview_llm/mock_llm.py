"""
Mock LLM for deterministic testing without API calls.

PURPOSE:
    The mock defines ONE valid tool sequence for each query, providing a
    reproducible baseline for regression testing. It is NOT "the correct answer" -
    many valid approaches exist for each visualization task.

MOCK vs REAL LLM:
    - Mock: Tests that tools work correctly (deterministic, fast, free)
    - Real LLM: Tests LLM reasoning + tool selection (variable, slow, costs money)

    The real LLM may choose different valid approaches:
    - Shear layer: vorticity isosurface OR velocity slice OR velocity gradient
    - Vortices: Q-criterion OR lambda2 OR swirling strength
    - Flow pattern: streamlines from stagnation OR from inlet OR seeded grid

    All can be "correct" - the mock just guarantees reproducible known-good results.

THRESHOLD RULES (when auto_threshold=True):
    - q_criterion: percentile of positive Q values (default 50%)
    - vorticity: percentile of positive |ω| values (default 50%)
    - swirling_strength: percentile of positive values (default 50%)
    - lambda2: 0.01 × min(λ2) (small negative, near vortex boundary)
    - helicity: 0.7 fixed (|Hn| > 0.7 = strongly helical)
"""

# Expected tool sequences for each test query
# Format: query_key -> list of (tool_name, kwargs) tuples
MOCK_RESPONSES = {
    "shear_layer": [
        # Shear layer = high velocity gradient region
        # Vorticity isosurface is best - directly shows where rotation (shear) occurs
        # Alternative valid approaches: velocity slice, velocity gradient magnitude
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "vorticity", "percentile": 70, "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "stagnation": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("find_minimum", {"field": "velocity", "proxy_name": "{data_source}", "exclude_boundaries": True}),
        # Use base tools for slice: create → set origin → set normal → color
        ("base:create", {"proxy_name": "Slice", "input_proxy": "{data_source}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Origin", "sub_property_value": "{min_location}", "proxy_name": "{last_created}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Normal", "sub_property_value": [1, 0, 0], "proxy_name": "{last_created}"}),
        ("base:update_color", {"proxy_name": "{last_created}", "field_name": "Velocity"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
    ],
    
    "flow_pattern": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("find_minimum", {"field": "velocity", "proxy_name": "{data_source}", "exclude_boundaries": True}),
        ("create_streamlines", {"center": "{min_location}", "radius": 0.5, "num_points": 50, "color_field": "Velocity", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "pressure": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("get_geometry_info", {"proxy_name": "{data_source}"}),
        ("base:create", {"proxy_name": "Slice", "input_proxy": "{data_source}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Origin", "sub_property_value": "{center}", "proxy_name": "{last_created}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Normal", "sub_property_value": [0, 1, 0], "proxy_name": "{last_created}"}),
        ("base:update_color", {"proxy_name": "{last_created}", "field_name": "p"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
    ],
    
    "velocity_stats": [
        # Returns histogram data for velocity distribution (data only, no visual)
        ("field_histogram", {"field": "velocity", "num_bins": 20, "proxy_name": "{data_source}"}),
    ],
    
    "velocity_distribution": [
        # Creates histogram chart in ParaView (visual)
        ("create_histogram_chart", {"field": "velocity", "num_bins": 20, "proxy_name": "{data_source}"}),
    ],
    
    "forces": [
        # Compute drag/lift forces and coefficients
        ("compute_forces", {"proxy_name": "{data_source}"}),
    ],
    
    "drag_distribution": [
        # Accumulated drag along streamwise direction (auto-detected)
        ("create_force_distribution_chart", {"force_axis": "drag", "distribution_axis": "streamwise", "num_bins": 40, "proxy_name": "{data_source}"}),
    ],
    
    "lift_distribution": [
        # Spanwise lift distribution (auto-detected span direction)
        ("create_force_distribution_chart", {"force_axis": "lift", "distribution_axis": "span", "num_bins": 50, "proxy_name": "{data_source}"}),
    ],
    
    "max_velocity": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("find_maximum", {"field": "velocity", "proxy_name": "{data_source}"}),
        ("base:create", {"proxy_name": "Slice", "input_proxy": "{data_source}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Origin", "sub_property_value": "{max_location}", "proxy_name": "{last_created}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Normal", "sub_property_value": [1, 0, 0], "proxy_name": "{last_created}"}),
        ("base:update_color", {"proxy_name": "{last_created}", "field_name": "Velocity"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
    ],
    
    "wake_slice": [
        # Slice through wake region (detected by velocity deficit)
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("detect_wake_region", {"proxy_name": "{data_source}"}),
        ("base:create", {"proxy_name": "Slice", "input_proxy": "{data_source}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Origin", "sub_property_value": "{wake_centroid}", "proxy_name": "{last_created}"}),
        ("base:update_sub_property", {"property_name": "SliceType", "sub_property_name": "Normal", "sub_property_value": [1, 0, 0], "proxy_name": "{last_created}"}),
        ("base:update_color", {"proxy_name": "{last_created}", "field_name": "Velocity"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_view", {"direction": "+x", "proxy_name": "{last_created}"}),
    ],
    
    "wake_streamlines": [
        # Streamlines seeded in wake region
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("detect_wake_region", {"proxy_name": "{data_source}"}),
        ("create_streamlines", {"center": "{wake_centroid}", "radius": 0.15, "num_points": 30, "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],

    "vortices_q": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "q_criterion", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "vortices_lambda2": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "lambda2", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "vortices_swirl": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "swirling_strength", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "vortices_helicity": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "helicity", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    
    "characterize": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("field_statistics", {"field": "velocity", "proxy_name": "{data_source}"}),
        ("find_minimum", {"field": "velocity", "proxy_name": "{data_source}", "exclude_boundaries": True}),
        ("find_maximum", {"field": "velocity", "proxy_name": "{data_source}"}),
        ("find_high_gradient", {"field": "velocity", "proxy_name": "{data_source}"}),
        ("create_vortex_isosurface", {"method": "q_criterion", "proxy_name": "{data_source}"}),
        ("create_streamlines", {"center": "{min_location}", "radius": 0.3, "num_points": 30, "color_field": "Velocity", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
}


class MockLLMExecutor:
    """
    Executes mock tool sequences without LLM calls.
    
    Substitutes placeholders like {data_source}, {min_location}, etc.
    with actual values from tool results.
    """
    
    def __init__(self, mcp, data_source: str):
        self.mcp = mcp
        self.data_source = data_source
        # Only static values - dynamic values added by tool results
        self.context = {
            "data_source": data_source,
        }
    
    def _substitute(self, value):
        """Substitute placeholders in a value."""
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            key = value[1:-1]
            if key in self.context:
                return self.context[key]
            # Keep placeholder - tool will fail with clear error
            return value
        return value
    
    def _substitute_kwargs(self, kwargs: dict) -> dict:
        """Substitute all placeholders in kwargs."""
        return {k: self._substitute(v) for k, v in kwargs.items()}
    
    def _update_context(self, tool_name: str, result: dict):
        """Update context based on tool result."""
        if not isinstance(result, dict):
            return
        
        # Special case: "name" -> "last_created" for chaining
        if "name" in result and result["name"] is not None:
            self.context["last_created"] = result["name"]
        elif "tube_name" in result and result["tube_name"] is not None:
            # create_streamlines returns tube_name (the visible result)
            self.context["last_created"] = result["tube_name"]
        elif "contour_name" in result and result["contour_name"] is not None:
            # create_vortex_isosurface returns contour_name
            self.context["last_created"] = result["contour_name"]
        elif "slice_name" in result and result["slice_name"] is not None:
            # Slice created via base tools may return slice_name
            self.context["last_created"] = result["slice_name"]
        elif tool_name.startswith("base:create") or tool_name == "create":
            # base:create sometimes returns name=None due to timing
            # Fall back to getting active source name
            from paraview import simple
            active = simple.GetActiveSource()
            if active:
                for name, proxy in simple.GetSources().items():
                    if proxy == active:
                        self.context["last_created"] = name[0]
                        break
        
        # Merge all result keys into context (except error and None values)
        for key, value in result.items():
            if key != "error" and value is not None:
                self.context[key] = value
    
    def execute(self, query_key: str) -> list:
        """
        Execute the mock tool sequence for a query.
        
        Returns list of (tool_name, kwargs, result) tuples.
        """
        if query_key not in MOCK_RESPONSES:
            return [("error", {}, {"error": f"Unknown query key: {query_key}"})]
        
        sequence = MOCK_RESPONSES[query_key]
        results = []
        
        for tool_name, kwargs in sequence:
            # Substitute placeholders
            resolved_kwargs = self._substitute_kwargs(kwargs)
            
            # Handle base: prefix for base MCP tools
            if tool_name.startswith("base:"):
                actual_tool_name = tool_name[5:]  # Remove "base:" prefix
                tool = getattr(self.mcp._base, actual_tool_name, None)
            else:
                # Get tool method from extended MCP first, then base
                tool = getattr(self.mcp, tool_name, None)
                if tool is None:
                    tool = getattr(self.mcp._base, tool_name, None)
            
            if tool is None:
                results.append((tool_name, resolved_kwargs, {"error": f"Tool not found: {tool_name}"}))
                continue
            
            # Execute tool
            try:
                result = tool(**resolved_kwargs)
            except Exception as e:
                result = {"error": str(e)}
            
            # Update context
            self._update_context(tool_name, result if isinstance(result, dict) else {})
            
            results.append((tool_name, resolved_kwargs, result))
        
        return results
