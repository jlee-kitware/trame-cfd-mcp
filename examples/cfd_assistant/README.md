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
pvpython test_e2e.py
```

Output:
```
============================================================
E2E Test Suite - MOCK LLM
============================================================
Data source: XMLMultiBlockDataReader1

TEST 1: shear_layer
Tools executed:
  ✓ hide_all
  ✓ show_data_context
  ✓ create_vortex_isosurface
  ✓ focus_on
  ✓ set_streamwise_view
✓ PASSED (0.9s)

...

Passed: 16/16
Total time: 3.7s
```

### Real LLM Mode

Tests actual LLM understanding (requires `OPENAI_API_KEY`):

```bash
export OPENAI_API_KEY="sk-..."
pvpython test_e2e.py --real
```

## Test Cases

| Test | Query | Visualization |
|------|-------|---------------|
| `shear_layer` | "show me the shear layer" | Vorticity isosurface |
| `stagnation` | "where is the stagnation point" | Slice at min velocity |
| `flow_pattern` | "visualize the flow pattern" | Streamlines |
| `pressure` | "show me the pressure distribution" | Pressure slice |
| `velocity_stats` | "what are the velocity statistics" | JSON data |
| `velocity_distribution` | "show me a histogram of velocity" | Bar chart |
| `forces` | "calculate drag and lift forces" | JSON data |
| `drag_distribution` | "how drag accumulates along streamwise" | XY chart |
| `lift_distribution` | "show spanwise lift distribution" | XY chart |
| `max_velocity` | "where is the maximum velocity" | Slice at max |
| `wake_slice` | "create a slice through the wake" | X-normal slice |
| `vortices_q` | "show vortices using Q-criterion" | Q isosurface |
| `vortices_lambda2` | "visualize vortex cores using lambda2" | λ2 isosurface |
| `vortices_swirl` | "show swirling strength" | Swirl isosurface |
| `vortices_helicity` | "show helical vortex structures" | Helicity isosurface |
| `characterize` | "characterize the flowfield" | Multi-tool analysis |

## Output

Screenshots are saved to `output/`:

```
output/
├── mock_01_shear_layer.png
├── mock_02_stagnation.png
├── ...
├── mock_08_drag_distribution.png   # XY chart
├── mock_09_lift_distribution.png   # XY chart
└── mock_16_characterize.png
```

## Adding New Tests

1. Add entry to `MOCK_RESPONSES` in `mock_llm.py`:

```python
"my_test": [
    ("hide_all", {}),
    ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
    ("my_tool", {"param": "value", "proxy_name": "{data_source}"}),
    ("focus_on", {"proxy_name": "{last_created}"}),
],
```

2. Add natural language mapping in `test_e2e.py`:

```python
QUERY_TEXT = {
    # ...
    "my_test": "natural language query for my test",
}
```

3. Run tests to verify:

```bash
pvpython test_e2e.py
```
