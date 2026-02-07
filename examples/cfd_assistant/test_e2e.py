"""
E2E tests with mock or real LLM.

Usage:
    pvpython test_e2e.py              # Mock mode (default, fast, free)
    pvpython test_e2e.py --real       # Real LLM mode (uses OpenAI assistant)
    pvpython test_e2e.py --mock       # Explicit mock mode
"""

import sys
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")
sys.path.insert(0, "/Users/jeff.lee/gitsync/trame-llm/src")

import argparse
from paraview import simple
import time

# Parse args
parser = argparse.ArgumentParser()
parser.add_argument("--real", action="store_true", help="Use real LLM (default: mock)")
parser.add_argument("--mock", action="store_true", help="Use mock LLM (default)")
args, _ = parser.parse_known_args()

USE_REAL_LLM = args.real and not args.mock

print("=" * 60)
print(f"E2E Test Suite - {'REAL LLM (assistant)' if USE_REAL_LLM else 'MOCK LLM'}")
print("=" * 60)

# Load data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

reader_name = None
for name, proxy in simple.GetSources().items():
    if proxy == reader:
        reader_name = name[0]
        break

print(f"Data source: {reader_name}")

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1024, 768]
view.Background = [0.4, 0.4, 0.4]
simple.SetActiveView(view)

# Setup MCP
from trame_llm.paraview import ParaViewMCP
from paraview_llm.extended_mcp import ExtendedParaViewMCP

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

# Test queries - map keys to natural language
QUERY_TEXT = {
    "shear_layer": "show me the shear layer",
    "stagnation": "where is the stagnation point",
    "flow_pattern": "visualize the flow pattern around the body",
    "pressure": "show me the pressure distribution",
    "velocity_stats": "what are the velocity statistics in this dataset",
    "velocity_distribution": "show me a histogram of the velocity distribution",
    "forces": "calculate the drag and lift forces",
    "drag_distribution": "show me how drag accumulates along the streamwise direction",
    "lift_distribution": "show me the spanwise lift distribution",
    "max_velocity": "where is the maximum velocity",
    "wake_slice": "create a slice through the wake region",
    "wake_streamlines": "show me streamlines in the wake",
    "vortices_q": "show me the vortices using Q-criterion",
    "vortices_lambda2": "visualize vortex cores using lambda2 method",
    "vortices_swirl": "show swirling strength in the flow",
    "vortices_helicity": "show helical vortex structures",
    "characterize": "characterize the flowfield - show me the key features",
}

# Setup executor based on mode
if USE_REAL_LLM:
    from paraview_llm.assistant import create_assistant
    assistant = create_assistant(
        base_mcp=base_mcp,
        extended_mcp=extended_mcp,
        provider="openai",
        model="gpt-4o-mini",
        data_source=reader_name
    )
else:
    from paraview_llm.mock_llm import MockLLMExecutor
    executor = MockLLMExecutor(extended_mcp, reader_name)

# Get test list from mock responses (defines canonical test set)
from paraview_llm.mock_llm import MOCK_RESPONSES
test_queries = list(MOCK_RESPONSES.keys())

results = {}
total_time = 0

for i, query_key in enumerate(test_queries, 1):
    print(f"\n{'=' * 60}")
    print(f"TEST {i}: {query_key}")
    print("=" * 60)
    
    # Clean up from previous test
    for proxy_name, proxy in list(simple.GetSources().items()):
        if proxy != reader:
            simple.Delete(proxy)
    
    # Delete any extra views (charts) and ensure we use render view
    for v in simple.GetViews():
        if v != view:
            simple.Delete(v)
    simple.SetActiveView(view)
    simple.ResetCamera()
    
    t0 = time.time()
    
    if USE_REAL_LLM:
        # Real LLM execution using assistant
        query_text = QUERY_TEXT.get(query_key, query_key)
        print(f"Query: '{query_text}'")
        
        try:
            result = assistant.execute(query_text)
            print(f"Response: {result['response'][:100]}...")
            print("Tools executed:")
            has_error = False
            tool_results = []
            for tool in result.get("tools", []):
                tool_name = tool.get("tool", "unknown")
                tool_result = tool.get("result", {})
                status = "✓" if not isinstance(tool_result, dict) or "error" not in tool_result else "✗"
                print(f"  {status} {tool_name}")
                if isinstance(tool_result, dict) and "error" in tool_result:
                    print(f"      ERROR: {tool_result['error']}")
                    has_error = True
                tool_results.append((tool_name, {}, tool_result))
        except Exception as e:
            print(f"ERROR: {e}")
            has_error = True
            tool_results = []
    else:
        # Mock LLM execution
        executor.context = {"data_source": reader_name}
        
        tool_results = executor.execute(query_key)
        
        print("Tools executed:")
        has_error = False
        for tool_name, kwargs, result in tool_results:
            status = "✓" if "error" not in result else "✗"
            print(f"  {status} {tool_name}")
            if "error" in result:
                print(f"      ERROR: {result['error']}")
                has_error = True
    
    elapsed = time.time() - t0
    total_time += elapsed
    
    # Data-only workflows - save JSON instead of PNG
    DATA_ONLY_WORKFLOWS = {"velocity_stats", "forces"}
    prefix = "real" if USE_REAL_LLM else "mock"
    
    if query_key in DATA_ONLY_WORKFLOWS:
        # Save data results to JSON
        import json
        filename = f"output/{prefix}_{i:02d}_{query_key}.json"
        # Get the last result that has actual data
        data_result = None
        for tool_name, kwargs, result in tool_results:
            if isinstance(result, dict) and "error" not in result:
                data_result = result
        if data_result:
            with open(filename, 'w') as f:
                json.dump(data_result, f, indent=2)
    else:
        # Visual workflows - save screenshot
        all_views = simple.GetViews()
        chart_view = None
        for v in all_views:
            vtype = str(type(v))
            if 'RenderView' not in vtype and v != view:
                chart_view = v
                break
        
        screenshot_view = chart_view if chart_view else view
        simple.Render(screenshot_view)
        filename = f"output/{prefix}_{i:02d}_{query_key}.png"
        
        if chart_view:
            simple.SaveScreenshot(filename, screenshot_view, ImageResolution=[800, 400])
        else:
            simple.SaveScreenshot(filename, screenshot_view, ImageResolution=[1024, 768])
    
    if has_error:
        results[query_key] = "FAILED"
        print(f"✗ FAILED ({elapsed:.1f}s) - saved {filename}")
    else:
        results[query_key] = "PASSED"
        print(f"✓ PASSED ({elapsed:.1f}s) - saved {filename}")

# Cleanup assistant if using real LLM
if USE_REAL_LLM and hasattr(assistant, 'cleanup'):
    try:
        assistant.cleanup()
    except:
        pass

# Summary
print(f"\n{'=' * 60}")
print("SUMMARY")
print("=" * 60)
passed = sum(1 for r in results.values() if r == "PASSED")
failed = sum(1 for r in results.values() if r == "FAILED")
print(f"Total: {len(results)} tests, {passed} passed, {failed} failed")
print(f"Time: {total_time:.1f}s total, {total_time/len(results):.1f}s avg")

for key, result in results.items():
    status = "✓" if result == "PASSED" else "✗"
    print(f"  {status} {key}")

print("=" * 60)
