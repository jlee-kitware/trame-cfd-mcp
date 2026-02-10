"""
ParaView LLM - CFD Analysis Tools for LLM Assistants

Usage:
    from paraview_llm import WorkflowMCP, TrackedLLMClient
    from trame_llm.paraview import ParaViewMCP
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    
    llm = TrackedLLMClient(max_iteractions=15)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    await llm.process_prompt("Show me the vortices and explain what I see")
    llm.print_report()  # Token usage and cost
"""

from .extended_mcp import ExtendedParaViewMCP
from .workflow_mcp import WorkflowMCP
from .workflows import CFDWorkflows
from .cost_tracker import TrackedLLMClient, UsageStats

__all__ = ["ExtendedParaViewMCP", "WorkflowMCP", "CFDWorkflows", "TrackedLLMClient", "UsageStats"]
__version__ = "0.7.0"
