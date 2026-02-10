# Architecture

## Design Evolution

We tried several approaches before arriving at the current architecture:

| Approach | Problem |
|----------|---------|
| LLM orchestrates 40+ tools | Skips steps, wrong order, burns tokens |
| LLM with detailed instructions | Still unreliable, 1M+ tokens for simple tasks |
| Intent classification → workflow | Works but limited to predefined intents |
| **Workflow tools + ontology** | ✅ Reliable execution + rich explanations |

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
│  Multiple tool calls in one response (parallel execution)   │
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
2. Calls ExtendedParaViewMCP analysis methods
3. Creates ParaView filters/sources
4. Returns rich result dict

### ExtendedParaViewMCP

40+ CFD analysis tools. Two categories:

**Analysis tools** (return data, no visualization):
- `compute_vortex_field` → threshold, field_range
- `detect_wake_region` → centroid, bounds
- `compute_forces` → Cd, Cl, distribution

**Visualization tools** (create ParaView objects):
- `create` → generic filter creation
- `update_property` → set filter properties
- `focus_on` → camera setup

### Ontology (ontology.json)

CFD domain knowledge:
- `flow_features` → What each visualization type means
- `causal_relationships` → What causes drag/lift changes
- `analysis_recommendations` → Which tools for which questions

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
