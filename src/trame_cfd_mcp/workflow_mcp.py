"""
Workflow-based MCP for CFD visualization.

Exposes high-level workflow tools plus refinement tools for tweaking results.
LLM does intent matching, workflows execute deterministically.
Ontology provides domain knowledge for explanations.
"""

import json
import os
from paraview import simple
from .cfd_analysis import CFDAnalysis
from .workflows import CFDWorkflows


# Load ontology at module level
_ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), "ontology.json")
with open(_ONTOLOGY_PATH) as f:
    CFD_ONTOLOGY = json.load(f)


class WorkflowMCP:
    """MCP with workflow tools and refinement capabilities."""
    
    def __init__(self, base_mcp):
        """
        Initialize workflow MCP.
        
        Args:
            base_mcp: ParaViewMCP instance from trame-llm
        """
        self._base_mcp = base_mcp
        self._analysis = CFDAnalysis()
        self._workflows = CFDWorkflows(
            self._analysis, 
            on_pipeline_changed=self._base_mcp.pipeline_changed
        )
        self._ontology = CFD_ONTOLOGY
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration (property for compatibility with LLMClient)."""
        return self.get_mcp()
    
    def list_data(self) -> dict:
        """
        List all loaded data sources and filters in the pipeline.
        
        Call this FIRST to see what data is available before analysis.
        
        Returns:
            Dict with:
            - readers: List of data sources (files loaded)
            - filters: List of filters created
            - active_source: Currently active proxy
        """
        result = self._analysis.list_data()
        result["tip"] = "Use proxy names from this list with refinement tools like update_representation()"
        return result
    
    def save_screenshot(
        self,
        filename: str,
        width: int = 1024,
        height: int = 768
    ) -> dict:
        """
        Save screenshot of the current view to a file.
        
        Args:
            filename: Output filename (e.g., "output/result.png")
            width: Image width in pixels (default: 1024)
            height: Image height in pixels (default: 768)
            
        Returns:
            Dict with filename and status
        """
        result = self._analysis.save_screenshot(filename, width, height)
        if "error" not in result:
            result["tip"] = "Screenshot saved. Use set_view() to change camera angle before saving another."
        return result
    
    def save_all_charts(
        self,
        prefix: str = "output/chart",
        width: int = 800,
        height: int = 600
    ) -> dict:
        """
        Save all pending chart views to files.
        
        Charts are created by workflows like show_boundary_layer, show_histogram,
        show_forces, etc. This saves all of them at once with sequential numbering.
        
        Args:
            prefix: Output filename prefix (e.g., "output/bl" -> bl_0.png, bl_1.png, ...)
            width: Image width in pixels (default: 800)
            height: Image height in pixels (default: 600)
            
        Returns:
            Dict with list of saved filenames and count
        """
        result = self._analysis.save_all_charts(prefix, width, height)
        if result.get("count", 0) > 0:
            result["tip"] = f"Saved {result['count']} charts. Charts are cleared after saving."
        return result
    
    def set_view(self, direction: str = "+x") -> dict:
        """
        Set camera view direction.
        
        Args:
            direction: "+x", "-x", "+y", "-y", "+z", "-z", or "iso"
            
        Returns:
            Dict with view info
            
        Tip:
            Use before save_screenshot() to capture different angles.
        """
        result = self._analysis.set_view(direction)
        if "error" not in result:
            result["tip"] = "Camera set. Call save_screenshot() to capture this view."
        return result
    
    def update_display_property(
        self,
        property_name: str,
        value,
        proxy_name: str = None
    ) -> dict:
        """
        Set display/representation property like opacity, interpolation, or line width.
        
        These are visual properties on how the data is displayed, NOT filter properties.
        Use list_properties() for filter properties, this is for display properties.
        
        Args:
            property_name: One of:
                - "Opacity": 0.0 (transparent) to 1.0 (opaque)
                - "Interpolation": "Flat", "Gouraud", or "PBR"
                - "LineWidth": line thickness (default 1.0)
                - "PointSize": point size for Points representation (default 2.0)
                - "Metallic": 0.0-1.0 for PBR materials
                - "Roughness": 0.0-1.0 for PBR materials
            value: The value to set (number or string depending on property)
            proxy_name: Proxy to modify, or active source if None
            
        Returns:
            Dict with proxy name, property, and value set
        """
        # Map common names to ParaView property names
        property_map = {
            "opacity": "Opacity",
            "linewidth": "LineWidth",
            "line_width": "LineWidth",
            "pointsize": "PointSize",
            "point_size": "PointSize",
            "interpolation": "Interpolation",
            "metallic": "Metallic",
            "roughness": "Roughness",
            "pbr": "Interpolation",  # Shortcut: "pbr" -> set Interpolation to PBR
        }
        
        # Normalize property name
        prop_key = property_name.lower().replace(" ", "")
        actual_prop = property_map.get(prop_key, property_name)
        
        # Handle "pbr" shortcut - set value to "PBR" if using the shortcut
        if prop_key == "pbr":
            value = "PBR"
        
        # Get proxy
        if proxy_name:
            proxy = simple.FindSource(proxy_name)
        else:
            proxy = simple.GetActiveSource()
        
        if proxy is None:
            return {"error": f"Could not find proxy '{proxy_name}'" if proxy_name else "No active source"}
        
        # Get representation
        view = simple.GetActiveView()
        rep = simple.GetRepresentation(proxy, view)
        
        if rep is None:
            return {"error": f"No representation found for '{proxy_name or 'active source'}'"}
        
        # Check if property exists on representation
        if not hasattr(rep, actual_prop):
            available = [p for p in dir(rep) if not p.startswith('_') and p[0].isupper()]
            return {
                "error": f"Property '{actual_prop}' not found on representation",
                "hint": "Common display properties: Opacity, LineWidth, PointSize",
                "tip": "Use update_representation() to change type (Wireframe, Surface, etc.)"
            }
        
        try:
            setattr(rep, actual_prop, value)
            simple.Render(view)
            
            # Get proxy name for return
            name = proxy_name
            if not name:
                for n, p in simple.GetSources().items():
                    if p == proxy:
                        name = n[0]
                        break
            
            return {
                "name": name,
                "property": actual_prop,
                "value": value,
                "tip": "Display property set. Opacity=0 is invisible, Opacity=1 is fully opaque."
            }
        except Exception as e:
            return {"error": str(e)}
    
    def save_state(self, filename: str) -> dict:
        """
        Save ParaView state for reproducibility.
        
        Saves complete pipeline state that can be loaded in ParaView GUI
        or via LoadState() in Python.
        
        Args:
            filename: Output filename (.pvsm for XML, .py for Python script)
            
        Returns:
            Dict with filename and status
        """
        simple.SaveState(filename)
        return {
            "status": "saved",
            "filename": filename,
            "tip": "Load with File > Load State in ParaView GUI, or simple.LoadState() in Python"
        }
    
    def get_ontology(self) -> dict:
        """
        Get CFD domain knowledge for interpreting results.
        
        Returns ontology containing:
        - flow_features: What each visualization type means
        - causal_relationships: What causes drag/lift changes
        - analysis_recommendations: Which tools to use for different questions
        
        Use this to explain visualizations and answer "why" questions.
        """
        return self._ontology
    
    def delete_filter(self, proxy_name: str) -> dict:
        """
        Delete a filter from the pipeline.
        
        Use this to clean up unwanted visualizations and free resources.
        
        Args:
            proxy_name: Name of the filter to delete (from list_data)
            
        Returns:
            Dict with status
        """
        try:
            proxy = simple.FindSource(proxy_name)
            if proxy is None:
                return {"error": f"Filter '{proxy_name}' not found"}
            
            simple.Delete(proxy)
            self._base_mcp.pipeline_changed()
            
            return {
                "status": "deleted",
                "proxy_name": proxy_name,
            }
        except Exception as e:
            return {"error": str(e)}
    
    def clear_all_filters(self) -> dict:
        """
        Delete all filters, keeping only the original data sources.
        
        Use this to reset the pipeline and free OpenGL resources.
        
        Returns:
            Dict with list of deleted filters
        """
        deleted = []
        try:
            # Get all sources
            sources = dict(simple.GetSources())
            
            # Find readers (data sources) vs filters
            readers = set()
            for name, proxy in sources.items():
                proxy_type = proxy.GetXMLName()
                if "Reader" in proxy_type or "Source" in proxy_type:
                    readers.add(name)
            
            # Delete filters (non-readers) in reverse dependency order
            for name, proxy in sources.items():
                if name not in readers:
                    try:
                        simple.Delete(proxy)
                        deleted.append(name[0])
                    except:
                        pass
            
            self._base_mcp.pipeline_changed()
            
            return {
                "status": "cleared",
                "deleted": deleted,
                "remaining": [n[0] for n in readers],
            }
        except Exception as e:
            return {"error": str(e)}
    
    def hide_all_scalar_bars(self) -> dict:
        """
        Hide all scalar bars (color legends) to reduce OpenGL texture usage.
        
        Use this if you see texture warnings or rendering issues.
        
        Returns:
            Dict with count of hidden bars
        """
        view = simple.GetActiveView()
        count = 0
        
        for name, proxy in simple.GetSources().items():
            rep = simple.GetRepresentation(proxy=proxy, view=view)
            if rep:
                try:
                    rep.SetScalarBarVisibility(view, False)
                    count += 1
                except:
                    pass
        
        simple.Render(view)
        return {
            "status": "hidden",
            "count": count,
            "tip": "Scalar bars hidden. Use update_color to show a specific one."
        }
    
    def get_mcp(self) -> dict:
        """Return MCP declaration with workflow and refinement tools."""
        return {
            "name": "cfd_visualization",
            "instructions": """
