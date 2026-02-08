# Architecture

## Design Principle

**LLM NEVER MAKES EXECUTION DECISIONS.**

This is the core architectural constraint. The LLM is restricted to:
- Understanding what the user wants (intent classification)
- Explaining what happened (result summarization)

The LLM is NEVER allowed to:
- Decide which tools to call
- Manage proxy names or pipeline state
- Loop or retry on failures
- Compose novel tool sequences

### Why This Constraint?

We observed that giving the LLM free reign to orchestrate tools resulted in:
- **1M tokens for 4 queries** (token explosion)
- **16+ retries** of the same failing tool
- **State confusion** with proxy names despite explicit instructions
- **$0.15 for simple tasks** that should cost $0.001

The LLM excels at understanding language but fails at:
- State management
- Knowing when to stop
- Following multi-step procedures
- Recovering from errors

## Tiered Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  USER QUERY                                                 │
│  "Show me the vortices"                                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Intent Classification (LLM)                        │
│                                                             │
│  Single LLM call (~150 tokens)                              │
│  Input: User query                                          │
│  Output: Intent enum + parameters                           │
│                                                             │
│  Example: "Show me vortices" → VISUALIZE_VORTICES           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 2: Workflow Selection (DETERMINISTIC)                 │
│                                                             │
│  No LLM - pure lookup                                       │
│  Input: Intent enum                                         │
│  Output: Predefined workflow                                │
│                                                             │
│  WORKFLOWS[VISUALIZE_VORTICES] → [hide_all, show_context,   │
│                                   ensure_velocity,          │
│                                   create_isosurface,        │
│                                   focus_on_last]            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 3: Execution (DETERMINISTIC)                          │
│                                                             │
│  No LLM - sequential tool execution                         │
│  - Manages all state (proxy names, pipeline)                │
│  - Handles errors without LLM consultation                  │
│  - Uses ontology for domain knowledge (not LLM reasoning)   │
│                                                             │
│  Returns structured result                                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 4: Result Summary (LLM)                               │
│                                                             │
│  Single LLM call (~200 tokens)                              │
│  Input: Execution result                                    │
│  Output: Natural language explanation                       │
│                                                             │
│  "Created vortex visualization using Q-criterion..."        │
└─────────────────────────────────────────────────────────────┘
```

## Intent Types

The LLM classifies into exactly ONE of these predefined intents:

| Intent | Description | Workflow |
|--------|-------------|----------|
| `visualize_vortices` | Show vortical structures | Q-criterion isosurface |
| `visualize_wake` | Show wake flow | Streamlines |
| `visualize_streamlines` | Show flow streamlines | Streamlines |
| `create_slice` | Create cut plane | Slice at center |
| `compute_forces` | Calculate drag/lift | Force integration |
| `analyze_drag` | Show drag distribution | Distribution chart |
| `field_statistics` | Get field stats | Min/max/mean |
| `describe_data` | Describe dataset | Characterize |
| `reset_view` | Reset camera | Camera reset |
| `hide_all` | Clear viz | Hide all |
| `explain_concept` | Explain CFD concept | Ontology lookup |
| `unknown` | Fallback | Error message |

## Workflow Definitions

Each workflow is a predefined sequence of tool calls:

```python
WORKFLOWS = {
    IntentType.VISUALIZE_VORTICES: {
        "name": "Visualize Vortices",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("create_vortex_isosurface", {"method": "q_criterion"}),
            ("focus_on_last", {}),
        ],
    },
    # ... more workflows
}
```

Workflows are:
- **Predefined** - No runtime composition
- **Deterministic** - Same intent → same execution
- **Complete** - Each workflow is self-contained

## Component Roles

### LLM (OpenAI/Claude)
- Intent classification (Tier 1)
- Result summarization (Tier 4)
- **Total: 2 calls per query**

### Ontology (CFDOntology)
- Domain knowledge for workflow validation
- Requirement checking (does data have velocity?)
- Concept explanations
- **NOT used for LLM reasoning**

### Extended MCP (ExtendedParaViewMCP)
- High-level CFD tools
- Vortex detection, force computation, streamlines
- Used by executor, not by LLM directly

### Base MCP (ParaViewMCP from trame-llm)
- Low-level ParaView operations
- Proxy creation, property updates, rendering

### Workflow Executor
- Runs predefined workflows
- Manages all state
- Handles errors deterministically
- **LLM never involved in execution**

## Cost Comparison

| Architecture | Tokens/Query | Cost/Query | Reliability |
|--------------|-------------|------------|-------------|
| Tool loop (old) | ~250,000 | $0.04 | Poor (retries, confusion) |
| Safe (new) | ~350 | $0.00005 | Excellent (deterministic) |

**750x cheaper, far more reliable.**

## Adding New Workflows

To add a new capability:

1. **Add IntentType enum value** in `cfd_assistant.py`
2. **Add workflow definition** in `WORKFLOWS` dict
3. **Implement tool function** if new tool needed
4. **Update classification prompt** with new intent description

The LLM will automatically classify queries to the new intent.

## What This Architecture Cannot Do

- **Novel compositions**: Cannot combine tools in ways not predefined
- **Adaptive retry**: Won't try alternative approaches on failure
- **Complex reasoning**: Won't figure out multi-step analysis

This is intentional. For complex exploratory analysis, use the tools directly or add new predefined workflows. The LLM should not improvise.

## Files

```
src/paraview_llm/
├── cfd_assistant.py      # Safe tiered architecture
├── extended_mcp.py       # CFD tools
├── ontology_triples.py   # Domain knowledge
├── ontology_planning.py  # Workflow prerequisites
└── mock_llm.py          # Testing without API
```
