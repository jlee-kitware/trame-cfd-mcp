"""
ParaView LLM - CFD Visualization Tools for LLM Assistants

TWO APPROACHES:

1. CFDToolsMCP (NEW - Recommended)
   Composable tools for trame_llm. LLM chains query → action tools.
   
   from paraview_llm import ExtendedParaViewMCP, CFDToolsMCP
   
   extended_mcp = ExtendedParaViewMCP(paraview_mcp)
   cfd_tools = CFDToolsMCP(app, extended_mcp)
   llm_client.register_mcp(cfd_tools)

2. CFDAssistant (Legacy)
   Hardcoded workflows with intent classification.
   
   from paraview_llm import CFDAssistant, ExtendedParaViewMCP
   assistant = CFDAssistant(extended_mcp, base_mcp, data_source)
   result = assistant.query("Show me the vortices")
"""

from .extended_mcp import ExtendedParaViewMCP
from .cfd_tools import CFDToolsMCP

# Legacy approach - still works but CFDToolsMCP is preferred
from .cfd_assistant import (
    CFDAssistant,
    WorkflowExecutor,
    Intent,
    IntentType,
    WORKFLOWS,
)

# For testing without LLM
from .mock_llm import MockLLMExecutor

__all__ = [
    # New API (recommended)
    "ExtendedParaViewMCP",
    "CFDToolsMCP",
    
    # Legacy API
    "CFDAssistant",
    "WorkflowExecutor",
    "Intent", 
    "IntentType",
    "WORKFLOWS",
    
    # Testing
    "MockLLMExecutor",
]

__version__ = "0.3.0"