You are a CFD visualization and analysis assistant. You create visualizations AND explain what they mean.

ALWAYS call list_data() first to see what data is loaded.

== WORKFLOW PATTERN ==

1. Create visualization with show_* tools (they return proxy_name and parameters)
2. If user wants refinement, use the proxy_name with refinement tools
3. Use get_ontology() to get domain knowledge for explanations
4. Save with save_screenshot()

== VISUALIZATION TOOLS (use these first) ==

- show_vortices(method="q_criterion") - Show vortex structures
- show_streamlines() - Show flow streamlines in wake region  
- show_slice(location="wake") - Show slice through data
- show_histogram(field="p") - Show field distribution chart
- show_forces() - Show force distribution chart
- show_boundary_layer(x_location=0.5) - Show boundary layer profile
- show_flow_topology() - Show vortex core lines

== REFINEMENT TOOLS (use after show_* to tweak) ==

After a workflow runs, it returns proxy_name and parameters. Use these to refine:

- update_representation(representation_type, proxy_name) 
  → Change to "Wireframe", "Surface", "Points", "Surface With Edges"
  
- update_color(proxy_name, field_name) 
  → Change coloring to different field (e.g., "pressure", "Velocity")
  
- update_list_property(property_name, property_value, proxy_name)
  → Adjust thresholds: update_list_property("Isosurfaces", [new_values], proxy_name)
  → Lower threshold = more structures, higher = fewer
  
