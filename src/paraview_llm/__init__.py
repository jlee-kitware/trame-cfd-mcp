"""
ParaView LLM

CFD post-processing with natural language.

Modes:
- Mock: Deterministic tool sequences for testing (no LLM calls)
- Single-shot: One LLM call to generate plan, then local execution

Components:
- ExtendedParaViewMCP: CFD analysis and visualization tools
- Orchestrator: Enriches queries with domain knowledge from ontology
- MockLLMExecutor: Deterministic test sequences
- SingleShotExecutor: Single LLM call execution (requires openai)
"""

__version__ = "0.1.0"

from paraview_llm.extended_mcp import ExtendedParaViewMCP
from paraview_llm.orchestrator import Orchestrator
from paraview_llm.mock_llm import MockLLMExecutor, MOCK_RESPONSES

__all__ = [
    "ExtendedParaViewMCP",
    "Orchestrator",
    "MockLLMExecutor",
    "MOCK_RESPONSES",
]

# Optional: SingleShotExecutor (requires openai package)
try:
    from paraview_llm.single_shot import SingleShotExecutor
    __all__.append("SingleShotExecutor")
except ImportError:
    pass  # openai not installed
