# ParaView LLM

Natural language interface for CFD post-processing with ParaView.

## Overview

ParaView LLM enables natural language queries for CFD visualization:

```
"show me the vortices"  →  Q-criterion isosurface with optimal threshold
"where is the stagnation point"  →  Find minimum velocity location
"calculate drag and lift"  →  Integrated pressure forces with Cd/Cl
```

## Key Features

- **Intent-Based Architecture**: LLM classifies intent → predefined workflows execute
- **17 CFD Workflows**: Vortex detection, forces, wake analysis, flow features
- **Auto-Detection**: Streamwise direction, field types, optimal thresholds
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
executor = MockLLMExecutor(extended_mcp, "simulation.vtm")
results = executor.execute("vortices_q")  # Uses predefined workflow
```

### Real LLM Mode

```python
from paraview_llm import ExtendedParaViewMCP, IntentExecutor

# Setup
extended_mcp = ExtendedParaViewMCP(base_mcp)
executor = IntentExecutor(extended_mcp, "simulation.vtm")

# LLM classifies intent → workflow executes
results = executor.execute("show me the vortices using Q-criterion")
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      INTENT-BASED ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User: "show me the vortices using Q-criterion"                             │
│                       │                                                     │
│                       ▼                                                     │
│  ┌─────────────────────────────────────────┐                                │
│  │  LLM (Intent Classification)            │  ← Simple task                 │
│  │  "Which of 17 workflows?"               │                                │
│  │  → {"workflow": "vortices_q"}           │                                │
│  └─────────────────────────────────────────┘                                │
│                       │                                                     │
│                       ▼                                                     │
│  ┌─────────────────────────────────────────┐                                │
│  │  WORKFLOWS["vortices_q"]                │  ← Ontology                    │
│  │  → [hide_all, show_data_context,        │                                │
│  │     create_vortex_isosurface, ...]      │                                │
│  └─────────────────────────────────────────┘                                │
│                       │                                                     │
│                       ▼                                                     │
│  Execute deterministically via ExtendedParaViewMCP → ParaView               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Intent-Based?

The LLM's job is **intent classification**, not **workflow composition**:

| Old Approach | New Approach |
|--------------|--------------|
| LLM composes tool sequences | LLM classifies into 17 workflows |
| 34 tools overwhelm LLM | Simple classification task |
| Needed filtering hacks | Clean architecture |
| Fragile | Robust |

## Available Workflows

| Workflow | Description |
|----------|-------------|
| `vortices_q` | Q-criterion vortex visualization |
| `vortices_lambda2` | Lambda2 vortex cores |
| `vortices_swirl` | Swirling strength |
| `vortices_helicity` | Helical structures |
| `stagnation` | Find stagnation point |
| `max_velocity` | Find maximum velocity |
| `pressure` | Pressure distribution |
| `shear_layer` | Shear layer visualization |
| `wake_slice` | Slice through wake |
| `wake_streamlines` | Streamlines in wake |
| `flow_pattern` | Overall flow visualization |
| `forces` | Compute drag/lift |
| `drag_distribution` | Streamwise drag accumulation |
| `lift_distribution` | Spanwise lift distribution |
| `velocity_stats` | Velocity statistics |
| `velocity_distribution` | Velocity histogram |
| `characterize` | Full flow characterization |

## Components

```
paraview_llm/
├── intent_executor.py   # LLM intent classification + workflow execution
├── extended_mcp.py      # CFD analysis & visualization tools (34 tools)
└── mock_llm.py          # Deterministic test sequences (no LLM)
```

### Extended MCP Tools

CFD-specific tools built on trame-llm's ParaViewMCP:

| Category | Tools |
|----------|-------|
| **Analysis** | `find_minimum`, `find_maximum`, `find_high_gradient`, `field_statistics` |
| **Forces** | `compute_forces`, `create_force_distribution_chart` |
| **Vortex** | `create_vortex_isosurface` (Q, λ2, swirl, vorticity, helicity) |
| **Wake** | `detect_wake_region` |
| **Visualization** | `create_slice`, `create_streamlines`, `create_histogram_chart` |
| **Utility** | `detect_streamwise_direction`, `hide_all`, `show_data_context`, `focus_on` |

## Testing

```bash
cd examples/cfd_assistant

# Mock mode (fast, free, deterministic)
pvpython --venv .venv test_e2e.py
# → 17/17 tests, 4.0s

# Real LLM mode (requires OPENAI_API_KEY)
pvpython --venv .venv test_e2e.py --real
# → 17/17 tests, ~12s
```

## Example Outputs

### Vortex Visualization (Q-criterion)
![Vortices](docs/images/vortices_q.png)

### Accumulated Drag Distribution
![Drag Distribution](docs/images/drag_distribution.png)

### Spanwise Lift Distribution  
![Lift Distribution](docs/images/lift_distribution.png)

## Environment Variables

```bash
export OPENAI_API_KEY="sk-..."       # Required for --real mode
export LLM_MODEL="gpt-4o-mini"       # Optional, default: gpt-4o-mini
```

## License

Apache 2.0
