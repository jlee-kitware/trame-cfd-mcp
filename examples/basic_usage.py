"""
Example: Basic usage of the ParaView LLM Orchestrator

Run this example:
    python examples/basic_usage.py
"""

from paraview_llm import Orchestrator


class MockMCPClient:
    """Mock MCP client for testing without ParaView"""
    
    def available_fields(self):
        return {
            "U": "POINTS",
            "p": "POINTS", 
            "T": "POINTS",
        }


def main():
    # Initialize orchestrator with mock client (no execution)
    # Pass mcp_client=None to get tool calls without executing
    orchestrator = Orchestrator(mcp_client=None)
    
    # Manually inject mock field data for resolution
    mock_fields = {"U": "POINTS", "p": "POINTS", "T": "POINTS"}
    
    print("=" * 60)
    print("Query: 'characterize flowfield'")
    print("=" * 60)
    
    # Run pipeline manually to show each step
    from paraview_llm import (
        resolve_fields, 
        select_available_methods,
        build_llm_context,
        call_llm,
        validate_llm_response,
        compile_to_tool_calls,
    )
    
    ontology = orchestrator.ontology
    
    # Step 1: Resolve fields
    bindings, unresolved = resolve_fields(ontology, mock_fields)
    print(f"\n[1] Resolved bindings: {bindings}")
    print(f"    Unresolved: {unresolved}")
    
    # Step 2: Select available methods
    available, unavailable = select_available_methods(ontology, bindings)
    print(f"\n[2] Available methods: {available}")
    print(f"    Unavailable: {unavailable}")
    
    # Step 3: Build LLM context
    context = build_llm_context(
        user_query="characterize flowfield",
        ontology=ontology,
        bindings=bindings,
        available_methods=available
    )
    print(f"\n[3] LLM context built ({len(context)} chars)")
    
    # Step 4: Call LLM (will use mock if no API key)
    llm_response = call_llm(context)
    print(f"\n[4] LLM response: {llm_response}")
    
    # Step 5: Validate
    is_valid, errors = validate_llm_response(llm_response, ontology, available)
    print(f"\n[5] Valid: {is_valid}, Errors: {errors}")
    
    # Step 6: Compile to tool calls
    if is_valid:
        tool_calls = compile_to_tool_calls(llm_response, ontology, bindings)
        print(f"\n[6] Compiled {len(tool_calls)} tool calls:")
        for i, tc in enumerate(tool_calls, 1):
            print(f"    {i}. {tc['tool']}({tc['args']})")


if __name__ == "__main__":
    main()
