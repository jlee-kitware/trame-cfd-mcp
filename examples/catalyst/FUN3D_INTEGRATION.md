# Fun3D Catalyst Integration for Live Monitoring

## Overview

To make Fun3D compatible with the live residual monitoring in `cfd_chat.py`, you need to send two Catalyst channels:

1. **`grid`** - The mesh/field data (you likely already have this)
2. **`monitors_current`** - Current timestep residuals as a single point

## Required Conduit Structure

### Channel: `monitors_current`

The pipeline expects a **single point** per timestep with the current residual values. The pipeline script accumulates these into a history.

```
catalyst/
├── state/
│   ├── timestep: <int>
│   └── time: <float>
├── channels/
│   └── monitors_current/
│       ├── type: "mesh"
│       └── data/
│           ├── coordsets/coords/
│           │   ├── type: "explicit"
│           │   └── values/
│           │       ├── x: [<timestep as float>]  # Single value
│           │       ├── y: [0.0]
│           │       └── z: [0.0]
│           ├── topologies/mesh/
│           │   ├── type: "unstructured"
│           │   ├── coordset: "coords"
│           │   └── elements/
│           │       ├── shape: "point"
│           │       └── connectivity: [0]
│           └── fields/
│               ├── iteration/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<timestep as float>]
│               ├── time/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<time>]
│               ├── continuity/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<residual_value>]
│               ├── momentum_x/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<residual_value>]
│               ├── momentum_y/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<residual_value>]
│               ├── momentum_z/
│               │   ├── association: "vertex"
│               │   ├── topology: "mesh"
│               │   └── values: [<residual_value>]
│               └── energy/
│                   ├── association: "vertex"
│                   ├── topology: "mesh"
│                   └── values: [<residual_value>]
```

## Example C++ Implementation

```cpp
#include <catalyst.hpp>
#include <catalyst_conduit.hpp>

void send_monitor_data(conduit_node* node, int timestep, double time,
                       double res_cont, double res_mom_x, double res_mom_y, 
                       double res_mom_z, double res_energy) {
    
    // State info
    conduit_node_set_path_int64(node, "catalyst/state/timestep", timestep);
    conduit_node_set_path_float64(node, "catalyst/state/time", time);
    
    // monitors_current channel
    conduit_node_set_path_char8_str(node, 
        "catalyst/channels/monitors_current/type", "mesh");
    
    // Coordset - single point
    conduit_node_set_path_char8_str(node,
        "catalyst/channels/monitors_current/data/coordsets/coords/type", "explicit");
    
    double x_coord = (double)timestep;
    double zero = 0.0;
    conduit_node_set_path_float64_ptr(node,
        "catalyst/channels/monitors_current/data/coordsets/coords/values/x", &x_coord, 1);
    conduit_node_set_path_float64_ptr(node,
        "catalyst/channels/monitors_current/data/coordsets/coords/values/y", &zero, 1);
    conduit_node_set_path_float64_ptr(node,
        "catalyst/channels/monitors_current/data/coordsets/coords/values/z", &zero, 1);
    
    // Topology - point
    conduit_node_set_path_char8_str(node,
        "catalyst/channels/monitors_current/data/topologies/mesh/type", "unstructured");
    conduit_node_set_path_char8_str(node,
        "catalyst/channels/monitors_current/data/topologies/mesh/coordset", "coords");
    conduit_node_set_path_char8_str(node,
        "catalyst/channels/monitors_current/data/topologies/mesh/elements/shape", "point");
    int connectivity = 0;
    conduit_node_set_path_int32_ptr(node,
        "catalyst/channels/monitors_current/data/topologies/mesh/elements/connectivity", 
        &connectivity, 1);
    
    // Fields
    #define SET_FIELD(name, value) \
        conduit_node_set_path_char8_str(node, \
            "catalyst/channels/monitors_current/data/fields/" name "/association", "vertex"); \
        conduit_node_set_path_char8_str(node, \
            "catalyst/channels/monitors_current/data/fields/" name "/topology", "mesh"); \
        { double v = value; \
          conduit_node_set_path_float64_ptr(node, \
            "catalyst/channels/monitors_current/data/fields/" name "/values", &v, 1); }
    
    double iter_val = (double)timestep;
    SET_FIELD("iteration", iter_val);
    SET_FIELD("time", time);
    SET_FIELD("continuity", res_cont);
    SET_FIELD("momentum_x", res_mom_x);
    SET_FIELD("momentum_y", res_mom_y);
    SET_FIELD("momentum_z", res_mom_z);
    SET_FIELD("energy", res_energy);
    
    #undef SET_FIELD
}

// In your main loop:
void fun3d_catalyst_execute(int timestep, double time, /* grid data */) {
    conduit_node* node = conduit_node_create();
    
    // Add grid channel (your existing code)
    // ...
    
    // Add monitors channel
    double res_cont = get_continuity_residual();
    double res_mom_x = get_momentum_x_residual();
    double res_mom_y = get_momentum_y_residual();
    double res_mom_z = get_momentum_z_residual();
    double res_energy = get_energy_residual();
    
    send_monitor_data(node, timestep, time, 
                      res_cont, res_mom_x, res_mom_y, res_mom_z, res_energy);
    
    catalyst_execute(node);
    conduit_node_destroy(node);
}
```

