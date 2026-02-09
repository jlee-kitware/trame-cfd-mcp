"""
Test CFDMCP hybrid approach with same queries as test_all_workflows.

Compares: CFDAssistant (explicit intent classification) vs CFDMCP (LLM picks tools)
"""

import asyncio
import sys
import os

sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType
from paraview_llm import ExtendedParaViewMCP

# Suppress VTK warnings
import vtk
vtk.vtkLogger.SetStderrVerbosity(vtk.vtkLogger.VERBOSITY_WARNING)


class MinimalApp:
    def update(self): simple.Render()
    def reset_camera(self): simple.ResetCamera()
    class ctrl:
        class on_active_proxy_change:
            @staticmethod
            def exists(): return False
        class on_data_change:
            @staticmethod
            def exists(): return False


# Track tool calls per query
current_tools = []
current_errors = []

def progress_handler(msg_type: ProgressType, msg: str):
    global current_tools, current_errors
    if msg_type == ProgressType.MCP_SELECTION:
        tool = msg.replace("Calling: ", "")
        current_tools.append(tool)
    elif msg_type == ProgressType.MCP_ERROR:
        current_errors.append(msg)
    elif msg_type == ProgressType.ERROR:
        current_errors.append(msg)


async def run_tests():
    global current_tools, current_errors
    
    # Load test data
    print("Loading test data...")
    reader = simple.OpenDataFile("test.vtm")
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    # Setup MCPs
    app = MinimalApp()
    pv_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(pv_mcp)
    
    # Create LLM client with BOTH base and extended tools exposed
    llm_client = LLMClient(max_iteractions=10)
    llm_client.register_mcp(pv_mcp)  # Base ParaView tools
    llm_client.register_mcp(extended_mcp)  # Extended CFD tools
    llm_client.set_progress_handler(progress_handler)
    
    await llm_client.initialize()
    
    print(f"Discovered {len(llm_client.tools)} tools")
    
    os.makedirs("output", exist_ok=True)
    
    # Same test queries as test_all_workflows
    tests = [
        ("Describe data", "What data do I have?"),
        ("Vortex Q-criterion", "Show me vortices using Q-criterion"),
        ("Vortex Lambda2", "Show vortices with lambda2 method"),
        ("Vortex Helicity", "Visualize helical vortices"),
        ("Wake detection", "Show me the wake region"),
        ("Streamlines", "Create streamlines"),
        ("Compute forces", "What are the drag and lift forces?"),
        ("Drag distribution", "Show the accumulated drag distribution"),
        ("Lift distribution", "Show the spanwise lift distribution"),
        ("Stagnation point", "Find the stagnation point"),
        ("Max pressure", "Where is the maximum pressure?"),
        ("Query location", "Where is velocity less than 0.3?"),
        ("Histogram", "Show a histogram of pressure distribution"),
    ]
    
    results = []
    
    for i, (name, query) in enumerate(tests, 1):
        print("=" * 60)
        print(f"[{i}] {name}: {query}")
        print("=" * 60)
        
        # Reset state
        current_tools = []
        current_errors = []
        
        # Clean up - delete everything except reader
        for src_name, src in list(simple.GetSources().items()):
            if 'Reader' not in src_name[0]:
                try:
                    simple.Delete(src)
                except:
                    pass
        
        simple.SetActiveSource(reader)
        simple.Show(reader, view)
        simple.ResetCamera()
        
        # Run query
        await llm_client.process_prompt(query)
        
        # Record results
        success = len(current_errors) == 0 and len(current_tools) > 0
        
        results.append({
            "name": name,
            "query": query,
            "tools": current_tools.copy(),
            "errors": current_errors.copy(),
            "success": success
        })
        
        print(f"Tools called: {current_tools}")
        if current_errors:
            print(f"Errors: {current_errors}")
        print(f"Success: {success}")
        
        # Screenshot
        simple.Render(view)
        filename = f"output/hybrid_workflow_{i:02d}_{name.replace(' ', '_').lower()}.png"
        simple.SaveScreenshot(filename, view, ImageResolution=[1024, 768])
        print()
    
    # Summary
    print("=" * 60)
    print("HYBRID CFDMCP TEST SUMMARY")
    print("=" * 60)
    
    for r in results:
        status = "✓" if r["success"] else "✗"
        tools_str = ", ".join(r["tools"]) if r["tools"] else "(no tools)"
        print(f"{status} {r['name']:20} → {tools_str}")
        if r["errors"]:
            for e in r["errors"][:1]:  # Just first error
                print(f"   ERROR: {e[:60]}...")
    
    passed = len([r for r in results if r["success"]])
    print(f"\nPassed: {passed}/{len(results)}")
    
    return results


if __name__ == "__main__":
    asyncio.run(run_tests())
