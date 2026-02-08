"""
ParaView LLM - Safe CFD Visualization Assistant

ARCHITECTURE:
    LLM does: Intent classification, result summarization
    LLM does NOT: Tool selection, execution decisions, retry logic

Usage:
    from paraview_llm import CFDAssistant, ExtendedParaViewMCP
    
    assistant = CFDAssistant(extended_mcp, base_mcp, data_source)
    result = assistant.query("Show me the vortices")
"""

from .extended_mcp import ExtendedParaViewMCP
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
    # Main API
    "CFDAssistant",
    "ExtendedParaViewMCP",
    
    # For advanced usage
    "WorkflowExecutor",
    "Intent", 
    "IntentType",
    "WORKFLOWS",
    
    # Testing
    "MockLLMExecutor",
]

__version__ = "0.2.0"
