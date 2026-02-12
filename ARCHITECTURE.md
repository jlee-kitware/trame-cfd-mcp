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

Workflows return analysis data, not just "done":

```python
{
    "status": "created",
    "type": "vortex_isosurface", 
    "method": "q_criterion",
    "threshold": 28.06,
    "field_range": [-23929, 75723],
    "color_by": "Velocity",
    "tip": "Threshold auto-computed. Adjust percentile for more/fewer structures."
}
```

The LLM can use this to:
- Answer follow-up questions ("what threshold was used?")
- Explain the visualization ("threshold 28 shows strongest vortex cores")
- Suggest next steps ("try lower threshold to see weaker structures")

## Component Responsibilities

### WorkflowMCP

High-level interface exposed to LLM. 11 tools:
- Discovery: `list_data`, `get_fields`, `analyze_data`
- Visualization: `show_vortices`, `show_streamlines`, `show_slice`, `show_histogram`, `show_forces`
- Knowledge: `get_ontology`
- Utilities: `save_screenshot`, `set_view`

### CFDWorkflows

Implementation of workflow tools. Each method:
1. Gets data reader explicitly (not active source)
2. Calls CFDAnalysis analysis methods
3. Creates ParaView filters/sources
4. Returns rich result dict

### CFDAnalysis

40+ CFD analysis tools. Two categories:

**Compute tools** (return data, no visualization):
- `compute_vortex_field` → Q-criterion, vorticity, or lambda2 field
- `compute_forces` → Cd, Cl using projected frontal area
- `compute_projected_area` → Rasterized frontal area for accurate Cd
- `compute_boundary_layer_profile` → δ, δ*, θ, H via surface-normal probing
- `compute_flow_topology` → Vortex core lines via VTK VortexCores
- `detect_wake_region` → Wake centroid and bounds

**Visualization tools** (create ParaView objects):
- `create` → generic filter creation
- `update_property` → set filter properties
- `focus_on` → camera setup

The separation between compute and visualization tools allows workflows to get data first, then create appropriate visualizations. Compute-heavy operations are centralized in CFDAnalysis while workflows in CFDWorkflows handle visualization and user-facing output.

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

### Ontology (ontology.json)

**Used for EXPLANATION only, not execution.**

CFD domain knowledge that helps LLM interpret results:
- `flow_features` → What each visualization type means (Q > 0 = vortex core)
- `causal_relationships` → What causes drag/lift changes (wake → base pressure → drag)
- `analysis_recommendations` → Which tools for which questions

The LLM calls `get_ontology()` when it needs to explain results. The ontology never influences which workflow runs or how it executes.

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
