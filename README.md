# ParaView LLM

Natural language interface for CFD post-processing with ParaView.

## Overview

ParaView LLM enables natural language queries for CFD visualization and analysis:

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

```bash
pip install paraview-llm
```

Requires:
- ParaView with Python bindings
- trame-llm
- OpenAI API key (or compatible)

## Quick Start

```python
import asyncio
from paraview import simple
from trame_llm.paraview import ParaViewMCP
from paraview_llm import WorkflowMCP, TrackedLLMClient

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
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    
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
        │    WorkflowMCP        │  12 high-level tools
        │  - show_vortices()    │  Deterministic execution
        │  - show_streamlines() │  Full provenance tracking
        │  - show_slice()       │
        │  - get_ontology()     │  CFD domain knowledge
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   ExtendedParaViewMCP │  CFD analysis tools
        │  - compute_vortex_field()
        │  - detect_wake_region()
        │  - compute_forces()   │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   ParaViewMCP         │  Base ParaView operations
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
| `show_forces()` | Force distribution along body |
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

## Cost Tracking

Every test automatically reports costs:

```
==================================================
COST REPORT
==================================================
Model: gpt-5-mini
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
src/paraview_llm/
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
