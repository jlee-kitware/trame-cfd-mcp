# Architecture

## Design Evolution

We tried several approaches before arriving at the current architecture:

| Approach | Problem |
|----------|---------|
| LLM orchestrates 40+ tools | Skips steps, wrong order, burns tokens |
| LLM with detailed instructions | Still unreliable, 1M+ tokens for simple tasks |
| Ontology-driven execution | RAG not deterministic, wrong workflow retrieval |
| Intent classification → workflow | Works but limited to predefined intents |
| **Workflow tools + ontology for explanation** | ✅ Reliable execution + rich explanations |

## Key Insight: Separate Execution from Explanation

**Ontology is for EXPLANATION, not EXECUTION.**

- **Execution**: Hardcoded workflows in Python. Deterministic, no LLM, no RAG.
- **Explanation**: Ontology provides CFD domain knowledge the LLM uses to interpret results.

This separation is critical:
- Execution must be reliable → hardcode it
- Explanation benefits from LLM reasoning → give it domain knowledge

## Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  User Query                                                 │
│  "Analyze the wake and explain how it affects drag"         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM (Intent Matching)                                      │
│                                                             │
│  Sees 11 workflow tools with clear descriptions             │
│  Decides: show_streamlines, show_slice, show_forces,        │
│           get_ontology, save_screenshot                     │
│                                                             │
│  Multiple tool calls in one response (batched execution)    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  WorkflowMCP (Deterministic Execution)                      │
│                                                             │
│  Each workflow:                                             │
│  1. Gets data reader (explicit, not active source)          │
│  2. Calls analysis tools (compute_*, detect_*)              │
│  3. Creates visualization (Contour, Slice, etc.)            │
│  4. Returns rich result with analysis data                  │
│                                                             │
│  NO LLM involved during execution                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM (Explanation)                                          │
│                                                             │
│  Combines:                                                  │
│  - Workflow results (threshold, location, ranges)           │
│  - Ontology knowledge (what Q-criterion means)              │
│  - CFD understanding (wake → base pressure → drag)          │
│                                                             │
│  Produces coherent explanation of the physics               │
└─────────────────────────────────────────────────────────────┘
```

## Why This Works

### 1. Workflow Tools Are Self-Contained

Each workflow tool (e.g., `show_vortices`) handles everything:
- Finding the right proxy (not relying on active source)
- Computing derived fields (Q-criterion, vorticity)
- Creating visualization (Contour with correct properties)
- Setting up display (colors, camera)
- Returning analysis data (threshold, range, location)

The LLM just needs to pick the right tool, not orchestrate steps.

### 2. Ontology Provides Domain Knowledge

The ontology is a JSON file with CFD knowledge:
- What each visualization method means
- Causal relationships (wake → drag)
- Interpretation guidance

The LLM retrieves it via `get_ontology()` tool when it needs to explain results.
This separates execution (deterministic) from explanation (LLM strength).

### 3. Rich Return Values Enable Reasoning

Workflows return data and provenance, not just "done":

```python
{
    "status": "created",
    "type": "vortex_isosurface", 
    "method": "q_criterion",
    "proxy_name": "Contour1",
    "result": {
        "field": "Q",
        "threshold": 28.06,
        "field_range": [-23929, 75723]
    },
    "provenance": {
        "filter_chain": [...],  # ParaView filters created
        "analysis": [...]       # Why those parameters
    },
    "tip": "To show MORE structures: update_list_property(...)"
}
```

The LLM can use this to:
- Answer follow-up questions ("what threshold was used?")
- Explain the visualization ("threshold 28 shows strongest vortex cores")
- Suggest next steps ("try lower threshold to see weaker structures")

## Component Responsibilities

### WorkflowMCP (trame-cfd-mcp)

High-level interface exposed to LLM. Key tool categories:
- Discovery: `list_data`, `get_fields`, `analyze_data`
- Visualization: `show_vortices`, `show_streamlines`, `show_slice`, `show_histogram`, `show_forces`, `show_boundary_layer`, `show_flow_topology`
- Refinement: `update_representation`, `update_color`, `update_display_property`, `show_or_hide`
- Knowledge: `get_ontology`
- Utilities: `save_screenshot`, `set_view`, `delete_filter`, `clear_all_filters`

### CFDWorkflows (trame-cfd-mcp)

Implementation of workflow tools. Each method:
1. Gets data reader explicitly (not active source)
2. Calls CFDAnalysis analysis methods
3. Creates ParaView filters/sources
4. Returns rich result dict

### CFDAnalysis (trame-cfd-mcp)

CFD analysis tools in two categories:

**Compute tools** (return data, no visualization):
- `compute_vortex_field` → Q-criterion, vorticity, or lambda2 field + auto-threshold
- `compute_forces` → Cd, Cl using projected frontal area
- `compute_projected_area` → Rasterized frontal area for accurate Cd
- `compute_boundary_layer_profile` → δ, δ*, θ, H via surface-normal probing
- `compute_flow_topology` → Vortex core lines via VTK VortexCores
- `detect_wake_region` → Wake centroid and bounds
- `detect_streamwise_direction` → Primary flow axis from velocity field
- `field_statistics`, `field_histogram` → Field KPIs

**Visualization tools** (create ParaView objects):
- `create` → generic filter creation
- `update_property` → set filter properties
- `focus_on` → camera setup

### Server-Side Analysis Architecture

All analysis that touches field data runs **server-side via ProgrammableFilter**. No field data moves from pvserver to the client. This is the core requirement for scalability with remote pvserver and large simulation datasets.

**Data flow:**
```
pvserver: raw fields → ProgrammableFilter (numpy analysis) → small vtkTable result
client:   fetch_table() → Python dict of scalar KPIs only
```

**Key functions in `trame_llm.paraview`:**

| Function | Purpose |
|---|---|
| `get_field_names(proxy)` | Field names + component counts via `GetDataInformation()` — zero data movement |
| `run_server_script(proxy, script_path, params)` | Embeds a `.py` script into a ProgrammableFilter; executes on pvserver |
| `fetch_table(proxy)` | Fetches a small vtkTable result (KPIs only) to client |
| `fetch_data(proxy)` | **Retained for Catalyst Live path only** — never called on full field data |

**Server scripts** (`src/trame_cfd_mcp/server_scripts/`):

Each script runs entirely on pvserver. Parameters are injected as Python assignments at the top. Output is always a small `vtkTable` of scalar KPIs.

| Script | Inputs | Outputs |
|---|---|---|
| `field_statistics.py` | `FIELD_NAME`, `LOCATION` | min, max, mean, std |
| `field_histogram.py` | `FIELD_NAME`, `LOCATION`, `NUM_BINS` | bin_center[], count[] |
| `vortex_threshold.py` | `FIELD_NAME`, `METHOD`, `PERCENTILE` | threshold, field_min, field_max |
| `force_integration.py` | `PRESSURE_FIELD`, `STREAMWISE_IDX`, etc. | Fx, Fy, Fz, Cd, Cl |
| `force_distribution.py` | `PRESSURE_FIELD`, `FORCE_IDX`, `DIST_IDX`, `NUM_BINS` | station[], sectional_force[] |
| `detect_streamwise.py` | `VELOCITY_FIELD` | streamwise axis/direction, freestream velocity |
| `detect_wake.py` | `VELOCITY_FIELD`, `VELOCITY_DEFICIT`, etc. | wake centroid, bounds |
| `boundary_layer.py` | `VELOCITY_FIELD`, `SURFACE_POINT`, `SURFACE_NORMAL`, `PROBE_LENGTH` | y[], u[], δ, δ*, θ, H |
| `find_region.py` | `FIELD_NAME`, `MODE` (min/max) | location (x,y,z), value |
| `centroid.py` | (none) | centroid (x,y,z), bounds |

**What legitimately uses `fetch_data`:**
- `compute_boundary_layer_profile`: fetches a small 2D airfoil cross-section (plane cut of body surface) to determine surface point and normal for probe injection — not field data
- Catalyst Live path: in-situ data is already reduced at the simulation

**`ensure_flat_input` behaviour:**
Uses `GetDataInformation().GetDataSetTypeAsString()` to detect composite datasets — no data movement. Returns `(flat_proxy, None, cleanup)`. Callers that previously used the returned `data` object now use `get_field_names()` or `GetDataInformation()` directly.

### Catalyst Live Data Flow

Catalyst Live is a fundamentally different data path from remote pvserver. Data movement rules differ because Catalyst reduces data **in-situ at the simulation** before it ever reaches the client.

**Catalyst Live flow:**
```
simulation (running) → Catalyst in-situ pipeline → ExtractCatalystData proxy (pvserver)
                                                   ↓
                                          WorkflowMCP / CFDAnalysis
                                          (same server-side analysis path)
