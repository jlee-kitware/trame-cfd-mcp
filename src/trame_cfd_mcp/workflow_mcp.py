# -*- coding: utf-8 -*-
"""
Workflow-based MCP for CFD visualization.

Exposes only high-level workflow tools - LLM does intent matching,
workflows execute deterministically. Ontology provides domain knowledge
for explanations.
"""

import json
import os
from paraview import simple
from .extended_mcp import ExtendedParaViewMCP
from .workflows import CFDWorkflows


# Load ontology at module level
_ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), "ontology.json")
with open(_ONTOLOGY_PATH) as f:
    CFD_ONTOLOGY = json.load(f)


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
        self._ontology = CFD_ONTOLOGY
    
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
    
    def get_mcp(self) -> dict:
        """Return MCP declaration with workflow tools only."""
        
        # Format ontology for instructions
        flow_features = self._ontology.get("flow_features", {})
        feature_summary = []
        for name, info in flow_features.items():
            desc = info.get("description", "")
            feature_summary.append(f"- {name}: {desc}")
        
        return {
            "name": "cfd_visualization",
            "instructions": f"""
You are a CFD visualization and analysis assistant. You create visualizations AND explain what they mean.

ALWAYS call list_data() first to see what data is loaded.

WORKFLOW:
1. Create visualization with show_* tools
2. Use get_ontology() to get domain knowledge for explanation
3. Explain what the visualization shows using the ontology
4. Save with save_screenshot()

TOOLS:

Discovery:
- list_data() - See loaded data sources
- get_fields() - List available fields with ranges  
- analyze_data() - Get dataset info and recommendations

Visualization:
- show_vortices(method="q_criterion") - Show vortex structures
- show_streamlines() - Show flow streamlines in wake region
- show_slice(location="wake", normal="x") - Show slice through data
- show_histogram(field="p") - Show field distribution chart
- show_forces() - Show force distribution chart
- show_boundary_layer(x_location=0.5) - Show boundary layer velocity profile

Knowledge:
- get_ontology() - Get CFD domain knowledge for explanations

Utilities:
- save_screenshot(filename="output/result.png") - Save current view
- save_state(filename="output/state.pvsm") - Save pipeline for reproducibility
- set_view(direction="+x") - Set camera angle

EXPLANATION GUIDANCE:
When explaining visualizations, use the ontology to provide:
- What the visualization method means (e.g., Q > 0 indicates vortex cores)
- What the specific results show (threshold value, location, etc.)
- Design relevance (what this means for aerodynamic performance)
""",
            "tools": [
                self.list_data,
                self._workflows.get_fields,
                self._workflows.show_vortices,
                self._workflows.show_streamlines,
                self._workflows.show_slice,
                self._workflows.show_histogram,
                self._workflows.show_forces,
                self._workflows.show_boundary_layer,
                self._workflows.analyze_data,
                self.get_ontology,
                self.save_screenshot,
                self.save_state,
                self.set_view,
            ],
            "resources": {},
        }
