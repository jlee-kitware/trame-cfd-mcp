# trame-cfd-mcp

CFD workflow tools for ParaView via MCP (Model Context Protocol).

Extends [trame-llm](https://github.com/Kitware/trame-llm)'s ParaViewMCP with CFD-specific visualization workflows.

## Overview

trame-cfd-mcp enables natural language queries for CFD visualization and analysis:

```
"show me the vortices"                →  Q-criterion isosurface
"show streamlines in the wake"        →  Detect wake, seed streamlines
"analyze the wake and explain drag"   →  Multiple visualizations + physics explanation
```

## Interactive Application

The main way to use trame-cfd-mcp is through the interactive chat interface:

```bash
cd examples/cfd_assistant
pvpython cfd_chat.py [your_data.vtm]
```

This launches a web-based UI with:

- **ParaView 3D View** - Interactive rendering of your CFD data
- **Pipeline Browser** - Click the branch icon (or press 'p') to see/manage filters
- **Chart Panel** - Click the chart icon (top-right) to view interactive Plotly charts
- **LLM Chat** - Click the chat icon (bottom-right) to interact with the assistant

### Features

- **Conversation continuity** - Follow-up questions remember previous context
- **Cost tracking** - Ask "what is the session cost?" to see token usage
- **Interactive charts** - Plotly charts with zoom, pan, and hover for boundary layer profiles, histograms, and force distributions
- **Pipeline updates** - New filters appear in pipeline browser automatically

### Example Session

```
You: What data is loaded?
Assistant: [calls list_data] You have a multi-block dataset with body and farfield...

You: Show vortices using lambda2
Assistant: [calls show_vortices] Created vortex visualization with λ₂ threshold...

You: Make them semi-transparent and color by pressure
Assistant: [calls update_display_property, update_color] Done...

You: Show the boundary layer at 50% chord
Assistant: [calls show_boundary_layer] BL profile shows H=1.7 indicating turbulent...

You: What's the session cost?
Assistant: [calls get_session_cost] Total: 45,000 tokens, ~$0.02
```

## What the LLM Does

The LLM acts as a **CFD analyst**, not just a command translator:

1. **Multi-step reasoning** - Decides what visualizations to create and in what order
2. **Parameter selection** - Chooses methods (q_criterion vs lambda2), locations (wake vs center)
3. **Ontology-driven explanation** - Uses CFD domain knowledge to explain what results mean
4. **Follow-up analysis** - Reasons about results, identifies patterns, suggests next steps

**What's deterministic:** The workflow implementations themselves. Once the LLM decides to call `show_vortices(method="q_criterion")`, the execution is pure Python with no LLM involvement.

## Installation

### Prerequisites

1. **ParaView** with Python bindings and SSL support
   - Option A: Build from source with system Python (recommended)
   - Option B: Use conda: `conda install -c conda-forge paraview`
   - Note: The pre-built ParaView.app on macOS lacks SSL, which is required for API calls

2. **trame-llm** - LLM orchestration library
   ```bash
   git clone https://github.com/Kitware/trame-llm.git
   cd trame-llm
   pip install -e .
   ```

3. **Required packages**
   ```bash
   pip install python-dotenv openai fastmcp trame trame-vuetify trame-vtk trame-dockview
   ```

4. **API key or local LLM**

   For cloud (OpenAI):
   ```bash
   # Create .env file in examples/cfd_assistant/
   echo "LLM_PROVIDER=openai" > .env
   echo "OPENAI_API_KEY=sk-your-key-here" >> .env
   echo "LLM_MODEL=gpt-4o-mini" >> .env
   echo "OPENAI_BASEURL=https://api.openai.com/v1" >> .env
   ```

   For local inference (LM Studio / Ollama — recommended for privacy and zero API cost):
   ```bash
   echo "LLM_PROVIDER=openai" > .env
   echo "OPENAI_API_KEY=lm-studio" >> .env
   echo "LLM_MODEL=qwen2.5-coder-14b-instruct" >> .env   # or 32b if you have 20GB+ VRAM
   echo "OPENAI_BASEURL=http://192.168.x.x:1234/v1" >> .env
   ```
   Enable "Serve on Local Network" in LM Studio, then verify the model ID from `/v1/models`.

### Install trame-cfd-mcp

```bash
git clone https://github.com/jlee-kitware/trame-cfd-mcp.git
cd trame-cfd-mcp
pip install -e .
```

## Running

### Interactive Chat App (Recommended)

```bash
cd examples/cfd_assistant

# With default test data
pvpython cfd_chat.py

# With your own data
pvpython cfd_chat.py /path/to/your/simulation.vtm
```

### Batch Tests

```bash
cd examples/cfd_assistant

# Fast unit tests (no LLM, no API costs)
pvpython test_workflows_basic.py

# LLM integration tests
pvpython --venv .venv test_workflows.py
pvpython --venv .venv test_boundary_layer.py
pvpython --venv .venv test_ontology.py
```

## Catalyst Live Monitoring

Connect to running simulations for real-time visualization and residual monitoring:

```bash
# Start the app with live mode enabled
pvpython cfd_chat.py --live --host localhost --port 22222
```

### Live UI Features

- **Connection button** (broadcast icon, top-right) - Connect/disconnect from simulation
- **Chart panel** (chart icon, top-right) - Live residual convergence plot
- **Pipeline browser** - Shows extracted data from simulation

### Live Workflow

1. Start your Catalyst-enabled simulation (must expose Live connection on port 22222)
2. Launch app with `--live` flag
3. Click broadcast icon to connect
4. Chat: `"extract monitors"` - starts residual tracking, open chart panel to view
5. Chat: `"extract grid"` then `"show grid colored by pressure"` - visualize mesh
6. Chat: `"pause simulation"` - freeze for detailed analysis
7. Chat: `"resume simulation"` - continue

### Live Tools

| Tool | Description |
|------|-------------|
| `connect_live(host, port)` | Connect to Catalyst simulation |
| `disconnect_live()` | Disconnect from simulation |
| `pause_simulation()` | Pause for detailed analysis |
| `resume_simulation()` | Continue simulation |
| `extract_live_data(name)` | Extract data channel (e.g., "grid") |
| `show_live_source(name, color_by)` | Display extracted data |
| `extract_monitors(channel)` | Start residual monitoring |
| `get_live_status()` | Get simulation time/state |

### Example Simulation

See `examples/catalyst/` for example Catalyst pipelines and mock simulations that work with live mode.

## Architecture

```
User Query: "Analyze the wake and explain drag"
                    │
                    ▼
        ┌───────────────────────┐
        │         LLM           │  Multi-step reasoning
        │  - What to visualize  │  Parameter selection
        │  - What order         │  Explanation generation
        │  - How to explain     │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │    WorkflowMCP        │  26 high-level tools    ─┐
        │  - show_vortices()    │  Deterministic execution  │
        │  - show_streamlines() │  Full provenance tracking │
        │  - show_slice()       │                           │ trame-cfd-mcp
        │  - get_ontology()     │  CFD domain knowledge     │
        └───────────────────────┘                          ─┘
                    │
                    ▼
        ┌───────────────────────┐
        │   CFDAnalysis         │  CFD analysis tools      ─┐
        │  - compute_vortex_field()                         │ trame-cfd-mcp
        │  - detect_wake_region()                           │
        │  - compute_forces()   │                          ─┘
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   ParaViewMCP         │  Base ParaView operations ─ trame-llm
        │  (from trame-llm)     │
        └───────────────────────┘
                    │
                    ▼
                ParaView
```

### Key Design Principles

1. **LLM reasons, workflows execute** - LLM decides what to do; Python does it deterministically
2. **Ontology for explanation** - Domain knowledge helps LLM explain physics, not control execution
3. **Full provenance** - Every workflow returns filter chain and analysis decisions for traceability
4. **Cost tracking built-in** - Monitor token usage and costs

## Workflow Tools

| Tool | Description |
|------|-------------|
| **Discovery** | |
| `list_data()` | List loaded data sources and filters |
| `get_fields()` | Get available fields with ranges |
| `analyze_data()` | Characterize dataset, recommend workflows |
| **Visualization** | |
| `show_vortices(method)` | Q-criterion, vorticity, or lambda2 isosurface |
| `show_streamlines()` | Flow streamlines in wake region |
| `show_slice(location, normal)` | Slice through wake or domain center |
| `show_histogram(field)` | Field distribution chart |
| `show_forces()` | Force distribution along body |
| `show_boundary_layer(x_over_chord, span_fraction)` | Boundary layer profile with δ, δ*, θ, H |
| `show_boundary_layer_context()` | 3D visualization of BL probe locations |
| `show_flow_topology()` | Vortex core lines via VTK VortexCores filter |
| **Refinement** | |
| `update_representation(type, proxy)` | Change to Wireframe, Surface, Points |
| `update_color(proxy, field)` | Recolor by different field |
| `update_list_property(prop, value, proxy)` | Adjust thresholds/isovalues |
| `update_display_property(prop, value, proxy)` | Set Opacity, Interpolation (PBR), LineWidth |
| `show_or_hide(proxy, visible)` | Toggle visibility |
| `list_properties(proxy)` | Discover adjustable properties |
| **Utilities** | |
| `set_view(direction)` | Set camera angle (iso, +x, -x, etc.) |
| `save_screenshot(filename)` | Save current view |
| `save_all_charts(prefix)` | Save all pending charts |
| `save_state(filename)` | Save full ParaView state |
| `get_ontology()` | CFD domain knowledge for explanations |
| `delete_filter(proxy)` | Remove a filter from pipeline |
| `clear_all_filters()` | Reset pipeline to original data |
| `hide_all_scalar_bars()` | Hide color legends (reduces GPU texture usage) |

## Key Analysis Features

### Boundary Layer Analysis

`show_boundary_layer(x_over_chord, span_fraction)` provides comprehensive boundary layer characterization:

- **Explicit station selection**: Specify chordwise position (0=LE, 1=TE) and span fraction (0=root, 1=tip)
- **Plane-cut methodology**: Cuts spanwise plane to get true airfoil section (client-side geometry), then runs velocity probe and BL computation via ProgrammableFilter on pvserver — no field data moves to client
- **Integral quantities**: δ (thickness), δ* (displacement), θ (momentum), H (shape factor)
- **Flow state indication**: H ≈ 1.3–1.4 turbulent, H ≈ 2.6 laminar, H > 3.5 separation risk

### Interactive Charts

Workflows that create charts (`show_boundary_layer`, `show_histogram`, `show_forces`) display interactive Plotly charts in the Chart Panel:

- **View in UI**: Click chart icon (top-right) to open/close the chart panel
- **Multiple charts**: Charts stack vertically with scrolling
- **Interactive**: Zoom, pan, hover for data values
- **Clear button**: Remove all charts to start fresh

### Display Properties

Control visual representation properties not exposed by base trame-llm:

```
"Make the surface semi-transparent"     →  Opacity: 0.5
"Show as wireframe with thick lines"    →  Representation: Wireframe, LineWidth: 2
"Enable PBR rendering"                  →  Interpolation: PBR
"Set metallic to 0.8 and roughness 0.2" →  PBR material properties
"Make points larger"                    →  PointSize: 5
```

Available properties via `update_display_property()`:
- **Opacity**: 0.0 (transparent) to 1.0 (opaque)
- **Interpolation**: "Flat", "Gouraud", or "PBR"
- **LineWidth**: Line thickness for wireframe/edges
- **PointSize**: Point size for Points representation
- **Metallic/Roughness**: PBR material properties (0.0-1.0)

## Provenance

Every workflow returns structured provenance for traceability:

```json
{
  "status": "created",
  "type": "vortex_isosurface",
  "proxy_name": "Vortices_lambda2",
  "result": {
    "field": "Lambda2",
    "threshold": -500.0
  },
  "provenance": {
    "dataset": "simulation.vtm",
    "filter_chain": [
      {"filter": "Gradient", "params": {"ComputeGradient": 1}},
      {"filter": "PythonCalculator", "params": {"Expression": "lambda2(...)"}},
      {"filter": "Contour", "params": {"Isosurfaces": [-500.0]}}
    ],
    "analysis": [
      {"type": "auto_threshold", "method": "percentile", "percentile": 50.0}
    ]
  }
}
```

## Cost Tracking

Monitor API costs (cloud) or electricity costs (local inference) in the interactive app:

```
You: What is the session cost?
Assistant: Model: qwen2.5-coder-32b-instruct, Input: 45,231 tokens, Output: 1,892 tokens, Cost: $0.0034
```

For **local inference** (LM Studio, Ollama), costs are estimated from electricity consumption:
- Assumes ~350W total system draw at $0.15/kWh
- Input tokens (prefill) charged at ~$0.036/1M (fast, ~400 tok/s)
- Output tokens (generation) charged at ~$1.82/1M (slower, ~8 tok/s with partial GPU offload)

Configure local inference in `.env`:
```bash
LLM_PROVIDER=openai
LLM_MODEL=qwen2.5-coder-32b-instruct
OPENAI_API_KEY=lm-studio          # any non-empty string
OPENAI_BASEURL=http://192.168.x.x:1234/v1
```

Or programmatically via `get_session_cost()` tool.

## Files

```
src/trame_cfd_mcp/
├── __init__.py          # Package exports
├── workflow_mcp.py      # High-level workflow tools (26 tools)
├── workflows.py         # Workflow implementations
├── cfd_analysis.py      # CFD analysis functions (all analysis runs server-side)
├── server_scripts/      # ProgrammableFilter scripts — execute on pvserver
│   ├── field_statistics.py     # min/max/mean/std
│   ├── field_histogram.py      # histogram bins/counts
│   ├── vortex_threshold.py     # auto-threshold for Q/vorticity/lambda2
│   ├── force_integration.py    # pressure×normal surface integration
│   ├── force_distribution.py   # sectional force distribution
│   ├── detect_streamwise.py    # primary flow axis detection
│   ├── detect_wake.py          # wake centroid/bounds
│   ├── boundary_layer.py       # BL probe + δ, δ*, θ, H
│   ├── find_region.py          # spatial min/max location
│   └── centroid.py             # point cloud centroid/bounds
├── catalyst_live.py     # Catalyst Live MCP (CFDChatMCP class)
├── cost_tracker.py      # Token usage and cost tracking
└── ontology.json        # CFD domain knowledge

examples/cfd_assistant/
├── cfd_chat.py          # Interactive chat application (supports --live)
├── test_workflows.py    # LLM integration tests
├── test_workflows_basic.py  # Unit tests (no LLM)
├── test_boundary_layer.py   # BL analysis tests
├── test_ontology.py     # Ontology explanation tests
├── .env.example         # API key template
└── test.vtm             # Sample CFD dataset

examples/catalyst/
├── catalyst_pipeline_monitors.py  # Pipeline with residual monitoring
├── mock_simulation.py             # Mock simulation for testing
└── README.md                      # Catalyst examples documentation
```

## License

BSD 3-Clause (compatible with ParaView/VTK)
