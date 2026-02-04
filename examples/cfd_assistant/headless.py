"""
Headless CFD Assistant - No UI, just the integration pattern

This shows the minimal code to integrate trame-llm + paraview-llm.
Useful for testing or scripting.

Run:
    pvpython headless.py
"""

from paraview import simple

# Setup: Create some test data
wavelet = simple.Wavelet()
simple.Show()
simple.ResetCamera()

# Now setup the LLM integration
# (In real use, this would be in a trame app)

class MinimalApp:
    """Minimal app interface that ParaViewMCP expects"""
    def update(self):
        simple.Render()
    
    def reset_camera(self):
        simple.ResetCamera()
    
    class ctrl:
        @staticmethod
        def on_active_proxy_change():
            pass
        
        @staticmethod 
        def on_data_change():
            pass
        
        # Make .exists() work
        on_active_proxy_change.exists = lambda: False
        on_data_change.exists = lambda: False


def main():
    from trame_llm.paraview import ParaViewMCP
    from paraview_llm import Orchestrator, TrameMCPAdapter
    
    # Create minimal app
    app = MinimalApp()
    
    # Setup the stack
    paraview_mcp = ParaViewMCP(app)
    adapter = TrameMCPAdapter(paraview_mcp)
    
    # Use mock LLM for testing (set llm_provider="openai" for real)
    orchestrator = Orchestrator(
        mcp_client=adapter,
        llm_provider="mock"
    )
    
    # Check what fields are available
    print("Available fields:", adapter.available_fields())
    
    # Run a query
    print("\n" + "="*60)
    print("Query: 'characterize flowfield'")
    print("="*60)
    
    result = orchestrator.run("characterize flowfield")
    
    if result.get("success"):
        print(f"\nReasoning: {result['reasoning']}")
        print(f"\nResults:")
        for r in result['results']:
            if 'error' in r:
                print(f"  ❌ {r['tool']}: {r['error']}")
            else:
                print(f"  ✅ {r['tool']}: {r['result']}")
    else:
        print(f"\nError: {result.get('error')}")


if __name__ == "__main__":
    main()
