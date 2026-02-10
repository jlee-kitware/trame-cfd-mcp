"""
ParaView LLM - CFD Analysis Tools for LLM Assistants

Usage (workflow mode - recommended):
    from paraview_llm import WorkflowMCP
    from trame_llm.paraview import ParaViewMCP
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    llm_client.register_mcp(workflow_mcp)

Usage (fine-grained mode):
    from paraview_llm import ExtendedParaViewMCP
    from trame_llm.paraview import ParaViewMCP
    
    base_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(base_mcp)
    llm_client.register_mcp(extended_mcp)
"""

from .extended_mcp import ExtendedParaViewMCP
from .workflow_mcp import WorkflowMCP
from .workflows import CFDWorkflows
from .cost_tracker import TrackedLLMClient, UsageStats

__all__ = ["ExtendedParaViewMCP", "WorkflowMCP", "CFDWorkflows", "TrackedLLMClient", "UsageStats"]
__version__ = "0.7.0"
