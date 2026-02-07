"""
Test the CFD Assistant with conversation history.

Run:
    pvpython -u --venv .venv test_assistant.py                 # OpenAI mini (default)
    pvpython -u --venv .venv test_assistant.py --gpt4o         # OpenAI gpt-4o
    pvpython -u --venv .venv test_assistant.py --claude        # Claude
    pvpython -u --venv .venv test_assistant.py --scenario drag # Drag distribution test
    
Features:
    - Persistent conversation (multi-turn)
    - Ontology loaded once (not per request)
    - Both OpenAI and Claude backends
    - Multiple test scenarios
    
Note: Use -u flag for unbuffered output to see prints immediately.
"""

import sys
import os

sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

import argparse
from paraview import simple


def log(msg):
    """Print with immediate flush."""
    print(msg, flush=True)
    sys.stdout.flush()


# Parse args
parser = argparse.ArgumentParser()
parser.add_argument("--claude", action="store_true", help="Use Claude")
parser.add_argument("--openai", action="store_true", help="Use OpenAI (default)")
parser.add_argument("--gpt4o", action="store_true", help="Use gpt-4o instead of gpt-4o-mini")
parser.add_argument("--scenario", type=str, default="vortex", 
                    choices=["vortex", "drag", "ontology", "wake", "all"],
                    help="Test scenario: vortex, drag, ontology, wake, or all")
args, _ = parser.parse_known_args()

provider = "claude" if args.claude else "openai"
model = "gpt-4o" if args.gpt4o else "gpt-4o-mini"
if args.claude:
    model = None  # Use default Claude model

# Test scenarios
SCENARIOS = {
    "vortex": {
        "name": "Vortex Visualization",
        "queries": [
            "Show me the vortices using Q-criterion",
            "What did you just create?",
            "Now color it by pressure instead of velocity",
            "What have we done in this session so far?",
        ]
    },
    "drag": {
        "name": "Drag Distribution Analysis",
        "queries": [
            "Show me the accumulated drag distribution",
            "Where along the body is drag the worst?",
            "At what position does drag reach half of the total?",
            "Summarize the drag distribution characteristics",
        ]
    },
    "ontology": {
        "name": "Ontology Reasoning",
        "queries": [
            "What methods can detect vortices? Query the ontology.",
            "What are the requirements for computing q_criterion?",
            "Can I visualize vortices with this dataset? Check what fields are available.",
            "Show me the vortices based on what we learned.",
        ]
    },
    "wake": {
        "name": "Wake Flow Analysis",
        "queries": [
            "Where is the wake region in this flow?",
            "Create streamlines to visualize the wake flow pattern",
            "What is the velocity deficit in the wake?",
            "Show me a slice through the wake colored by velocity magnitude",
        ]
    },
}

scenarios_to_run = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]

log("=" * 60)
log(f"CFD Assistant Test - {provider.upper()} ({model or 'default'})")
log("=" * 60)

# Load test data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

# Get reader name
reader_name = None
for name, proxy in simple.GetSources().items():
    if proxy == reader:
        reader_name = name[0]
        break

log(f"Data source: {reader_name}")

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1024, 768]
view.LODThreshold = 0  # Disable LOD — avoids Viskores field association errors in batch mode
simple.SetActiveView(view)
simple.SetActiveSource(reader)
simple.Show(reader, view)
simple.ResetCamera()

# Create MCP instances
from trame_llm.paraview import ParaViewMCP
from paraview_llm import ExtendedParaViewMCP, create_assistant

class MinimalApp:
    """Minimal app stub for ParaViewMCP."""
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

os.makedirs("output", exist_ok=True)

for scenario_key in scenarios_to_run:
    scenario = SCENARIOS[scenario_key]
    
    log(f"\n{'#' * 60}")
    log(f"# SCENARIO: {scenario['name']}")
    log(f"{'#' * 60}")
    
    # Create fresh assistant for each scenario
    log(f"\nCreating {provider} assistant...")
    assistant = create_assistant(
        base_mcp=base_mcp,
        extended_mcp=extended_mcp,
        provider=provider,
        model=model,
        data_source=reader_name,
    )
    log(f"Assistant ready.")
    
    # Reset view for clean scenario - delete all sources except reader
    for name, _ in list(simple.GetSources().items()):
        if name[0] != reader_name:
            simple.Delete(simple.FindSource(name[0]))
    
    # Delete any chart views from previous scenario and ensure render view is active
    for v in simple.GetViews():
        if v != view:  # Keep our main render view
            simple.Delete(v)
    
    # Clean up stale color bars from previous scenario
    for rep_info in view.Representations:
        try:
            rep_info.SetScalarBarVisibility(view, False)
        except:
            pass
    
    # Ensure we're using the render view (not a chart view)
    simple.SetActiveView(view)
    simple.SetActiveSource(reader)
    
    # Show body surface as context: extracted surface with farfield clipped away
    extended_mcp.hide_all()
    extended_mcp.show_data_context(proxy_name=reader_name)
    
    # Set isometric camera so 3D domain is visible, not face-on
    simple.ResetCamera()
    view.CameraPosition = [
        view.CameraFocalPoint[0] + view.CameraParallelScale * 1.5,
        view.CameraFocalPoint[1] + view.CameraParallelScale * 1.0,
        view.CameraFocalPoint[2] + view.CameraParallelScale * 1.5,
    ]
    simple.ResetCamera()
    
    # Run queries
    for i, query in enumerate(scenario["queries"], 1):
        log(f"\n{'=' * 60}")
        log(f"[{i}] USER: {query}")
        log("=" * 60)
        
        result = assistant.execute(query)
        
        # Show response
        response = result["response"]
        log(f"\nASSISTANT: {response}")
        
        # Show tools called
        if result["tools"]:
            log(f"\nTools called:")
            for tc in result["tools"]:
                status = "✗" if "error" in tc.get("result", {}) else "✓"
                log(f"  {status} {tc['tool']}")
                if "error" in tc.get("result", {}):
                    log(f"      Error: {tc['result']['error']}")
        
        # Save screenshot - ensure render view is active (chart views can steal focus)
        simple.SetActiveView(view)
        simple.Render(view)
        filename = f"output/assistant_{provider}_{scenario_key}_{i:02d}.png"
        simple.SaveScreenshot(filename, view, ImageResolution=[1024, 768])
        log(f"\nScreenshot: {filename}")
    
    # Scenario summary
    log(f"\n{'=' * 60}")
    log(f"SCENARIO SUMMARY: {scenario['name']}")
    log("=" * 60)
    
    usage = assistant.usage
    log(f"\nLLM Usage:")
    log(f"  Model:    {usage['model']}")
    log(f"  Requests: {usage['requests']}")
    log(f"  Tokens:   {usage['total_tokens']:,} ({usage['input_tokens']:,} in / {usage['output_tokens']:,} out)")
    if "cache_read_tokens" in usage:
        log(f"  Cache:    {usage['cache_read_tokens']:,} read / {usage['cache_creation_tokens']:,} created")
    log(f"  Cost:     ${usage['estimated_cost_usd']:.4f}")
    
    # History
    log(f"\nConversation History:")
    for msg in assistant.get_history():
        role = msg["role"].upper()
        content = msg["content"]
        log(f"  {role}: {content}")

log("=" * 60)
