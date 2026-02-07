# Architecture

## Design Philosophy

### Intent-Based vs Workflow Composition

This system uses **intent-based execution**: the LLM classifies user intent into one of 17 predefined workflows, which execute deterministically.

```
INTENT-BASED (implemented):
  Query → LLM (classify) → Workflow Lookup → Execute Tools

WORKFLOW COMPOSITION (rejected):
  Query → LLM (compose tools from 34 options) → Execute
```

**Why intent-based?**

| Concern | Workflow Composition | Intent-Based |
|---------|---------------------|--------------|
| LLM task | Compose tool sequences | Classify into 17 categories |
| Reliability | LLM overwhelmed by 34 tools | Simple classification |
| Latency | ~2s (complex reasoning) | ~0.5s (simple classification) |
| Predictability | Variable sequences | Deterministic workflows |

**Key insight**: The LLM should be an **intent classifier**, not a **workflow composer**. All tool sequencing is predefined in the ontology.

## System Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User Query                                                                 │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  IntentExecutor                                                     │    │
│  │  ├── extract_intent(): LLM classifies → workflow name              │    │
│  │  └── execute_workflow(): Lookup WORKFLOWS[name] → run sequence     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  WORKFLOWS (the Ontology)                                           │    │
│  │  17 predefined CFD workflows, each a sequence of tools              │    │
│  │  Example: vortices_q → [hide_all, show_context, isosurface, focus]  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ExtendedParaViewMCP (34 CFD tools)                                 │    │
│  │  Analysis: find_minimum, find_maximum, field_statistics, etc.       │    │
│  │  Forces: compute_forces, create_force_distribution_chart            │    │
│  │  Vortex: create_vortex_isosurface (Q, λ2, swirl, helicity)          │    │
│  │  Visualization: create_slice, create_streamlines, etc.              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ParaViewMCP (from trame-llm)                                       │    │
│  │  Base ParaView operations: render, camera, color mapping, etc.      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                     │
│       ▼                                                                     │
│  ParaView                                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Workflow Definition

Each workflow is a predefined sequence of tool calls:

```python
WORKFLOWS = {
    "vortices_q": {
        "description": "Visualize vortices using Q-criterion",
        "sequence": [
            ("hide_all", {}),
            ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
            ("create_vortex_isosurface", {"method": "q_criterion", "proxy_name": "{data_source}"}),
            ("focus_on", {"proxy_name": "{last_created}"}),
            ("set_streamwise_view", {"proxy_name": "{last_created}"}),
        ]
    },
    # ... 16 more workflows
}
```

### Placeholder Substitution

Workflows use placeholders that are resolved at execution time:

| Placeholder | Resolved To |
|-------------|-------------|
| `{data_source}` | Name of the loaded dataset |
| `{last_created}` | Name of the most recently created proxy |
| `{wake_centroid}` | Centroid from detect_wake_region() result |
| `{location}` | Location from find_minimum/maximum result |

## Intent Classification

The LLM receives a simple classification prompt:

```
AVAILABLE WORKFLOWS:
- vortices_q: Visualize vortices using Q-criterion
- vortices_lambda2: Visualize vortex cores using lambda2 method
- stagnation: Find stagnation point
- ... (17 total)

USER REQUEST: show me the vortices using Q-criterion

Respond with JSON: {"workflow": "vortices_q"}
```

This is a trivial task for any LLM—just text classification with 17 categories.

## Mock vs Real Execution

Both modes use the same WORKFLOWS definitions:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXECUTION MODES                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MOCK MODE (CI/testing)                                                     │
│                                                                             │
│    Query Key → MockLLMExecutor → MOCK_RESPONSES[key] → Execute              │
│    "vortices_q"   (keyword match)   (predefined)                            │
│                                                                             │
│    Cost: $0 | Time: ~0.2s | Use: CI, development                            │
│                                                                             │
│  REAL LLM MODE (production)                                                 │
│                                                                             │
│    Natural Language → IntentExecutor → LLM → WORKFLOWS[name] → Execute      │
│    "show me vortices"  (classify)   (API)   (predefined)                    │
│                                                                             │
│    Cost: ~$0.001 | Time: ~0.7s | Use: Production                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tool Design Principles

### Auto-Detection

Tools automatically detect parameters when possible:

```python
def create_vortex_isosurface(method="q_criterion", threshold=None, ...):
    # Auto-detect threshold if not provided
    if threshold is None:
        if method == "lambda2":
            threshold = 0.01 * stats["min"]  # 1% of min (close to 0)
        else:
            threshold = percentile(values, 50)  # 50th percentile
```

### Intelligent Defaults

Tools have CFD-aware defaults:

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `opacity` | 0.15 | Context visible but not distracting |
| `percentile` | 50 | Captures significant structures |
| `num_points` | 50 | Enough streamlines for patterns |
| `color_field` | "Velocity" | Most common CFD visualization |

### Error Handling

Tools handle common issues gracefully:

- Missing fields → use available alternatives
- Invalid bounds → compute from data
- Missing view → create one

## Adding New Workflows

1. Add to `WORKFLOWS` in `intent_executor.py`:

```python
"separation_bubble": {
    "description": "Detect and visualize flow separation",
    "sequence": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("detect_separation", {"proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
    ]
}
```

2. Implement any new tools in `extended_mcp.py`

3. Add test case in `mock_llm.py` and `test_e2e.py`

The LLM will automatically be able to classify queries to the new workflow.

## Performance

| Mode | Tests | Time | Cost |
|------|-------|------|------|
| Mock | 17/17 | 4.0s | $0 |
| Real LLM | 17/17 | 12.5s | ~$0.02 |

The intent-based architecture is:
- **4x faster** than workflow composition (12s vs 51s)
- **More reliable** (simple classification vs complex reasoning)
- **More predictable** (deterministic workflows)
