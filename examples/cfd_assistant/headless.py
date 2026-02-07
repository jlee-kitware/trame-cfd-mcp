"""
Headless CFD Assistant - No UI, just the integration pattern

This shows the minimal code to integrate trame-llm + paraview-llm.
Useful for testing or scripting.

Run:
    pvpython --venv .venv headless.py
"""

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


def main():
    import sys
    sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")
    sys.path.insert(0, "/Users/jeff.lee/gitsync/trame-llm/src")
    
    from trame_llm.paraview import ParaViewMCP
    from paraview_llm import ExtendedParaViewMCP, MockLLMExecutor
    
    # Create minimal app
    app = MinimalApp()
    
    # Setup the stack
    base_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(base_mcp)
    
    # Use mock executor for testing
    executor = MockLLMExecutor(extended_mcp, reader_name)
    
    # Run some queries
    queries = [
        "show me the vortices using Q-criterion",
        "where is the stagnation point",
        "show me the pressure distribution",
    ]
    
    for query in queries:
        print("\n" + "=" * 60)
        print(f"Query: '{query}'")
        print("=" * 60)
        
        results = executor.execute(query)
        
        print(f"\nExecuted {len(results)} tools:")
        for tool_name, kwargs, result in results:
            if isinstance(result, dict) and 'error' in result:
                print(f"  ✗ {tool_name}: {result['error']}")
            else:
                print(f"  ✓ {tool_name}")
    
    # Save screenshot
    simple.SaveScreenshot("output/headless_test.png", view)
    print("\nSaved: output/headless_test.png")


if __name__ == "__main__":
    main()
