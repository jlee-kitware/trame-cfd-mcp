"""
Example: Integration with trame-llm

Shows how to use paraview-llm with trame-llm's ParaViewMCP.

This example won't run standalone (needs trame app), but shows the pattern.
"""

# Real usage pattern:
USAGE_EXAMPLE = """
from trame.app import Lite
from trame_llm.paraview import ParaViewMCP
from paraview_llm import ExtendedParaViewMCP
from paraview_llm.assistant import create_assistant

# Setup trame app
app = Lite()

# Create ParaViewMCP (from trame-llm)
base_mcp = ParaViewMCP(app)

# Wrap with extended CFD tools
extended_mcp = ExtendedParaViewMCP(base_mcp)

# Create LLM-based assistant with semantic reasoning
assistant = create_assistant(
    base_mcp=base_mcp,
    extended_mcp=extended_mcp,
    provider="openai",  # or "claude"
    data_source="MyData.vtk"
)

# Handle user query
def handle_query(user_message: str):
    result = assistant.execute(user_message)
    
    print(f"Response: {result['response']}")
    
    for tool in result.get('tools', []):
        tool_name = tool['tool']
        status = "✓" if 'error' not in tool.get('result', {}) else "✗"
        print(f"  {status} {tool_name}")

# Use it
# handle_query("show me the vortices using Q-criterion")
"""


def main():
    """Show the trame integration pattern."""
    print("=" * 60)
    print("Trame Integration Pattern")
    print("=" * 60)
    print(USAGE_EXAMPLE)
    
    print("=" * 60)
    print("Architecture")
    print("=" * 60)
    print("""
┌──────────────────────────────────────────────────────────┐
│                      Trame App                           │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  User: "show me the vortices"                            │
│                      │                                   │
│                      ▼                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │              CFDAssistant                          │  │
│  │  1. Uses PlanningOntology for semantic reasoning   │  │
│  │  2. LLM selects and calls tools via function calls │  │
│  │  3. Can generate and execute plans automatically   │  │
│  └────────────────────────────────────────────────────┘  │
│                      │                                   │
│                      ▼                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │            ExtendedParaViewMCP                     │  │
│  │  CFD tools: vortex detection, wake analysis, etc.  │  │
│  └────────────────────────────────────────────────────┘  │
│                      │                                   │
│                      ▼                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │          ParaViewMCP (from trame-llm)              │  │
│  │  Base tools: slice, contour, render, etc.          │  │
│  └────────────────────────────────────────────────────┘  │
│                      │                                   │
│                      ▼                                   │
│                   ParaView                               │
│                                                          │
└──────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()
