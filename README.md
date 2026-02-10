# ParaView LLM

Natural language interface for CFD post-processing with ParaView.

## Overview

ParaView LLM enables natural language queries for CFD visualization and analysis:

```
"show me the vortices"                →  Q-criterion isosurface
"show streamlines in the wake"        →  Detect wake, seed streamlines
"analyze the wake and explain drag"   →  Multiple visualizations + physics explanation
```

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
    llm = TrackedLLMClient(max_iteractions=10)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    # Run query
    await llm.process_prompt("Show vortices and explain what I'm seeing")
    
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
        │   LLM (Intent Match)  │  Picks which workflow tools to call
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │    WorkflowMCP        │  11 high-level tools
        │  - show_vortices()    │  Deterministic execution
        │  - show_streamlines() │  No LLM during execution
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

1. **LLM does intent matching only** - Picks which workflow to run
2. **Workflows execute deterministically** - No LLM during execution
3. **Ontology provides explanations** - Domain knowledge for interpreting results
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
| `save_screenshot(filename)` | Save current view |
| `set_view(direction)` | Set camera angle |

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

The LLM can call `get_ontology()` to retrieve this knowledge when explaining visualizations.

## Cost Tracking

Every test automatically reports costs:

```
==================================================
COST REPORT
==================================================
Model: gpt-5-mini
LLM calls: 15
Tool calls: 14
Input tokens: 42,967
Output tokens: 2,661
Total tokens: 45,628
Estimated cost: $0.008042
==================================================
```

## Testing

```bash
cd examples/cfd_assistant

# Test all workflows
pvpython --venv .venv test_workflows.py

# Test ontology-based explanations
pvpython --venv .venv test_ontology.py

# Test multi-step analysis
pvpython --venv .venv test_analysis.py
```

## Files

```
src/paraview_llm/
├── __init__.py          # Package exports
├── workflow_mcp.py      # High-level workflow tools (11 tools)
├── workflows.py         # Workflow implementations
├── extended_mcp.py      # CFD analysis tools (40+ tools)
├── ontology.json        # CFD domain knowledge
└── cost_tracker.py      # Token/cost tracking

examples/cfd_assistant/
├── test_workflows.py    # Test all 5 workflows
├── test_ontology.py     # Test explanation capability
├── test_analysis.py     # Test multi-step exploration
└── test.vtm             # Sample CFD dataset
```

## License

Apache 2.0
