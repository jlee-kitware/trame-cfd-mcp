# CFD Assistant Example

Example tests for ParaView LLM workflow tools.

## Setup

```bash
# Create venv with ParaView-compatible Python
/path/to/paraview/bin/pvpython -m venv .venv

# Activate and install dependencies
source .venv/bin/activate
pip install openai python-dotenv

# Set API key
echo "OPENAI_API_KEY=sk-..." > .env
```

## Test Data

The example uses `test.vtm` - a multiblock VTK dataset with:
- CFD simulation results (velocity, pressure, density fields)
- Body geometry for force integration
- Turbulence quantities

## Running Tests

### Test All Workflows

Validates each workflow tool with simple prompts:

```bash
pvpython --venv .venv test_workflows.py
```

Output:
```
TEST: vortex
PROMPT: Show vortices. Save to output/test_vortex.png
[call] Calling: show_vortices
[result] {"status":"created","type":"vortex_isosurface",...}
[call] Calling: save_screenshot
...

==================================================
COST REPORT
==================================================
Model: gpt-5-mini
Tool calls: 10
Estimated cost: $0.003
==================================================
```

### Test Ontology Explanations

Tests that the LLM uses ontology knowledge to explain visualizations:

```bash
pvpython --venv .venv test_ontology.py
```

Prompt: "Show me the vortex structures and explain what I'm seeing."

Output includes physics explanation using ontology knowledge.

### Test Multi-Step Analysis

Open-ended exploration - LLM decides what visualizations to create:

```bash
pvpython --venv .venv test_analysis.py
```

Prompt: "Analyze this CFD dataset to understand the flow physics. I want to understand the wake structure and how it relates to drag."

Typical output:
- Vortices (Q-criterion and lambda2)
- Streamlines in wake
- Wake slice
- Pressure histogram  
- Force distribution
- Physics explanation connecting all results

## Output

Screenshots saved to `output/`:

```
output/
├── test_vortex.png
├── test_streamlines.png
├── test_slice.png
├── test_histogram.png
├── test_forces.png
├── test_vortex_explained.png
├── analysis_vortices_qcriterion.png
├── analysis_vortices_lambda2.png
├── analysis_streamlines.png
├── analysis_slice_wake.png
├── analysis_pressure_histogram.png
└── analysis_forces.png
```

## Test Files

| File | Purpose |
|------|---------|
| `test_workflows.py` | Validate all 5 workflow tools |
| `test_ontology.py` | Test explanation with ontology |
| `test_analysis.py` | Test multi-step exploration |

## Cost Tracking

All tests use `TrackedLLMClient` which reports:
- LLM calls
- Tool calls
- Input/output tokens
- Estimated cost

Typical costs:
- Simple workflow test: ~$0.001
- With explanation: ~$0.003
- Full analysis: ~$0.008
