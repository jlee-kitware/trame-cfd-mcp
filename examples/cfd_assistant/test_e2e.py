#!/usr/bin/env pvpython
"""
E2E tests with mock or real LLM.

Usage:
    pvpython test_e2e.py              # Mock mode (default, fast, free)
    pvpython test_e2e.py --real       # Real LLM mode (single-shot, ~30s)
    pvpython test_e2e.py --mock       # Explicit mock mode
"""

import sys
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

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
print(f"E2E Test Suite - {'REAL LLM (single-shot)' if USE_REAL_LLM else 'MOCK LLM'}")
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
    "vortices_q": "show me the vortices using Q-criterion",
    "vortices_lambda2": "visualize vortex cores using lambda2 method",
    "vortices_swirl": "show swirling strength in the flow",
    "vortices_helicity": "show helical vortex structures",
    "characterize": "characterize the flowfield - show me the key features",
}

# Setup executor based on mode
if USE_REAL_LLM:
    from paraview_llm.single_shot import SingleShotExecutor
    executor = SingleShotExecutor(extended_mcp, reader_name)
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
        # Single-shot LLM execution
        query_text = QUERY_TEXT.get(query_key, query_key)
        print(f"Query: '{query_text}'")
        
        try:
            tool_results = executor.execute(query_text)
            print("Tools executed:")
            has_error = False
            for tool_name, kwargs, result in tool_results:
                status = "✓" if "error" not in str(result) else "✗"
                print(f"  {status} {tool_name}")
                if "error" in str(result):
                    print(f"      ERROR: {result.get('error', result)}")
                    has_error = True
        except Exception as e:
            print(f"ERROR: {e}")
            has_error = True
    else:
        # Mock LLM execution
        executor.context = {
            "data_source": reader_name,
            "last_created": None,
            "min_location": None,
            "max_location": None,
            "high_gradient_location": None,
        }
        
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
    
    # Save screenshot - use chart view if one was created, otherwise render view
    all_views = simple.GetViews()
    chart_view = None
    for v in all_views:
        vtype = str(type(v))
        if 'RenderView' not in vtype and v != view:
            chart_view = v
            break
    
    screenshot_view = chart_view if chart_view else view
    simple.Render(screenshot_view)
    prefix = "real" if USE_REAL_LLM else "mock"
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

# Summary
print(f"\n{'=' * 60}")
print("SUMMARY")
print("=" * 60)
for query_key in test_queries:
    status = "✓" if results.get(query_key) == "PASSED" else "✗"
    print(f"  {status} {query_key}")

passed = len([r for r in results.values() if r == "PASSED"])
print(f"\nPassed: {passed}/{len(test_queries)}")
print(f"Total time: {total_time:.1f}s")
print(f"Mode: {'REAL LLM (single-shot)' if USE_REAL_LLM else 'MOCK LLM'}")
print("=" * 60)
