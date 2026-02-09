# ParaView LLM

Natural language interface for CFD post-processing with ParaView.

## Overview

ParaView LLM enables natural language queries for CFD visualization:

```
"show me the vortices"       →  Q-criterion isosurface
"show streamlines in wake"   →  Detect wake → seed streamlines there
"what are the forces?"       →  Compute drag and lift
"describe the data"          →  Characterize loaded dataset
```

## Installation

```bash
pip install paraview-llm
```

## Two Approaches

### 1. CFDToolsMCP (Recommended) - Composable Tools for trame_llm

LLM chains query → action tools based on descriptions:

```python
from paraview import simple
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient
from paraview_llm import ExtendedParaViewMCP, CFDToolsMCP

# Load data
reader = simple.OpenDataFile("simulation.vtm")

# Setup MCPs
app = MyTrameApp()
pv_mcp = ParaViewMCP(app)
extended_mcp = ExtendedParaViewMCP(pv_mcp)
cfd_tools = CFDToolsMCP(app, extended_mcp)

# Register with trame_llm
llm_client = LLMClient()
llm_client.register_mcp(pv_mcp)      # Base ParaView tools
llm_client.register_mcp(cfd_tools)   # CFD analysis tools
await llm_client.initialize()

# LLM sees all tools, chains them appropriately
await llm_client.process_prompt("Show streamlines in the wake")
# → detect_wake_region() → create_streamlines(center=wake_centroid)
```

**How it works:**
- Query tools return data: `detect_wake_region()`, `find_stagnation_point()`
- Action tools use that data: `create_streamlines(center=...)`, `create_vortex_isosurface()`
- Tool docstrings include workflow hints that guide the LLM

### 2. CFDAssistant (Legacy) - Hardcoded Workflows

Intent classification → deterministic workflow execution:

```python
from paraview_llm import ExtendedParaViewMCP, CFDAssistant

assistant = CFDAssistant(extended_mcp, base_mcp, reader_name)
result = assistant.query("show me the vortices")
# → Classifies as VISUALIZE_VORTICES → runs predefined steps
```

## Architecture

### CFDToolsMCP - LLM-Driven Composition

```
User: "Show streamlines in the wake"
         │
         ▼
┌─────────────────────────────────────┐
│  LLM reads tool descriptions        │
│  Picks: detect_wake_region          │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  detect_wake_region()               │
│  Returns: {wake_centroid, bounds}   │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  LLM chains next tool               │
│  create_streamlines(center=...)     │
└─────────────────────────────────────┘
         │
         ▼
    Visualization created
```

**Key insight:** Tool docstrings guide chaining:
```python
def detect_wake_region() -> dict:
    """Detect wake region behind body.
    
    USE RESULT FOR:
    - create_streamlines(center=result["wake_centroid"])
    - create_body_slice(location=result["wake_centroid"][0])
    """
```

## CFD Tools

### Query Tools (return data)

| Tool | Returns |
|------|---------|
| `describe_dataset` | Fields, bounds, mesh stats |
| `detect_wake_region` | wake_centroid, wake_bounds, suggested_radius |
| `detect_streamwise_direction` | streamwise axis, freestream_velocity |
| `find_stagnation_point` | location, velocity value |
| `find_maximum(field)` | location, value |
| `find_minimum(field)` | location, value |
| `get_field_statistics(field)` | min, max, mean, std |

### Action Tools (create visualizations)

| Tool | Creates |
|------|---------|
| `create_streamlines(center, radius)` | Flow streamlines |
| `create_vortex_isosurface(method)` | Q-criterion/λ2/vorticity isosurface |
| `create_body_slice(normal, color_by)` | Slice through body region |
| `compute_forces()` | Drag/lift calculation |
| `set_streamwise_view()` | Camera along flow |
| `show_body_context(opacity)` | Transparent body surface |

## Testing

```bash
cd examples/cfd_assistant

# Test CFDToolsMCP with trame_llm
pvpython --venv .venv test_cfd_tools.py

# Test legacy CFDAssistant workflows  
pvpython --venv .venv test_all_workflows.py
```

## Design Philosophy

**Ontology-informed, not ontology-driven:**

The CFD domain knowledge (what a wake is, how to detect vortices, when to use Q-criterion) is encoded in tool descriptions, not runtime reasoning. This is simpler and works well in practice.

If LLM selection proves unreliable for specific cases, deterministic intent rules can be added as a fallback layer.

## License

Apache 2.0
