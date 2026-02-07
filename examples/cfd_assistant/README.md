# CFD Assistant Example

End-to-end example and test suite for ParaView LLM.

## Setup

```bash
# Create venv with ParaView-compatible Python
/path/to/paraview/bin/pvpython -m venv .venv

# Activate and install dependencies
source .venv/bin/activate
pip install openai  # Only needed for --real mode
```

## Test Data

The example uses `test.vtm` - a multiblock VTK dataset with:
- CFD simulation results (velocity, pressure fields)
- Body geometry for force integration

## Running Tests

### Mock Mode (Default)

Fast, free, deterministic testing:

```bash
pvpython --venv .venv test_e2e.py
```

Output:
```
============================================================
E2E Test Suite - MOCK LLM
============================================================
Data source: XMLMultiBlockDataReader1

✓ shear_layer (0.9s)
✓ stagnation (0.2s)
...

Passed: 17/17
Total time: 4.0s
```

### Real LLM Mode

Tests intent classification with real LLM:

```bash
export OPENAI_API_KEY="sk-..."
pvpython --venv .venv test_e2e.py --real
```

Output:
```
============================================================
E2E Test Suite - REAL LLM (intent-based)
============================================================

✓ shear_layer → shear_layer (0.7s)
✓ stagnation → stagnation (0.6s)
...

Passed: 17/17
Total time: 12.5s
```

## Test Cases

| Test | Query | Workflow |
|------|-------|----------|
| `shear_layer` | "show me the shear layer" | Vorticity + high gradient |
| `stagnation` | "where is the stagnation point" | find_minimum(velocity) |
| `flow_pattern` | "visualize the flow pattern" | Streamlines in wake |
| `pressure` | "show me the pressure distribution" | Color by pressure |
| `velocity_stats` | "what are the velocity statistics" | field_statistics |
| `velocity_distribution` | "show me a histogram of velocity" | Histogram chart |
| `forces` | "calculate drag and lift forces" | compute_forces |
| `drag_distribution` | "drag accumulates along streamwise" | Force distribution chart |
| `lift_distribution` | "spanwise lift distribution" | Force distribution chart |
| `max_velocity` | "where is the maximum velocity" | find_maximum(velocity) |
| `wake_slice` | "slice through the wake" | detect_wake + slice |
| `wake_streamlines` | "streamlines in the wake" | detect_wake + streamlines |
| `vortices_q` | "vortices using Q-criterion" | Q-criterion isosurface |
| `vortices_lambda2` | "vortex cores using lambda2" | λ2 isosurface |
| `vortices_swirl` | "swirling strength" | Swirl isosurface |
| `vortices_helicity` | "helical vortex structures" | Helicity isosurface |
| `characterize` | "characterize the flowfield" | Multi-tool analysis |

## Output

Screenshots are saved to `output/`:

```
output/
├── mock_01_shear_layer.png
├── mock_02_stagnation.png
├── ...
├── real_01_shear_layer.png  # When using --real
└── ...
```

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────┐
│  MockLLMExecutor        │  (mock mode)
│  - Keyword matching     │
│  - No LLM calls         │
└─────────────────────────┘
    or
┌─────────────────────────┐
│  IntentExecutor         │  (real mode)
│  - LLM classifies       │
│  - {"workflow": "..."}  │
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  WORKFLOWS[name]        │
│  - Predefined sequence  │
│  - Deterministic        │
└─────────────────────────┘
    │
    ▼
ExtendedParaViewMCP → ParaView
```

## Adding New Workflows

1. Add workflow to `intent_executor.py`:

```python
WORKFLOWS = {
    "my_workflow": {
        "description": "Description for LLM",
        "sequence": [
            ("hide_all", {}),
            ("show_data_context", {"proxy_name": "{data_source}"}),
            ("my_tool", {"proxy_name": "{data_source}"}),
            ("focus_on", {"proxy_name": "{last_created}"}),
        ]
    },
}
```

2. Add mock response in `mock_llm.py`:

```python
MOCK_RESPONSES = {
    "my_workflow": [
        # Same sequence as WORKFLOWS
    ],
}
```

3. Add test query in `test_e2e.py`:

```python
QUERY_TEXT = {
    "my_workflow": "natural language query",
}
```

4. Run tests:

```bash
pvpython --venv .venv test_e2e.py
pvpython --venv .venv test_e2e.py --real
```
