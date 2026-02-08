"""
Test the safe CFD Assistant architecture.

Architecture enforces:
- LLM only classifies intent (Tier 1) and summarizes results (Tier 4)
- Workflow selection is deterministic (Tier 2)
- Execution is deterministic (Tier 3)
- NO LLM in the execution loop
"""

import sys
import os
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

from paraview import simple

# Suppress VTK warnings
import vtk
vtk.vtkLogger.SetStderrVerbosity(vtk.vtkLogger.VERBOSITY_WARNING)

# Load API key
from dotenv import load_dotenv
load_dotenv()


def log(msg):
    print(msg, flush=True)


# Load test data
log("Loading test data...")
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

# Get reader name
reader_name = None
for name, p in simple.GetSources().items():
    if p == reader:
        reader_name = name[0]
        break
log(f"Data source: {reader_name}")

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
log("Initializing MCPs...")
from trame_llm.paraview import ParaViewMCP

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

from paraview_llm import ExtendedParaViewMCP, CFDAssistant
extended_mcp = ExtendedParaViewMCP(base_mcp)

# Create assistant
log("Creating CFD Assistant (safe architecture)...")
assistant = CFDAssistant(
    extended_mcp=extended_mcp,
    base_mcp=base_mcp,
    data_source=reader_name,
    provider="openai"
)
log("Assistant ready.")
log("")

os.makedirs("output", exist_ok=True)

# Test queries
queries = [
    "What data do I have?",
    "Show me the vortices",
    "Create a slice through the center colored by pressure",
    "What are the drag and lift forces?",
]

for i, query in enumerate(queries, 1):
    log("=" * 60)
    log(f"[{i}] USER: {query}")
    log("=" * 60)
    
    result = assistant.query(query)
    
    log(f"\nIntent: {result['intent'].type.value}")
    log(f"Workflow: {result['result'].get('workflow', 'N/A')}")
    log(f"Success: {result['success']}")
    log(f"\nResponse: {result['response']}")
    
    if not result['success']:
        log(f"Error: {result['result'].get('error', 'Unknown')}")
    
    # Save screenshot
    simple.SetActiveView(view)
    simple.Render(view)
    filename = f"output/safe_assistant_{i:02d}.png"
    simple.SaveScreenshot(filename, view, ImageResolution=[1024, 768])
    log(f"\nScreenshot: {filename}")
    log("")

# Summary
log("=" * 60)
log("SUMMARY")
log("=" * 60)
log(f"Total LLM requests: {assistant.usage['requests']}")
log(f"Model: {assistant.usage['model']}")
log(f"Expected: 2 requests per query (classify + summarize)")
log(f"Actual: {assistant.usage['requests']} for {len(queries)} queries")
log("")
log("History:")
for h in assistant.history:
    status = "✓" if h["success"] else "✗"
    log(f"  {status} {h['intent']}: {h['query'][:40]}...")
