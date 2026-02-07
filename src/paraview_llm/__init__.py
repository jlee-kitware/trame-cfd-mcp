"""
ParaView LLM

CFD post-processing with natural language.

Architecture:
- CFDAssistant: LLM-based tool composition with semantic reasoning (OpenAI/Anthropic)
- PlanningOntology: Triple-based domain knowledge with STRIPS-style planning
- ExtendedParaViewMCP: CFD analysis and visualization tools
- Mock: Deterministic sequences for testing (no LLM calls)

Components:
- ExtendedParaViewMCP: CFD analysis and visualization tools (vortex detection, force computation, etc.)
- PlanningOntology: Semantic reasoning - queries, inference, planning
- CFDAssistant: Agent-based assistant with tool calling and conversation history
- MockLLMExecutor: Deterministic test sequences (no LLM needed)
"""

__version__ = "0.3.0"

from paraview_llm.extended_mcp import ExtendedParaViewMCP
from paraview_llm.mock_llm import MockLLMExecutor, MOCK_RESPONSES

__all__ = [
    "ExtendedParaViewMCP",
    "MockLLMExecutor",
    "MOCK_RESPONSES",
]

# Planning ontology - triple-based domain knowledge with semantic reasoning
try:
    from paraview_llm.ontology_planning import PlanningOntology
    from paraview_llm.ontology_triples import CFDOntology
    __all__.extend(["PlanningOntology", "CFDOntology"])
except ImportError:
    pass

# CFDAssistant - LLM-based tool composition (requires openai or anthropic)
try:
    from paraview_llm.assistant import (
        create_assistant,
        OpenAICFDAssistant,
        ClaudeCFDAssistant,
        CFDAssistant,
    )
    __all__.extend(["create_assistant", "OpenAICFDAssistant", "ClaudeCFDAssistant", "CFDAssistant"])
except ImportError:
    pass  # openai/anthropic not installed
