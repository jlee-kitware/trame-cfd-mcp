"""
ParaView LLM - CFD Analysis Tools for LLM Assistants

RECOMMENDED: CFDAnalysisMCP - Pure analysis tools
   
Analysis tools compute fields and find values.
Base ParaView tools handle visualization.

    from paraview_llm import ExtendedParaViewMCP, CFDAnalysisMCP
    
    extended_mcp = ExtendedParaViewMCP(paraview_mcp)
    analysis_mcp = CFDAnalysisMCP(app, extended_mcp)
    llm_client.register_mcp(paraview_mcp)   # Base: Contour, StreamTracer, etc.
    llm_client.register_mcp(analysis_mcp)   # Analysis: compute_vortex_field, etc.

Example workflow:
    "Show vortices"
    → compute_vortex_field("q_criterion")  # Analysis: adds Q array
    → suggest_threshold("Q")               # Analysis: returns threshold
    → [ParaView Contour]                   # Base: visualization

LEGACY: CFDToolsMCP, CFDAssistant - still available
"""

from .extended_mcp import ExtendedParaViewMCP
from .cfd_analysis import CFDAnalysisMCP

# Legacy - composable tools with some visualization
from .cfd_tools import CFDToolsMCP

# Legacy - hardcoded workflows
from .cfd_assistant import (
    CFDAssistant,
    WorkflowExecutor,
    Intent,
    IntentType,
    WORKFLOWS,
)

from .mock_llm import MockLLMExecutor

__all__ = [
    # Recommended
    "ExtendedParaViewMCP",
    "CFDAnalysisMCP",
    
    # Legacy
    "CFDToolsMCP",
    "CFDAssistant",
    "WorkflowExecutor",
    "Intent", 
    "IntentType",
    "WORKFLOWS",
    "MockLLMExecutor",
]

__version__ = "0.4.0"
