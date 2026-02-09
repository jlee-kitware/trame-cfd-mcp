"""
Test all workflows in the safe CFD Assistant.
"""

import sys
import os
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

from paraview import simple

# Suppress VTK warnings
import vtk
vtk.vtkLogger.SetStderrVerbosity(vtk.vtkLogger.VERBOSITY_WARNING)

from dotenv import load_dotenv
load_dotenv()


def print_log(msg):
    print(msg, flush=True)


# Load test data
print_log("Loading test data...")
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

reader_name = None
for name, p in simple.GetSources().items():
    if p == reader:
        reader_name = name[0]
        break
print_log(f"Data source: {reader_name}")

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1024, 768]
view.LODThreshold = 0
view.UseOutlineForLODRendering = 1
simple.SetActiveView(view)
simple.SetActiveSource(reader)
simple.Show(reader, view)
simple.ResetCamera()

# Initialize
from trame_llm.paraview import ParaViewMCP
from paraview_llm import ExtendedParaViewMCP, CFDAssistant

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

app = MinimalApp()
base_mcp = ParaViewMCP(app)
extended_mcp = ExtendedParaViewMCP(base_mcp)

assistant = CFDAssistant(
    extended_mcp=extended_mcp,
    base_mcp=base_mcp,
    data_source=reader_name,
    provider="openai"
)

os.makedirs("output", exist_ok=True)

# Test all key workflows
tests = [
    # Basic
    ("Describe data", "What data do I have?"),
    
    # Vortex methods
    ("Vortex Q-criterion", "Show me vortices using Q-criterion"),
    ("Vortex Lambda2", "Show vortices with lambda2 method"),
    ("Vortex Helicity", "Visualize helical vortices"),
    
    # Wake/Flow
    ("Wake detection", "Show me the wake region"),
    ("Streamlines", "Create streamlines"),
    
    # Forces
    ("Compute forces", "What are the drag and lift forces?"),
    ("Drag distribution", "Show the accumulated drag distribution"),
    ("Lift distribution", "Show the spanwise lift distribution"),
    
    # Location finding
    ("Stagnation point", "Find the stagnation point"),
    ("Max pressure", "Where is the maximum pressure?"),
    ("Query location", "Where is velocity less than 0.3?"),
    
    # Charts
    ("Histogram", "Show a histogram of pressure distribution"),
    
    # Removed: Slice - this is a base ParaView operation, not a CFD-specific intent
    # "Create a slice" is handled by trame_llm directly via base.create("Slice")
]

results = []
for i, (name, query) in enumerate(tests, 1):
    print_log("=" * 60)
    print_log(f"[{i}] {name}: {query}")
    print_log("=" * 60)
    
    # Clean up derived proxies from previous test to avoid texture exhaustion
    extended_mcp.hide_all(delete_derived=True)
    
    result = assistant.query(query)
    
    intent = result['intent'].type.value
    workflow = result['result'].get('workflow', 'N/A')
    success = result['success']
    
    print_log(f"Intent: {intent}")
    print_log(f"Workflow: {workflow}")
    print_log(f"Success: {success}")
    
    # Show actual result data for location/value queries
    workflow_result = result['result'].get('result', {})
    if isinstance(workflow_result, dict):
        if 'location' in workflow_result:
            loc = workflow_result['location']
            print_log(f"Location: ({loc[0]:.4f}, {loc[1]:.4f}, {loc[2]:.4f})")
        if 'num_points' in workflow_result:
            print_log(f"Points matched: {workflow_result['num_points']}")
        if 'value' in workflow_result:
            print_log(f"Value: {workflow_result['value']:.4f}")
        if 'drag' in workflow_result:
            print_log(f"Drag: {workflow_result['drag']:.4f}, Lift: {workflow_result.get('lift', 0):.4f}")
    
    if not success:
        print_log(f"ERROR: {result['result'].get('error', 'Unknown')}")
    
    results.append({
        "name": name,
        "intent": intent,
        "workflow": workflow,
        "success": success,
        "error": result['result'].get('error') if not success else None
    })
    
    # Screenshot - use chart view if workflow created one, otherwise 3D view
    screenshot_view = view
    if hasattr(extended_mcp, '_last_chart_view') and extended_mcp._last_chart_view is not None:
        # Chart workflow - capture the chart view
        screenshot_view = extended_mcp._last_chart_view
        extended_mcp._last_chart_view = None  # Reset for next iteration
    
    simple.Render(screenshot_view)
    filename = f"output/workflow_test_{i:02d}_{name.replace(' ', '_').lower()}.png"
    simple.SaveScreenshot(filename, screenshot_view, ImageResolution=[1024, 768])
    print_log("")

# Summary
print_log("=" * 60)
print_log("WORKFLOW TEST SUMMARY")
print_log("=" * 60)
for r in results:
    status = "✓" if r["success"] else "✗"
    print_log(f"{status} {r['name']:20} → {r['intent']:30} | {r['workflow']}")
    if r["error"]:
        print_log(f"   ERROR: {r['error']}")

passed = len([r for r in results if r["success"]])
print_log(f"\nPassed: {passed}/{len(results)}")

# Usage/Cost summary
usage = assistant.usage
print_log("")
print_log("=" * 60)
print_log("COST SUMMARY")
print_log("=" * 60)
print_log(f"Model: {usage['model']}")
print_log(f"Requests: {usage['requests']}")
print_log(f"Tokens: {usage['total_tokens']:,} ({usage['prompt_tokens']:,} prompt + {usage['completion_tokens']:,} completion)")
print_log(f"Estimated cost: ${usage['estimated_cost_usd']:.4f}")
