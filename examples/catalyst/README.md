# Catalyst Live Integration

This document explains how to connect trame-cfd-mcp to a running simulation via Catalyst Live.

## Architecture

```
SIMULATION HOST                              VISUALIZATION HOST
┌────────────────────────────────────┐      ┌────────────────────────────────┐
│                                    │      │                                │
│  ┌──────────────────────────────┐  │      │  ┌──────────────────────────┐  │
│  │     Your Simulation          │  │      │  │   cfd_chat_live.py       │  │
│  │     (FUN3D, OpenFOAM, etc.)  │  │      │  │   (ParaView + LLM)       │  │
│  └──────────────┬───────────────┘  │      │  └──────────────▲───────────┘  │
│                 │                  │      │                 │              │
│                 │ catalyst_execute()      │                 │              │
│                 ▼                  │      │                 │              │
│  ┌──────────────────────────────┐  │      │                 │              │
│  │     Catalyst Library         │  │      │                 │              │
│  │     + Pipeline Script        │──┼──────┼─────────────────┘              │
│  │     (enables Live)           │  │ TCP  │  Port 22222                    │
│  └──────────────────────────────┘  │      │                                │
│                                    │      │                                │
└────────────────────────────────────┘      └────────────────────────────────┘
```

## Key Points

1. **The simulation doesn't push data directly** - It calls `catalyst_execute()` which triggers the pipeline
2. **The pipeline script enables Live** - Via `options.EnableCatalystLive = True`
3. **Catalyst waits for ParaView** - When Live is enabled, Catalyst holds data available for a connecting ParaView client
4. **ParaView pulls the data** - When you connect via `Catalyst > Connect`, ParaView requests the data

## Setup Steps

### 1. Simulation Side: Create Pipeline Script

```python
# catalyst_pipeline_live.py
from paraview.catalyst import Options

options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"
```

### 2. Simulation Side: Pass Script to Simulation

```bash
# Environment setup
export CATALYST_IMPLEMENTATION_PATHS=/path/to/paraview/lib/catalyst
export CATALYST_IMPLEMENTATION_NAME=paraview

# Run simulation with pipeline
./my_simulation catalyst_pipeline_live.py
```

### 3. Visualization Side: Connect with cfd_chat_live.py

```bash
# On visualization machine (can be same or different host)
pvpython cfd_chat_live.py --host simulation_hostname --port 22222
```

Or in the chat interface:
```
You: Connect to the simulation at 192.168.1.100 port 22222
Assistant: [calls connect_live] Connected! Live data now available...
```

## For Your Adaptor

If you're writing a C++ adaptor, here's the minimal code:

```cpp
#include <catalyst.hpp>

// Called once at simulation start
void initialize(int argc, char* argv[]) {
    // argv should contain path to pipeline script
    catalyst_initialize(argc, argv);
}

// Called every timestep
void coprocess(double time, int cycle, YourMesh* mesh) {
    conduit::Node node;
    
    // Required: time/cycle info
    node["catalyst/state/timestep"] = cycle;
    node["catalyst/state/time"] = time;
    
    // Required: mesh data in Conduit Blueprint format
    // See: https://llnl-conduit.readthedocs.io/en/latest/blueprint_mesh.html
    
    node["catalyst/channels/input/type"] = "mesh";
    
    // Coordinates
    node["catalyst/channels/input/data/coordsets/coords/type"] = "explicit";
    node["catalyst/channels/input/data/coordsets/coords/values/x"].set_external(
        mesh->x_coords, mesh->num_points);
    // ... y, z ...
    
    // Topology
    node["catalyst/channels/input/data/topologies/mesh/type"] = "unstructured";
    node["catalyst/channels/input/data/topologies/mesh/coordset"] = "coords";
    node["catalyst/channels/input/data/topologies/mesh/elements/shape"] = "hex";
    node["catalyst/channels/input/data/topologies/mesh/elements/connectivity"].set_external(
        mesh->connectivity, mesh->num_cells * 8);
    
    // Fields
    node["catalyst/channels/input/data/fields/pressure/association"] = "element";
    node["catalyst/channels/input/data/fields/pressure/topology"] = "mesh";
    node["catalyst/channels/input/data/fields/pressure/values"].set_external(
        mesh->pressure, mesh->num_cells);
    
    // Execute - this makes data available to connected ParaView
    catalyst_execute(conduit::c_node(&node));
}

// Called at simulation end
void finalize() {
    catalyst_finalize();
}
```

## Using with trame-cfd-mcp

Once connected, all the normal tools work on live data:

```
You: What data is available?
Assistant: [calls list_data] Live data channel "input" with pressure, velocity...

You: Show vortices
Assistant: [calls show_vortices] Created lambda2 isosurface on live data...

You: Pause the simulation
Assistant: [calls pause_simulation] Simulation paused at timestep 150

You: [analyze in detail]

You: Resume
Assistant: [calls resume_simulation] Simulation continuing...
```

## Troubleshooting

1. **Connection refused**: Make sure simulation is running and Live is enabled in pipeline script
2. **No data**: Check that `catalyst_execute()` is being called each timestep
3. **Firewall**: Port 22222 must be open between simulation and visualization hosts
4. **MPI mismatch**: ParaView and simulation should use compatible MPI versions