## Fortran Implementation

```fortran
subroutine send_monitor_data(node, timestep, time, &
                             res_cont, res_mom_x, res_mom_y, res_mom_z, res_energy)
    use catalyst_conduit_mod
    type(conduit_node), intent(inout) :: node
    integer, intent(in) :: timestep
    real(8), intent(in) :: time, res_cont, res_mom_x, res_mom_y, res_mom_z, res_energy
    
    real(8) :: x_coord(1), y_coord(1), z_coord(1), iter_val(1)
    integer :: connectivity(1)
    real(8) :: field_val(1)
    
    x_coord(1) = dble(timestep)
    y_coord(1) = 0.0d0
    z_coord(1) = 0.0d0
    connectivity(1) = 0
    iter_val(1) = dble(timestep)
    
    ! Coordset
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/type", "mesh")
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/coordsets/coords/type", "explicit")
    call conduit_node_set_path_float64_ptr(node, &
        "catalyst/channels/monitors_current/data/coordsets/coords/values/x", x_coord, 1)
    call conduit_node_set_path_float64_ptr(node, &
        "catalyst/channels/monitors_current/data/coordsets/coords/values/y", y_coord, 1)
    call conduit_node_set_path_float64_ptr(node, &
        "catalyst/channels/monitors_current/data/coordsets/coords/values/z", z_coord, 1)
    
    ! Topology
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/topologies/mesh/type", "unstructured")
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/topologies/mesh/coordset", "coords")
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/topologies/mesh/elements/shape", "point")
    call conduit_node_set_path_int32_ptr(node, &
        "catalyst/channels/monitors_current/data/topologies/mesh/elements/connectivity", &
        connectivity, 1)
    
    ! Fields - iteration
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/fields/iteration/association", "vertex")
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors_current/data/fields/iteration/topology", "mesh")
    call conduit_node_set_path_float64_ptr(node, &
        "catalyst/channels/monitors_current/data/fields/iteration/values", iter_val, 1)
    
    ! Similar for time, continuity, momentum_x, momentum_y, momentum_z, energy...
    ! (See full pattern above)
    
end subroutine
```

## Key Points

1. **Channel name must be `monitors_current`** - The pipeline script looks for this specific name

2. **Field names must match exactly:**
   - `iteration` (float, required)
   - `time` (float, optional)
   - `continuity` (float, required for chart)
   - `momentum_x` (float, required for chart)
   - `momentum_y` (float, required for chart)
   - `momentum_z` (float, required for chart)
   - `energy` (float, required for chart)

3. **Single point per call** - Send only the current timestep's values. The pipeline script (`catalyst_pipeline_monitors.py`) accumulates the history.

4. **Pipeline script** - Use `catalyst_pipeline_monitors.py` from `catalyst-examples/ParaView/PythonSteering/`

## Testing

1. Start Fun3D with the pipeline script:
   ```bash
   mpirun -np 4 fun3d.mpi --catalyst_script catalyst_pipeline_monitors.py
   ```

2. Connect with cfd_chat:
   ```bash
   pvpython cfd_chat.py --live --host <hostname> --port 22222
   ```

3. In chat:
   - "extract monitors" - starts monitoring
   - Click chart icon to see live residuals

## Alternative: Full History Mode

If you prefer to send the full history from Fun3D (instead of letting the pipeline accumulate), use channel name `monitors` and send all history points. See `mock_simulation.py:create_monitor_node()` for that approach.
