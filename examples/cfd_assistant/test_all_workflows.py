"""
Test all workflows using CFDAnalysisMCP + trame_llm.
"""

import sys
import os
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")
sys.path.insert(0, "/Users/jeff.lee/gitsync/trame-llm/src")

from paraview import simple

# Suppress VTK warnings
import vtk
vtk.vtkLogger.SetStderrVerbosity(vtk.vtkLogger.VERBOSITY_WARNING)

from dotenv import load_dotenv
load_dotenv()

import asyncio

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

# Initialize MCPs
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType
from paraview_llm import ExtendedParaViewMCP
from paraview_llm.cfd_analysis import CFDAnalysisMCP

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
analysis_mcp = CFDAnalysisMCP(app, extended_mcp)

os.makedirs("output", exist_ok=True)

# Test queries
tests = [
    # Basic understanding
    ("describe_data", "What data do I have?"),
    
    # Vortex visualization
    ("vortex_q", "Show me vortices using Q-criterion"),
    
    # Streamlines
    ("streamlines_wake", "Show streamlines in the wake region"),
    
    # Slicing
    ("slice_midplane", "Create a slice through the center of the domain"),
    
    # Surface pressure
    ("surface_pressure", "Show surface pressure distribution"),
    
    # Field statistics
    ("field_stats", "What is the range of velocity in this dataset?"),
]


def progress_callback(ptype, msg):
    if ptype == ProgressType.MCP_SELECTION:
        print_log(f"[tool] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        # Truncate long responses
        if len(msg) > 200:
            msg = msg[:200] + "..."
        print_log(f"[response] {msg}")
    elif ptype == ProgressType.ERROR:
        print_log(f"[ERROR] {msg}")


async def run_tests():
    # Initialize LLM client
    llm = LLMClient()
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(base_mcp)
    llm.register_mcp(analysis_mcp)
    await llm.initialize()
    
    print_log(f"\n{len(llm.tools)} tools available")
    print_log(f"{len(llm.resources)} resources available\n")
    
    results = []
    
    for test_name, query in tests:
        print_log("=" * 70)
        print_log(f"TEST: {test_name}")
        print_log(f"QUERY: {query}")
        print_log("=" * 70)
        
        # Reset pipeline for each test (keep only reader)
        for name, p in list(simple.GetSources().items()):
            if p != reader:
                simple.Delete(p)
        simple.SetActiveSource(reader)
        simple.ResetCamera()
        
        try:
            await llm.process_prompt(query)
            
            # Save screenshot
            simple.Render()
            filename = f"output/workflow_{test_name}.png"
            simple.SaveScreenshot(filename, view)
            print_log(f"Saved: {filename}")
            results.append((test_name, "PASS", ""))
            
        except Exception as e:
            print_log(f"FAILED: {e}")
            results.append((test_name, "FAIL", str(e)))
        
        print_log("")
    
    # Summary
    print_log("=" * 70)
    print_log("SUMMARY")
    print_log("=" * 70)
    passed = sum(1 for _, status, _ in results if status == "PASS")
    print_log(f"Passed: {passed}/{len(results)}")
    for name, status, error in results:
        if status == "FAIL":
            print_log(f"  FAIL: {name} - {error}")


if __name__ == "__main__":
    asyncio.run(run_tests())
