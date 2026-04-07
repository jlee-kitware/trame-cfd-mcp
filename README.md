# trame-cfd-mcp

CFD workflow tools for ParaView via MCP (Model Context Protocol).

Extends [trame-llm](https://github.com/Kitware/trame-llm)'s ParaViewMCP with CFD-specific
visualization workflows. A user states an engineering question in natural language; the system
plans a deterministic analysis chain, executes it via ParaView, and returns a grounded
physical explanation.

```
"show me the vortices"                →  Q-criterion isosurface, auto-thresholded
"show streamlines in the wake"        →  Wake detection + seeded streamlines
"analyze the wake and explain drag"   →  Multi-step analysis + physics explanation
```

---

## Requirements

| Dependency | Version | Notes |
|---|---|---|
| ParaView (with Python) | 5.12+ | Must include SSL support — see note below |
| Python | 3.10+ | Must be the same Python ParaView uses |
| trame-llm | main branch | Kitware internal; clone separately |
| LLM | any OpenAI-compatible | Cloud (OpenAI) or local (Ollama, LM Studio) |

**ParaView + SSL note:** The pre-built ParaView.app downloaded from paraview.org on macOS
does not configure SSL certificates correctly, causing API calls to fail. This is a macOS
certificate issue with that specific distribution, not a ParaView problem. Use one of:
- Build ParaView from source (links against system Python/SSL — this is what Kitware developers use)
- `conda install -c conda-forge paraview` (includes SSL, easiest for new installs)
- On Linux, the official pre-built binary works fine

---

## Installation

### 1. Clone both repos

```bash
git clone https://github.com/Kitware/trame-llm.git
git clone https://github.com/jlee-kitware/trame-cfd-mcp.git
```

> **Note:** trame-cfd-mcp is currently on the `feature/pvserver-support` branch.
> trame-llm is currently on the `feature/planner-executor` branch.
> Both branches contain the pvserver client-server infrastructure; main does not yet.

```bash
cd trame-llm && git checkout feature/planner-executor && cd ..
cd trame-cfd-mcp && git checkout feature/pvserver-support && cd ..
```

### 2. Install into ParaView's Python environment

Use `pvpython` (not your system Python) for the install so packages land where ParaView can
find them. `pvpython -m pip` is the reliable way to do this.

```bash
pvpython -m pip install -e /path/to/trame-llm
pvpython -m pip install -e /path/to/trame-cfd-mcp
pvpython -m pip install trame-plotly plotly  # for interactive charts
```

### 3. Configure your LLM

Create a `.env` file in `examples/cfd_assistant/`:

```bash
cd trame-cfd-mcp/examples/cfd_assistant
cp .env.example .env
```

**Option A — OpenAI (cloud):**
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o-mini
OPENAI_BASEURL=https://api.openai.com/v1
```

**Option B — Ollama (local, recommended for air-gapped or cost-sensitive use):**
```bash
# Install Ollama: https://ollama.ai
# Pull a model: ollama pull qwen2.5-coder:14b
LLM_PROVIDER=openai
OPENAI_API_KEY=ollama          # any non-empty string
LLM_MODEL=qwen2.5-coder:14b   # or :32b if you have 20GB+ VRAM
OPENAI_BASEURL=http://localhost:11434/v1
```

**Option C — LM Studio (local):**
```bash
# Enable "Serve on Local Network" in LM Studio
# Verify model ID at http://your-ip:1234/v1/models
LLM_PROVIDER=openai
OPENAI_API_KEY=lm-studio
LLM_MODEL=qwen2.5-coder-14b-instruct
OPENAI_BASEURL=http://192.168.x.x:1234/v1
```

---

## Running

### Local (in-process) — simplest

```bash
cd trame-cfd-mcp/examples/cfd_assistant

# With the bundled test dataset
pvpython cfd_chat.py

# With your own data (.vtm, .vtk, .cgns, or any format ParaView reads)
pvpython cfd_chat.py /path/to/your/simulation.vtm
```

### Remote pvserver — for HPC or large datasets

This is the production mode. All data and rendering stay on the server; the browser receives
only JPEG frames. Client memory is constant regardless of dataset size.

**On the compute node / server:**
```bash
pvserver                          # default port 11111
# or
pvserver --server-port=22222
```

**On your workstation:**
```bash
cd trame-cfd-mcp/examples/cfd_assistant
pvpython cfd_chat.py --pvserver=<server-host>:11111 /server/path/to/data.vtm
```

> The data path must be valid on the **server** filesystem, not the client.

### Catalyst Live — connect to a running simulation

```bash
# Start your Catalyst-enabled simulation (see examples/catalyst/ for mock examples)
# Then:
pvpython cfd_chat.py --live --host localhost --port 22222

# Combined: pvserver + live
pvpython cfd_chat.py --pvserver=<host>:11111 --live
```

---

## UI Layout

Once running, open the URL printed to stdout (default `http://localhost:8080`):

| Control | Location | Action |
|---|---|---|
| Chat | Bottom-right icon | Type natural language queries |
| Pipeline browser | Left toolbar icon (or press `p`) | See/manage ParaView filters |
| Chart panel | Top-right chart icon | BL profiles, histograms, force distributions |
| Live connection | Top-right broadcast icon | Connect/disconnect Catalyst |
| Pause / Step | Top-right controls | Control simulation time stepping |

---

## Example Session

```
You: What data is loaded?
Assistant: Multi-block dataset — body surface and farfield volume. Fields: Velocity, Pressure, Cf.

You: Show vortices using lambda2
Assistant: Created λ₂ isosurface at threshold -500 (50th percentile of negative values).

You: Make them semi-transparent and color by pressure
Assistant: Set opacity to 0.5, colored by Pressure field.

You: Show the boundary layer at 50% chord
Assistant: BL profile at x/c=0.50: δ=0.023c, δ*=0.0031c, θ=0.0024c, H=1.31 — attached turbulent.

You: What is driving the drag increase between 4 and 8 degrees?
Assistant: Extracted Cf and Cp at both angles. Separation moved forward from x/c=0.78 to x/c=0.62.
          Pressure drag increased 40%; viscous drag unchanged. Wake momentum deficit up 55%.
          Separation-induced pressure drag dominates — consistent with incipient stall.

You: What is the session cost?
Assistant: 45,231 input tokens, 1,892 output tokens. Cost: ~$0.0034 (OpenAI) or ~$0.0008 (local).
```

---

## Architecture

```
User Query
    │
    ▼
  LLM (Plan)          ← domain ontology constrains tool selection
    │  ordered tool calls
    ▼
  WorkflowMCP         ← 26 deterministic CFD workflow tools
    │  server-side ProgrammableFilter scripts
    ▼
  pvserver            ← all data and rendering here; no field data moves to client
    │  structured results (KPIs, profiles, stats)
    ▼
  LLM (Interpret)     ← grounded explanation with quantitative specifics
```

Key principle: the LLM decides **what** to analyze and explains **what it means**.
Python tools handle **how** — deterministically, with full provenance.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full detail on the server-side analysis
infrastructure, dual-mode data access, provenance tracking, and Catalyst Live data flow.

---

## Workflow Tools

| Tool | Description |
|---|---|
| `list_data()` | List loaded sources and filters |
| `get_fields()` | Available fields with ranges |
| `analyze_data()` | Characterize dataset, recommend workflows |
| `show_vortices(method)` | Q-criterion, vorticity, or λ₂ isosurface |
| `show_streamlines()` | Flow streamlines seeded from wake region |
| `show_slice(location, normal)` | Planar cut with automatic field selection |
| `show_histogram(field)` | Field distribution chart |
| `show_forces()` | Cd/Cl via pressure integration + spanwise distribution |
| `show_boundary_layer(x_over_chord, span_fraction)` | BL profile: δ, δ*, θ, H |
| `show_boundary_layer_context()` | 3D visualization of BL probe locations |
| `show_flow_topology()` | Vortex core lines via VTK VortexCores |
| `update_representation(type, proxy)` | Surface / Wireframe / Points |
| `update_color(proxy, field)` | Recolor by field |
| `update_list_property(prop, value, proxy)` | Adjust isovalues / thresholds |
| `update_display_property(prop, value, proxy)` | Opacity, PBR, LineWidth, PointSize |
| `show_or_hide(proxy, visible)` | Toggle visibility |
| `set_view(direction)` | Camera angle (iso, +x, -x, +y, ...) |
| `save_screenshot(filename)` | Save current view |
| `save_state(filename)` | Save full ParaView state |
| `get_ontology()` | CFD domain knowledge for LLM explanation |
| `delete_filter(proxy)` | Remove filter from pipeline |
| `clear_all_filters()` | Reset to original data |

---

## Catalyst Live

Connect to a running simulation for real-time visualization and residual monitoring.

### Starting the app in live mode

```bash
pvpython cfd_chat.py --live --host localhost --port 22222

# Combined with pvserver (data stays on compute node)
pvpython cfd_chat.py --pvserver=<host>:11111 --live
```

### Workflow

```
1. Start your Catalyst-enabled simulation
2. Click the broadcast icon (top-right) to connect
3. Chat: "extract monitors"         → starts residual tracking
4. Click chart icon to see live convergence plot
5. Chat: "pause simulation"         → freeze for analysis
6. Chat: "extract grid"             → copy mesh to local session
7. Chat: "show grid colored by p"   → visualize
8. Chat: "resume simulation"        → continue
```

Or use `set_pause_on_connect()` before starting the simulation to auto-pause on connect.

### Simulation-side requirements

The simulation must expose a Catalyst Live connection on the configured port (default 22222).
In your Catalyst pipeline script:

```python
from paraview.catalyst import Options
options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"
```

### Monitor channel format

`extract_monitors()` looks for a channel named `"monitors"` by default. The simulation
must publish this channel as a **Blueprint mesh** via Conduit — Catalyst Live requires
mesh data, not tables or plain objects.

The expected Conduit node layout for the monitors channel:

```
catalyst/state/timestep                     ← integer
catalyst/state/time                         ← float

catalyst/channels/monitors/type             = "mesh"
catalyst/channels/monitors/data/coordsets/coords/type        = "explicit"
catalyst/channels/monitors/data/coordsets/coords/values/x    ← iteration array (float32)
catalyst/channels/monitors/data/coordsets/coords/values/y    ← zeros (float32)
catalyst/channels/monitors/data/coordsets/coords/values/z    ← zeros (float32)

catalyst/channels/monitors/data/topologies/mesh/type         = "points"
catalyst/channels/monitors/data/topologies/mesh/coordset     = "coords"

catalyst/channels/monitors/data/fields/iteration/association = "vertex"
catalyst/channels/monitors/data/fields/iteration/topology    = "mesh"
catalyst/channels/monitors/data/fields/iteration/values      ← iteration array

catalyst/channels/monitors/data/fields/continuity/association = "vertex"
catalyst/channels/monitors/data/fields/continuity/topology    = "mesh"
catalyst/channels/monitors/data/fields/continuity/values      ← residual array

# ... additional fields: momentum_x, momentum_y, momentum_z, energy, drag, lift, etc.
```

**Key constraint:** Each point in the mesh represents one iteration. Send the **full
history** each timestep (not just the current value) — the client deduplicates by
tracking the last seen iteration number.

**Field naming:** The chart legend uses the field names as-is. Use descriptive names
(`continuity`, `momentum_x`, `energy`) rather than generic ones (`res1`, `r2`).

A minimal Python example using the standalone Catalyst API:

```python
import catalyst_conduit as conduit
import catalyst

def send_monitors(solver):
    node = conduit.Node()
    n = solver.current_iteration

    node["catalyst/state/timestep"] = n
    node["catalyst/state/time"] = solver.time

    ch = node["catalyst/channels/monitors"]
    ch["type"] = "mesh"

    # Coordinate: use iteration number as x
    ch["data/coordsets/coords/type"] = "explicit"
    ch["data/coordsets/coords/values/x"].set_external(solver.iterations[:n])
    ch["data/coordsets/coords/values/y"].set(np.zeros(n, dtype=np.float32))
    ch["data/coordsets/coords/values/z"].set(np.zeros(n, dtype=np.float32))

    ch["data/topologies/mesh/type"] = "points"
    ch["data/topologies/mesh/coordset"] = "coords"

    for name, arr in solver.residuals.items():
        ch[f"data/fields/{name}/association"] = "vertex"
        ch[f"data/fields/{name}/topology"] = "mesh"
        ch[f"data/fields/{name}/values"].set_external(arr[:n])

    catalyst.execute(node)
```

See `examples/catalyst/mock_simulation.py` for a complete working example, and
`examples/catalyst/catalyst_pipeline_monitors.py` for the corresponding pipeline script.

### Catalyst Live tools

| Tool | Description |
|---|---|
| `connect_live(host, port, pause)` | Connect; optionally auto-pause |
| `set_pause_on_connect()` | Auto-pause when simulation connects |
| `disconnect_live()` | Disconnect and clean up |
| `pause_simulation()` | Freeze for analysis |
| `resume_simulation()` | Continue time stepping |
| `step_simulation(count)` | Advance N iterations then auto-pause |
| `set_breakpoint(iteration)` | Auto-pause at specific iteration |
| `clear_breakpoint()` | Remove active breakpoint |
| `extract_live_data(name)` | Extract named channel to local session |
| `show_live_source(name, color_by)` | Display extracted data |
| `extract_monitors(channel)` | Start residual monitoring (default: `"monitors"`) |
| `show_monitor_chart()` | Open convergence chart |
| `get_current_monitors()` | Latest monitor values |
| `get_live_status()` | Connection state and simulation time |

---

## Repository Layout

```
src/trame_cfd_mcp/
├── workflow_mcp.py          # 26 high-level MCP tools
├── workflows.py             # Workflow implementations
├── cfd_analysis.py          # CFD analysis (all runs server-side)
├── server_scripts/          # ProgrammableFilter scripts for pvserver
│   ├── vortex_threshold.py
│   ├── boundary_layer.py
│   ├── force_integration.py
│   ├── force_distribution.py
│   ├── detect_wake.py
│   ├── detect_streamwise.py
│   ├── field_statistics.py
│   ├── field_histogram.py
│   ├── find_region.py
│   └── centroid.py
├── catalyst_live.py         # Catalyst Live connection and tools
├── cost_tracker.py          # Token usage and cost estimation
└── ontology.json            # CFD domain knowledge (30 entries)

examples/cfd_assistant/
├── cfd_chat.py              # Main application entry point
├── .env.example             # LLM configuration template
├── test_workflows_basic.py  # Unit tests (no LLM, no API cost)
├── test_workflows.py        # LLM integration tests
├── test_boundary_layer.py   # BL analysis tests
└── test_ontology.py         # Ontology explanation tests

examples/catalyst/
├── catalyst_pipeline_monitors.py  # Catalyst pipeline with residual monitoring
├── mock_simulation.py             # Mock FUN3D-style simulation for testing
└── README.md
```

---

## Troubleshooting

**`ModuleNotFoundError: trame_cfd_mcp`**
Install with `pvpython -m pip install -e .`, not `pip install`. ParaView uses its own Python.

**`SSLError` or API calls fail on macOS**
The ParaView.app binary lacks SSL. Use conda ParaView or build from source.

**`pvpython: command not found`**
Add ParaView's bin directory to PATH: `export PATH=/path/to/ParaView/bin:$PATH`

**Data not loading in pvserver mode**
The path must exist on the **server** filesystem. For remote servers, stage the data there first.

**LLM gives poor results with local model**
Use at least `qwen2.5-coder:14b`. Models below 14B parameters struggle with multi-tool
orchestration. `qwen2.5-coder:32b` gives results comparable to GPT-4o-mini.

---

## License

BSD 3-Clause — compatible with ParaView and VTK.
