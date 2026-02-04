"""
Example: Integration with trame-llm

Shows how to use paraview-llm with trame-llm's ParaViewMCP.

This example won't run standalone (needs trame app), but shows the pattern.
"""

# Real usage would look like this:
"""
from trame.app import Lite
from trame_llm.paraview import ParaViewMCP
from paraview_llm import Orchestrator, TrameMCPAdapter

# Setup trame app
app = Lite()

# Create ParaViewMCP (from trame-llm)
paraview_mcp = ParaViewMCP(app)

# Wrap with our adapter
adapter = TrameMCPAdapter(paraview_mcp)

# Create orchestrator
orchestrator = Orchestrator(
    mcp_client=adapter,
    llm_provider="openai",  # matches trame-llm default
)

# Handle user query
async def handle_query(user_message: str):
    result = orchestrator.run(user_message)
    
    if result.get("success"):
        print(f"Reasoning: {result['reasoning']}")
        print(f"Executed {len(result['results'])} tool calls")
        for r in result['results']:
            if 'error' in r:
                print(f"  ERROR: {r['tool']}: {r['error']}")
            else:
                print(f"  OK: {r['tool']}: {r['result']}")
    else:
        print(f"Error: {result.get('error')}")
        if result.get('unresolved_fields'):
            print(f"Missing fields: {result['unresolved_fields']}")

# Use it
# await handle_query("characterize flowfield")
"""

# For standalone testing, we can mock the adapter
from paraview_llm.adapters.base import MCPAdapter


class MockTrameMCPAdapter(MCPAdapter):
    """Mock adapter for testing without ParaView"""
    
    def __init__(self):
        self.executed_calls = []
    
    def available_fields(self):
        return {
            "U": "POINTS",
            "p": "POINTS",
            "T": "POINTS",
        }
    
    def execute(self, tool_name: str, args: dict):
        self.executed_calls.append({"tool": tool_name, "args": args})
        return f"Mock executed: {tool_name}"
    
    def get_data_range(self, field_name: str):
        # Mock ranges
        ranges = {
            "U": (0.0, 100.0),
            "p": (-1000.0, 1000.0),
            "QCriterion": (0.0, 500.0),
        }
        return ranges.get(field_name, (0.0, 1.0))
    
    def get_bounds(self):
        return (-1.0, 1.0, -0.5, 0.5, -0.5, 0.5)


def main():
    from paraview_llm import Orchestrator
    
    # Create mock adapter
    adapter = MockTrameMCPAdapter()
    
    # Create orchestrator with mock LLM
    orchestrator = Orchestrator(
        mcp_client=adapter,
        llm_provider="mock"
    )
    
    print("=" * 60)
    print("Testing with mock trame-llm adapter")
    print("=" * 60)
    
    result = orchestrator.run("characterize flowfield")
    
    if result.get("success"):
        print(f"\nReasoning: {result['reasoning']}")
        print(f"\nExecuted {len(result['results'])} tool calls:")
        for r in result['results']:
            print(f"  {r['tool']}: {r['result']}")
        
        print(f"\nAdapter received these calls:")
        for call in adapter.executed_calls:
            print(f"  {call['tool']}({call['args']})")
    else:
        print(f"\nError: {result.get('error')}")


if __name__ == "__main__":
    main()