```

The `ExtractCatalystData` proxy is created by the Live connection and lives on the pvserver side. It is small by design — the simulation's Catalyst pipeline already performs in-situ reduction (surface extraction, sampling, monitors). Crucially:

- **`fetch_data` is legitimate on Catalyst Live sources** — the extracted data is already reduced; fetching it does not move large simulation fields
- **CFDAnalysis still runs server-side** — once extracted, the Live source is a normal pvserver proxy and all `run_server_script` / ProgrammableFilter analysis applies identically
- **`fetch_data` must NOT be called on full pvserver simulation data** — only on extracted/reduced Catalyst outputs

**Live-specific tools** (`CFDChatMCP` in `catalyst_live.py`):

| Tool | What it does |
|---|---|
| `connect_live(host, port)` | Opens Catalyst Live connection, creates `_live_link` |
| `extract_live_data(name)` | Calls `ExtractCatalystData` → small proxy on pvserver |
| `extract_monitors(channel)` | Extracts residual/monitor data for convergence tracking |
| `pause_simulation()` / `resume_simulation()` | Controls simulation time stepping |
| `get_live_status()` | Returns simulation time, iteration, connection state |

**Data movement summary across all paths:**

| Path | Full field data | Fetch use | Analysis location |
|---|---|---|---|
| Remote pvserver | Stays on server | ❌ never | pvserver ProgrammableFilter |
| Catalyst Live extracted | Reduced in-situ | ✅ OK (small) | pvserver ProgrammableFilter |
| BL airfoil section | Small 2D geometry | ✅ OK (tiny) | Client (for probe injection) |

### Provenance Tracking

Full reproducibility through hybrid provenance architecture:

**Filter Chain** (from ParaView):
- `extract_filter_chain(proxy)` walks `proxy.Input` recursively
- Extracts filter type, input/output names, key parameters
- Always reflects current state (auto-tracks refinements)

**Analysis Log** (from CFDAnalysis):
- `_log_analysis(type, **details)` called for computational decisions
- Records reasoning ParaView doesn't know:
  - Why threshold = 28.06? (50th percentile of Q > 0)
  - Where is wake? (velocity < 50% freestream)
  - How was seed placed? (from wake centroid)

**Workflow Pattern**:
```python
def show_vortices(self, ...):
    self._mcp.clear_analysis_log()  # Fresh start
    
    vortex = self._mcp.compute_vortex_field(...)  # Logs auto_threshold
    contour = simple.Contour(...)  # ParaView tracks
    
    return {
        "provenance": {
            "filter_chain": self._mcp.extract_filter_chain(contour),
            "analysis": self._mcp.get_analysis_log()
        }
    }
