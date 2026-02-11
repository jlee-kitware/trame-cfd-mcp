# trame-cfd-mcp

CFD workflow tools for ParaView via MCP (Model Context Protocol).

Extends [trame-llm](https://github.com/Kitware/trame-llm)'s ParaViewMCP with CFD-specific visualization workflows.

## Overview

trame-cfd-mcp enables natural language queries for CFD visualization and analysis:

```
"show me the vortices"                →  Q-criterion isosurface
"show streamlines in the wake"        →  Detect wake, seed streamlines
"analyze the wake and explain drag"   →  Multiple visualizations + physics explanation
```

## What the LLM Does

The LLM acts as a **CFD analyst**, not just a command translator:

1. **Multi-step reasoning** - Decides what visualizations to create and in what order
2. **Parameter selection** - Chooses methods (q_criterion vs lambda2), locations (wake vs center)
3. **Ontology-driven explanation** - Uses CFD domain knowledge to explain what results mean
4. **Follow-up analysis** - Reasons about results, identifies patterns, suggests next steps

**What's deterministic:** The workflow implementations themselves. Once the LLM decides to call `show_vortices(method="q_criterion")`, the execution is pure Python with no LLM involvement.

## Installation

### Prerequisites

1. **ParaView** with Python bindings (pvpython)
   - Download from [paraview.org](https://www.paraview.org/download/) or build from source
   
2. **trame-llm** - LLM orchestration library
   ```bash
   # Clone and install trame-llm (not yet on PyPI)
   git clone https://github.com/Kitware/trame-llm.git
   cd trame-llm
   pip install -e .
   ```

3. **OpenAI API key**
   ```bash
   export OPENAI_API_KEY=sk-your-key-here
   ```

### Install trame-cfd-mcp

```bash
git clone https://github.com/Kitware/trame-cfd-mcp.git
cd trame-cfd-mcp
pip install -e ".[openai]"
```

## Running the Examples

```bash
cd examples/cfd_assistant

# Create virtual environment for pvpython
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install openai python-dotenv

# Copy and edit .env
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# Run with pvpython (NOT regular python)
/path/to/paraview/bin/pvpython --venv .venv test_analysis.py
```

**Important:** You must use `pvpython` (ParaView's Python) with the `--venv` flag to load packages from your virtual environment. Regular Python won't have ParaView bindings.

## Quick Start

```python
import asyncio
from paraview import simple
from trame_llm.paraview import ParaViewMCP
from trame_cfd_mcp import WorkflowMCP, TrackedLLMClient

# Minimal app interface for ParaViewMCP
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

async def main():
    # Load data
    reader = simple.OpenDataFile("simulation.vtm")
    simple.UpdatePipeline()
    
    # Setup view
    view = simple.CreateRenderView()
    simple.SetActiveView(view)
    simple.Show(reader, view)
    
    # Create MCP stack
    app = MinimalApp()
    base_mcp = ParaViewMCP(app)          # from trame-llm
    workflow_mcp = WorkflowMCP(base_mcp)  # from trame-cfd-mcp
    
    # Create LLM client with cost tracking
    llm = TrackedLLMClient(max_iteractions=20)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    # Run analysis
    await llm.process_prompt(
        "Analyze the wake structure and explain how it relates to drag. "
        "Save visualizations to output/"
    )
    
    # Print cost report
    llm.print_report()

asyncio.run(main())
```

## Architecture

```
User Query: "Analyze the wake and explain drag"
                    │
                    ▼
        ┌───────────────────────┐
        │         LLM           │  Multi-step reasoning
        │  - What to visualize  │  Parameter selection
        │  - What order         │  Explanation generation
        │  - How to explain     │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │    WorkflowMCP        │  13 high-level tools    ─┐
        │  - show_vortices()    │  Deterministic execution  │
        │  - show_streamlines() │  Full provenance tracking │
        │  - show_slice()       │                           │ trame-cfd-mcp
        │  - get_ontology()     │  CFD domain knowledge     │
        └───────────────────────┘                          ─┘
                    │
                    ▼
        ┌───────────────────────┐
        │   ExtendedParaViewMCP │  CFD analysis tools      ─┐
        │  - compute_vortex_field()                         │ trame-cfd-mcp
        │  - detect_wake_region()                           │
        │  - compute_forces()   │                          ─┘
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   ParaViewMCP         │  Base ParaView operations ─ trame-llm
        │  (from trame-llm)     │
        └───────────────────────┘
                    │
                    ▼
                ParaView
```

### Key Design Principles

1. **LLM reasons, workflows execute** - LLM decides what to do; Python does it deterministically
2. **Ontology for explanation** - Domain knowledge helps LLM explain physics, not control execution
3. **Full provenance** - Every workflow returns dataset, filter chain, parameters, and claims
4. **Cost tracking built-in** - Monitor token usage and costs

## Workflow Tools

| Tool | Description |
|------|-------------|
| `list_data()` | List loaded data sources |
| `get_fields()` | Get available fields with ranges |
| `analyze_data()` | Characterize dataset, recommend workflows |
| `show_vortices(method)` | Q-criterion, vorticity, or lambda2 isosurface |
| `show_streamlines()` | Flow streamlines in wake region |
| `show_slice(location, normal)` | Slice through wake or domain center |
| `show_histogram(field)` | Field distribution chart |
| `show_forces()` | Force distribution along body (uses projected frontal area for Cd) |
| `show_boundary_layer(x_location)` | Boundary layer profile with δ, δ*, θ, H (Antares methodology) |
| `show_flow_topology()` | Vortex core lines via VTK VortexCores filter |
| `get_ontology()` | CFD domain knowledge for explanations |
| `save_screenshot(filename)` | Save current view (3D or chart) |
| `save_state(filename)` | Save full ParaView state for reproducibility |
| `set_view(direction)` | Set camera angle |

## Provenance

Every workflow returns structured provenance for traceability:

```json
{
  "status": "created",
  "type": "vortex_isosurface",
  "provenance": {
    "dataset": "simulation.vtm",
    "filter_chain": ["MergeBlocks", "Gradient", "Contour"],
    "arrays_used": ["Velocity", "Q"],
    "parameters": {
      "method": "q_criterion",
      "threshold": 28.06,
      "ContourBy": "Q"
    }
  },
  "interpretation": {
    "field": "Q",
    "threshold": 28.06,
    "claim": "Q Criterion > 0 indicates vortex cores where rotation dominates strain"
  }
}
```

Full results are saved to JSON files for inspection.

## Ontology

The ontology provides CFD domain knowledge that helps the LLM explain results:

```json
{
  "flow_features": {
    "vortex_isosurface": {
      "methods": {
        "q_criterion": {
          "interpretation": "Q > 0 indicates rotation dominates strain, identifying vortex cores"
        }
      }
    }
  },
  "causal_relationships": {
    "drag_increase": [
      {"cause": "larger_wake", "effect": "lower_base_pressure"},
      {"cause": "lower_base_pressure", "effect": "higher_pressure_drag"}
    ]
  }
}
```

The LLM retrieves this via `get_ontology()` when explaining visualizations. The ontology is for **explanation only** - it doesn't control workflow execution.

## Key Analysis Features

### Boundary Layer Analysis

`show_boundary_layer(x_location)` provides comprehensive boundary layer characterization:

- **Surface-normal probing**: Automatically detects body surface and probes perpendicular to it
- **Multiple edge detection criteria** (following Antares/CERFACS methodology):
  - 99% of local edge velocity
  - Haase diagnostic function: y × |du/dy| maximum
- **Integral quantities**: δ (thickness), δ* (displacement), θ (momentum), H (shape factor)
- **Flow state indication**: H ≈ 1.3-1.4 turbulent, H ≈ 2.6 laminar

### Projected Frontal Area

`compute_projected_area()` uses rasterization for accurate reference area:

- Renders body surface with orthographic projection aligned with flow
- Counts non-background pixels to compute area
- Handles complex geometries, hidden surfaces, and concavities
- Used automatically by `compute_forces()` for accurate Cd/Cl

### Flow Topology

`show_flow_topology()` extracts vortex core lines using VTK's VortexCores filter, which is more appropriate for external aerodynamics than critical point analysis (which finds spurious points on no-slip walls).

## Cost Tracking

Every test automatically reports costs:

```
==================================================
COST REPORT
==================================================
Model: gpt-4o-mini
LLM calls: 13
Tool calls: 12
Input tokens: 39,207
Output tokens: 2,558
Total tokens: 41,765
Estimated cost: $0.007416
==================================================
```

## Testing

```bash
cd examples/cfd_assistant

# Test individual workflows
pvpython --venv .venv test_workflows.py

# Test ontology-based explanations
pvpython --venv .venv test_ontology.py

# Test multi-step analysis (full reasoning)
pvpython --venv .venv test_analysis.py
```

All tests save:
- Screenshots to `output/*.png`
- Full provenance to `output/*_results.json`

## Files

```
src/trame_cfd_mcp/
├── __init__.py          # Package exports
├── workflow_mcp.py      # High-level workflow tools (12 tools)
├── workflows.py         # Workflow implementations
├── extended_mcp.py      # CFD analysis tools (40+ tools)
├── ontology.json        # CFD domain knowledge
└── cost_tracker.py      # Token/cost tracking

examples/cfd_assistant/
├── test_utils.py        # Shared test utilities
├── test_workflows.py    # Test individual workflows
├── test_ontology.py     # Test explanation capability
├── test_analysis.py     # Test multi-step reasoning
└── test.vtm             # Sample CFD dataset
```

## License

BSD 3-Clause (compatible with ParaView/VTK)
