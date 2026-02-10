# -*- coding: utf-8 -*-
"""
Workflow-based MCP for CFD visualization.

Exposes only high-level workflow tools - LLM does intent matching,
workflows execute deterministically.
"""

from paraview import simple
from .extended_mcp import ExtendedParaViewMCP
from .workflows import CFDWorkflows


class WorkflowMCP:
    """MCP with high-level workflow tools only."""
    
    def __init__(self, base_mcp):
        """
        Initialize workflow MCP.
        
        Args:
            base_mcp: ParaViewMCP instance from trame-llm
        """
        self._base_mcp = base_mcp
        self._extended = ExtendedParaViewMCP(base_mcp)
        self._workflows = CFDWorkflows(self._extended)
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration (property for compatibility with LLMClient)."""
        return self.get_mcp()
    
    def list_data(self) -> dict:
        """
        List all loaded data sources.
        
        Call this first to see what data is available.
        
        Returns:
            Dict with 'readers' (data sources) and 'filters' lists
        """
        return self._extended.list_data()
    
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
        return self._extended.save_screenshot(filename, width, height)
    
    def set_view(self, direction: str = "+x") -> dict:
        """
        Set camera view direction.
        
        Args:
            direction: "+x", "-x", "+y", "-y", "+z", "-z", or "iso"
            
        Returns:
            Dict with view info
        """
        return self._extended.set_view(direction)
    
    def get_mcp(self) -> dict:
        """Return MCP declaration with workflow tools only."""
        return {
            "name": "cfd_visualization",
            "instructions": """
You are a CFD visualization assistant. You have high-level tools to create visualizations.

ALWAYS call list_data() first to see what data is loaded.

DISCOVERY:
- list_data() - See loaded data sources
- get_fields() - List available fields with ranges
- analyze_data() - Get dataset info and recommendations

VISUALIZATION TOOLS:
- show_vortices(method="q_criterion") - Show vortex structures  
- show_streamlines() - Show flow streamlines in wake region
- show_slice(location="wake", normal="x") - Show slice through data
- show_histogram(field="p") - Show field distribution chart
- show_forces() - Show force distribution chart

UTILITIES:
- save_screenshot(filename="output/result.png") - Save current view
- set_view(direction="+x") - Set camera angle

After creating a visualization, call save_screenshot() to save the result.
""",
            "tools": [
                self.list_data,
                self._workflows.get_fields,
                self._workflows.show_vortices,
                self._workflows.show_streamlines,
                self._workflows.show_slice,
                self._workflows.show_histogram,
                self._workflows.show_forces,
                self._workflows.analyze_data,
                self.save_screenshot,
                self.set_view,
            ],
            "resources": {},
        }
