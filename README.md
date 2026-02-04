# ParaView LLM

Natural language interface for CFD post-processing with ParaView.

## Overview

ParaView LLM enables natural language queries for CFD visualization:

```
"show me the vortices"  →  Q-criterion isosurface with optimal threshold
"where is the stagnation point"  →  Slice at minimum velocity location
"calculate drag and lift"  →  Integrated pressure forces with Cd/Cl
```

## Key Features

- **Domain-Aware**: CFD ontology guides tool selection (vortex detection, forces, flow features)
- **Auto-Detection**: Streamwise direction, field types, optimal thresholds
- **Single-Shot Execution**: One LLM call generates complete tool plan
- **Mock Mode**: Fast, free, deterministic testing without LLM

## Installation

```bash
pip install paraview-llm

# With OpenAI support
pip install paraview-llm[openai]
```

## Quick Start

### Mock Mode (Testing)

```python
from paraview import simple
from trame_llm.paraview import ParaViewMCP
from paraview_llm import ExtendedParaViewMCP, MockLLMExecutor

# Load data
reader = simple.OpenDataFile("simulation.vtm")

# Setup MCP
base_mcp = ParaViewMCP(app)
extended_mcp = ExtendedParaViewMCP(base_mcp)

# Execute with mock (no LLM calls)
mock = MockLLMExecutor(extended_mcp, "simulation.vtm")
results = mock.execute("vortices_q")  # Uses pre-defined tool sequence
```

### Single-Shot Mode (Real LLM)

```python
from paraview_llm import ExtendedParaViewMCP, SingleShotExecutor

# Setup
extended_mcp = ExtendedParaViewMCP(base_mcp)
executor = SingleShotExecutor(extended_mcp, "simulation.vtm")

# One LLM call → tool plan → local execution
results = executor.execute("show me the vortices using Q-criterion")
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXECUTION MODES                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MOCK MODE (CI/development) ─────────────────────────────────────────────   │
│                                                                             │
│    Query Key ──▶ MockLLMExecutor ──▶ ExtendedMCP ──▶ ParaView               │
│    "vortices_q"   (lookup table)     (CFD tools)                            │
│                                                                             │
│    Cost: $0 | Time: ~0.2s/query | Use: Testing, CI                          │
│                                                                             │
│  SINGLE-SHOT MODE (production) ──────────────────────────────────────────   │
│                                                                             │
│    Natural     ┌─────────────┐   Enriched    ┌─────────┐   Tool             │
│    Language ──▶│ Orchestrator│──▶ Prompt  ──▶│ LLM API │──▶ Plan            │
│    Query       │ (ontology)  │   (domain     │(1 call) │   (execute         │
│                └─────────────┘    hints)     └─────────┘    locally)        │
│                                                                             │
│    Cost: ~$0.01/query | Time: ~2s/query | Use: Production                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Single-Shot (Not In-Loop)?

In-loop execution (multiple LLM round-trips with intermediate results) was removed because:

1. **Good ontology = correct first time**: If tools are well-designed with proper defaults, the LLM doesn't need to self-correct
2. **Self-correction masks problems**: Needing retries indicates ontology/tool gaps that should be fixed
3. **10x faster, 5x cheaper**: Single-shot is equivalent for deterministic queries

If a query fails, the fix is improving the ontology or tools—not adding runtime patching.

## Components

```
paraview_llm/
├── ontology/
│   └── cfd.json              # Domain knowledge: concepts, visualizations
├── orchestrator.py           # Enriches queries with ontology hints
├── extended_mcp.py           # CFD analysis & visualization tools
├── mock_llm.py              # Deterministic test sequences  
└── single_shot.py           # Single LLM call executor
```

### Ontology (`cfd.json`)

Maps CFD concepts to detection methods and visualizations:

```json
{
  "concepts": {
    "vortex_core": {
      "definition": "Region of concentrated rotation",
      "keywords": ["vortex", "vortices", "swirl", "rotation"],
      "detection": {
        "tool": "create_vortex_isosurface",
        "method": "q_criterion"
      }
    },
    "stagnation_point": {
      "definition": "Location where velocity is zero",
      "detection": {
        "tool": "find_minimum",
        "field_type": "velocity"
      }
    }
  }
}
```

### Orchestrator

Enriches user queries with domain knowledge:

```
Input:  "show me the vortices"

Output (enriched prompt):
  USER REQUEST: show me the vortices
  
  RELEVANT CFD CONCEPTS:
  - vortex_core: Region of concentrated rotation
    → create_vortex_isosurface(method="q_criterion", proxy_name="data")
  
  WORKFLOW:
  1. hide_all()
  2. show_data_context(proxy_name="data", opacity=0.15)
  3. create_vortex_isosurface(...)
  4. focus_on(proxy_name=result)
```

### Extended MCP Tools

CFD-specific tools built on trame-llm's ParaViewMCP:

| Category | Tools |
|----------|-------|
| **Analysis** | `find_minimum`, `find_maximum`, `find_high_gradient`, `field_statistics`, `field_histogram` |
| **Forces** | `compute_forces`, `create_force_distribution_chart` |
| **Vortex** | `create_vortex_isosurface` (Q, λ2, swirl, vorticity, helicity) |
| **Visualization** | `create_slice`, `create_streamlines`, `create_histogram_chart` |
| **Utility** | `detect_streamwise_direction`, `hide_all`, `show_data_context`, `focus_on` |

### Auto-Detection Features

| Feature | Method |
|---------|--------|
| **Streamwise direction** | Magnitude-weighted velocity average |
| **Span direction** | Largest extent perpendicular to streamwise |
| **Field types** | Pattern matching ("U", "Velocity" → velocity) |
| **Vortex thresholds** | Percentile-based or 1% of min (λ2) |
| **Force reference values** | Auto-detect freestream velocity, frontal area |

## Testing

```bash
cd examples/cfd_assistant

# Mock mode (fast, free, deterministic)
pvpython test_e2e.py
# → 16/16 tests, 3.7s

# Real LLM mode (requires OPENAI_API_KEY)
pvpython test_e2e.py --real
# → 16/16 tests, ~30s
```

### Test Coverage

| Test | Visualization |
|------|---------------|
| `shear_layer` | Vorticity isosurface |
| `stagnation` | Slice at min velocity |
| `flow_pattern` | Streamlines from stagnation |
| `pressure` | Pressure slice |
| `velocity_stats` | Histogram data (JSON) |
| `velocity_distribution` | Histogram chart |
| `forces` | Cd/Cl calculation |
| `drag_distribution` | Chordwise drag chart |
| `lift_distribution` | Spanwise lift chart |
| `max_velocity` | Slice at max velocity |
| `wake_slice` | X-normal slice |
| `vortices_q` | Q-criterion isosurface |
| `vortices_lambda2` | λ2 isosurface |
| `vortices_swirl` | Swirling strength isosurface |
| `vortices_helicity` | Helicity isosurface |
| `characterize` | Multi-tool analysis |

## Example Outputs

### Vortex Visualization (Q-criterion)
![Vortices](docs/images/vortices_q.png)

### Accumulated Drag Distribution
![Drag Distribution](docs/images/drag_distribution.png)

### Spanwise Lift Distribution  
![Lift Distribution](docs/images/lift_distribution.png)

## Environment Variables

```bash
export OPENAI_API_KEY="sk-..."      # Required for --real mode
export OPENAI_MODEL="gpt-4o"        # Optional, default: gpt-4o
```

## License

Apache 2.0
