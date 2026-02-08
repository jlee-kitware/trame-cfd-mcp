"""
Headless CFD Assistant - No UI, just the integration pattern

This shows the minimal code to integrate trame-llm + paraview-llm.
Useful for testing or scripting.

Run:
    pvpython --venv .venv headless.py
    pvpython --venv .venv headless.py --mock   # Use mock (no API calls)
"""

import sys
import argparse

sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")
sys.path.insert(0, "/Users/jeff.lee/gitsync/trame-llm/src")

from paraview import simple

# Setup: Load test data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

# Get reader name
reader_name = None
for name, proxy in simple.GetSources().items():
    if proxy == reader:
        reader_name = name[0]
        break

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1024, 768]
simple.SetActiveView(view)


class MinimalApp:
    """Minimal app interface that ParaViewMCP expects"""
    def update(self):
        simple.Render()
    
    def reset_camera(self):
        simple.ResetCamera()
    
    class ctrl:
        class on_active_proxy_change:
            @staticmethod
            def exists(): return False
        class on_data_change:
            @staticmethod
            def exists(): return False


def run_with_mock():
    """Run with MockLLMExecutor - no API calls, uses predefined sequences."""
    from trame_llm.paraview import ParaViewMCP
    from paraview_llm import ExtendedParaViewMCP, MockLLMExecutor
    
    app = MinimalApp()
    base_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(base_mcp)
    executor = MockLLMExecutor(extended_mcp, reader_name)
    
    # Mock uses string keys, not natural language
    queries = [
        "vortices_q",      # Q-criterion vortices
        "stagnation",      # Find stagnation point
        "pressure",        # Pressure slice
    ]
    
    for query_key in queries:
        print("\n" + "=" * 60)
        print(f"Mock query: '{query_key}'")
        print("=" * 60)
        
        results = executor.execute(query_key)
        
        print(f"\nExecuted {len(results)} tools:")
        for tool_name, kwargs, result in results:
            if isinstance(result, dict) and 'error' in result:
                print(f"  ✗ {tool_name}: {result['error']}")
            else:
                print(f"  ✓ {tool_name}")


def run_with_llm():
    """Run with CFDAssistant - uses real LLM API calls."""
    from dotenv import load_dotenv
    load_dotenv()
    
    from trame_llm.paraview import ParaViewMCP
    from paraview_llm import ExtendedParaViewMCP, CFDAssistant
    
    app = MinimalApp()
    base_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(base_mcp)
    assistant = CFDAssistant(extended_mcp, base_mcp, reader_name)
    
    # Natural language queries
    queries = [
        "Show me the vortices using Q-criterion",
        "Where is the stagnation point?",
        "Create a slice colored by pressure",
    ]
    
    for query in queries:
        print("\n" + "=" * 60)
        print(f"Query: '{query}'")
        print("=" * 60)
        
        result = assistant.query(query)
        
        intent = result['intent'].type.value
        workflow = result['result'].get('workflow', 'N/A')
        success = result['success']
        
        print(f"  Intent: {intent}")
        print(f"  Workflow: {workflow}")
        print(f"  Success: {success}")
        
        if not success and 'error' in result['result']:
            print(f"  Error: {result['result']['error']}")


def main():
    parser = argparse.ArgumentParser(description="Headless CFD Assistant")
    parser.add_argument("--mock", action="store_true", help="Use mock executor (no API calls)")
    args = parser.parse_args()
    
    if args.mock:
        run_with_mock()
    else:
        run_with_llm()
    
    # Save screenshot
    simple.SaveScreenshot("output/headless_test.png", view)
    print("\nSaved: output/headless_test.png")


if __name__ == "__main__":
    main()
