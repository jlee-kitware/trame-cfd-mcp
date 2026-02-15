"""
trame-cfd-mcp - CFD Workflow Tools for ParaView via MCP

Extends trame-llm's ParaViewMCP with CFD-specific visualization workflows.

Usage:
    from trame_cfd_mcp import WorkflowMCP, TrackedLLMClient
    from trame_llm.paraview import ParaViewMCP
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    
    llm = TrackedLLMClient(max_iteractions=15)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    await llm.process_prompt("Show me the vortices and explain what I see")
    llm.print_report()  # Token usage and cost
"""

from .cfd_analysis import CFDAnalysis
from .workflow_mcp import WorkflowMCP
from .workflows import CFDWorkflows
from .cost_tracker import TrackedLLMClient, UsageStats
from .catalyst_live import CatalystLiveSource, CatalystLiveMCP

__all__ = [
    "CFDAnalysis", 
    "WorkflowMCP", 
    "CFDWorkflows", 
    "TrackedLLMClient", 
    "UsageStats",
    "CatalystLiveSource",
    "CatalystLiveMCP",
]
__version__ = "0.1.0"