```

**Example Provenance**:
```json
{
  "filter_chain": [
    {"filter": "XMLMultiBlockDataReader", "output": "Reader1", "params": {"FileName": "test.vtm"}},
    {"filter": "MergeBlocks", "output": "MergeBlocks1", "input": "Reader1"},
    {"filter": "Gradient", "output": "Gradient1", "input": "MergeBlocks1", 
     "params": {"ScalarArray": "Velocity", "ComputeQCriterion": 1}},
    {"filter": "Contour", "output": "Contour1", "input": "Gradient1",
     "params": {"ContourBy": "Q", "Isosurfaces": [28.06]}}
  ],
  "analysis": [
    {"type": "auto_threshold", "method": "percentile", "percentile": 50.0,
     "field_range": [-23929, 75723], "positive_count": 9257, "result": 28.06}
  ]
}
```

**Benefits**:
- No duplicate tracking (ParaView tracks filters)
- Refinements automatically captured on re-extract
- Full reproducibility: filter_chain + analysis = complete provenance

### Ontology (trame-cfd-mcp, ontology.json)

**Used for EXPLANATION only, not execution.**

CFD domain knowledge that helps LLM interpret results:
- `flow_features` → What each visualization type means (Q > 0 = vortex core)
- `causal_relationships` → What causes drag/lift changes (wake → base pressure → drag)
- `analysis_recommendations` → Which tools for which questions

The LLM calls `get_ontology()` when it needs to explain results. The ontology never influences which workflow runs or how it executes.

### ParaViewMCP (trame-llm)

Base ParaView operations from trame-llm. Provides low-level tools:
- `list_existing_proxies`, `activate_proxy` - proxy management
- `list_properties`, `update_property` - property inspection/modification
- `create` - generic filter/source creation
- View and camera control

WorkflowMCP builds on top of ParaViewMCP, adding CFD-specific high-level workflows.

### TrackedLLMClient

Wrapper around trame-llm's LLMClient that tracks:
- Token usage (input, output)
- Tool calls
- Estimated cost

## Cost Analysis

Typical costs for different query types:

| Query Type | Tool Calls | Tokens | Cost |
|------------|------------|--------|------|
| Simple visualization | 2-3 | ~5K | ~$0.001 |
| Visualization + explanation | 3-4 | ~15K | ~$0.003 |
| Multi-step analysis | 10-15 | ~45K | ~$0.008 |

Compare to LLM orchestrating 40+ tools: 200K+ tokens, $0.04+

## Adding New Workflows

1. Add method to `CFDWorkflows` class in `workflows.py`
2. Add tool to `WorkflowMCP.get_mcp()` tools list
3. Update ontology if new flow feature type
4. Test with natural language prompt

Example:

```python
# In workflows.py
def show_pressure_contours(self, num_contours: int = 10) -> dict:
    """Show pressure contours on body surface."""
    proxy = self._get_data_reader()
    # ... implementation
    return {
        "status": "created",
        "type": "pressure_contours",
        "num_contours": num_contours,
        # ... analysis data
    }

# In workflow_mcp.py get_mcp()
"tools": [
    # ... existing tools
    self._workflows.show_pressure_contours,
]
```

## What This Architecture Cannot Do

- **Novel tool combinations** - Only predefined workflows
- **Adaptive debugging** - Won't figure out why a workflow failed
- **Complex multi-case comparison** - Need to add comparison workflows

These are intentional limitations. The value is reliable execution + rich explanation, not unbounded exploration.