- update_display_property(property_name, value, proxy_name)
  → Set Opacity (0.0=transparent, 1.0=opaque), LineWidth, PointSize
  → These are DISPLAY properties, not filter properties
  
- show_or_hide(action, proxy_name)
  → action="hide" or "show" to toggle visibility
  
- list_properties(proxy_name)
  → See all adjustable properties on a filter

== REFINEMENT EXAMPLES ==

User: "Show vortices" → call show_vortices() → returns {proxy_name: "Contour1", threshold: 28.0, ...}
User: "Make them wireframe" → call update_representation("Wireframe", "Contour1")
User: "Show more structures" → call update_list_property("Isosurfaces", [14.0], "Contour1")
User: "Color by pressure" → call update_color("Contour1", "p")
User: "Make them semi-transparent" → call update_display_property("Opacity", 0.5, "Contour1")

== DISCOVERY TOOLS ==

- list_data() - See loaded data sources and filters with proxy names
- get_fields() - List available fields with ranges
- analyze_data() - Get dataset info and recommendations
- list_properties(proxy_name) - See adjustable properties

== EXPLANATION GUIDANCE ==

When explaining visualizations, use the ontology to provide:
- What the visualization method means (e.g., Q > 0 indicates vortex cores)
- What the specific results show (threshold value, location, etc.)
- Design relevance (what this means for aerodynamic performance)
""",
            "tools": [
                # Discovery
                self.list_data,
                self._workflows.get_fields,
                self._workflows.analyze_data,
                
                # Visualization workflows
                self._workflows.show_vortices,
                self._workflows.show_streamlines,
                self._workflows.show_slice,
                self._workflows.show_histogram,
                self._workflows.show_forces,
                self._workflows.show_boundary_layer,
                self._workflows.show_boundary_layer_context,
                self._workflows.show_flow_topology,
                
                # Refinement tools (from base MCP)
                self._base_mcp.reset_camera,
                self._base_mcp.focus_on,
                self._base_mcp.update_representation,
                self._base_mcp.update_color,
                self._base_mcp.update_list_property,
                self._base_mcp.show_or_hide,
                self._base_mcp.list_properties,
                self.update_display_property,
                
                # Knowledge and utilities
                self.get_ontology,
                self.save_screenshot,
                self.save_all_charts,
                self.save_state,
                self.set_view,
                self.delete_filter,
                self.clear_all_filters,
                self.hide_all_scalar_bars,
            ],
            "resources": {},
        }
