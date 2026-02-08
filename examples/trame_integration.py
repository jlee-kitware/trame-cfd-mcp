"""
Example: Integration with trame-llm

Shows how to use paraview-llm with trame-llm's ParaViewMCP.

This example won't run standalone (needs trame app), but shows the pattern.
"""

# Real usage pattern:
USAGE_EXAMPLE = """
from trame.app import Lite
from trame_llm.paraview import ParaViewMCP
from paraview_llm import ExtendedParaViewMCP, CFDAssistant

# Setup trame app
app = Lite()

# Create ParaViewMCP (from trame-llm)
base_mcp = ParaViewMCP(app)

# Wrap with extended CFD tools
extended_mcp = ExtendedParaViewMCP(base_mcp)

# Create CFD assistant (safe tiered architecture)
# LLM only classifies intent - all execution is deterministic
assistant = CFDAssistant(
    extended_mcp=extended_mcp,
    base_mcp=base_mcp,
    data_source="MyData.vtk"
)

# Handle user query
def handle_query(user_message: str):
    result = assistant.query(user_message)
    
    intent = result['intent'].type.value
    workflow = result['result'].get('workflow', 'N/A')
    success = result['success']
    
    print(f"Intent: {intent}")
    print(f"Workflow: {workflow}")
    print(f"Success: {success}")
    
    if success:
        print(f"Summary: {result.get('summary', 'Done')}")
    else:
        print(f"Error: {result['result'].get('error', 'Unknown')}")

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
    print("Architecture (Safe Tiered Design)")
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
│  │                                                    │  │
│  │  Tier 1: Intent Classification (LLM)              │  │
│  │    - Single LLM call to classify user query       │  │
│  │    - Returns: IntentType.VISUALIZE_VORTICES       │  │
│  │                                                    │  │
│  │  Tier 2: Workflow Selection (deterministic)       │  │
│  │    - Maps intent to predefined workflow           │  │
│  │    - No LLM involved                              │  │
│  │                                                    │  │
│  │  Tier 3: Execution (deterministic)                │  │
│  │    - Runs workflow steps in sequence              │  │
│  │    - No LLM involved                              │  │
│  │                                                    │  │
│  │  Tier 4: Result Summary (LLM, optional)           │  │
│  │    - Single LLM call to explain results           │  │
│  └────────────────────────────────────────────────────┘  │
│                      │                                   │
│                      ▼                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │            ExtendedParaViewMCP                     │  │
│  │  CFD tools: vortex detection, wake analysis,      │  │
│  │  forces, histograms, streamlines, etc.            │  │
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

KEY PRINCIPLE: LLM never makes execution decisions.
  - ~400 tokens per query (vs 1M tokens with tool-loop)
  - Deterministic, reproducible results
  - 13/13 workflows tested and passing
""")


if __name__ == "__main__":
    main()
