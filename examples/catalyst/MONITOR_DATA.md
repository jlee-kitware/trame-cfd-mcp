# How to Send Monitor Data from Your Simulation

## Overview

There are two ways to send monitor data (residuals, forces, etc.) to ParaView:

1. **As a VTK Table** - If your simulation already uses VTK
2. **As Conduit Blueprint data** - Pure Conduit, no VTK dependency

## Option 1: As Conduit Blueprint "Points" Mesh

This is the simplest approach - encode your residual history as a 1D point set:

```cpp
// In your C++ adaptor
void send_monitors(conduit::Node& node, 
                   int num_iterations,
                   float* iteration_array,
                   float* residual_continuity,
                   float* residual_momentum,
                   float* residual_energy,
                   float* drag_history,
                   float* lift_history) {
    
    // Set up as a "points" mesh - just a list of coordinates
    conduit::Node& monitors = node["catalyst/channels/monitors"];
    monitors["type"] = "mesh";
    
    // Coordset: use iteration as x, residual as y (for easy plotting)
    conduit::Node& coords = monitors["data/coordsets/coords"];
    coords["type"] = "explicit";
    coords["values/x"].set_external(iteration_array, num_iterations);
    coords["values/y"].set_external(residual_continuity, num_iterations);  // Primary residual
    coords["values/z"].set(std::vector<float>(num_iterations, 0.0f));  // z=0 for 2D plot
    
    // Topology: points (one point per iteration)
    conduit::Node& topo = monitors["data/topologies/points"];
    topo["type"] = "points";
    topo["coordset"] = "coords";
    
    // Fields: additional residuals and forces
    conduit::Node& fields = monitors["data/fields"];
    
    // Residual fields
    fields["continuity/association"] = "vertex";
    fields["continuity/topology"] = "points";
    fields["continuity/values"].set_external(residual_continuity, num_iterations);
    
    fields["momentum/association"] = "vertex";
    fields["momentum/topology"] = "points";
    fields["momentum/values"].set_external(residual_momentum, num_iterations);
    
    fields["energy/association"] = "vertex";
    fields["energy/topology"] = "points";
    fields["energy/values"].set_external(residual_energy, num_iterations);
    
    // Force fields
    fields["drag/association"] = "vertex";
    fields["drag/topology"] = "points";
    fields["drag/values"].set_external(drag_history, num_iterations);
    
    fields["lift/association"] = "vertex";
    fields["lift/topology"] = "points";
    fields["lift/values"].set_external(lift_history, num_iterations);
}
```

## Option 2: Send as Table (via Conduit)

Conduit doesn't directly support VTK tables, but you can encode tabular data:

```cpp
void send_monitor_table(conduit::Node& node, MonitorData& data) {
    // Use a special "table" channel that your pipeline script will interpret
    conduit::Node& table = node["catalyst/channels/monitor_table"];
    table["type"] = "object";  // Not a mesh - raw data
    
    // Column data
    table["data/columns/iteration"].set_external(data.iterations, data.count);
    table["data/columns/residual_L2"].set_external(data.residual_L2, data.count);
    table["data/columns/residual_Linf"].set_external(data.residual_Linf, data.count);
    table["data/columns/drag"].set_external(data.drag, data.count);
    table["data/columns/lift"].set_external(data.lift, data.count);
    
    // Metadata
    table["data/num_rows"] = data.count;
    table["data/current_iteration"] = data.current_iteration;
}
```

Then in your pipeline script, convert to VTK table:

```python
# catalyst_pipeline_monitors.py

def catalyst_execute(info):
    import vtk
    from vtk.util import numpy_support
    
    params = info.catalyst_params
    
    if params.has_path("channels/monitor_table/data"):
        table_data = params["channels/monitor_table/data"]
        
        # Create VTK table
        vtk_table = vtk.vtkTable()
        
        for col_name in ["iteration", "residual_L2", "residual_Linf", "drag", "lift"]:
            if table_data.has_path(f"columns/{col_name}"):
                arr = numpy_support.numpy_to_vtk(
                    table_data[f"columns/{col_name}"].value()
                )
                arr.SetName(col_name)
                vtk_table.AddColumn(arr)
        
        # Now vtk_table can be used for charting
        # ... create chart view, etc.
```

## On the ParaView Side (cfd_chat_live.py)

Once connected via Catalyst Live, the "monitors" channel appears as a source:

```python
from paraview.live import ConnectToCatalyst, ExtractCatalystData
from paraview import simple

# Connect
link = ConnectToCatalyst("localhost", 22222)

# Extract the monitor channel
monitors = ExtractCatalystData(link, "monitors")

# Create a PlotData filter to chart the point data
plot = simple.PlotData(Input=monitors)

# Create chart view
chart = simple.CreateXYPlotView()
chart.ChartTitle = "Residual Convergence"
chart.LeftAxisLogScale = 1

# Show it
display = simple.Show(plot, chart)
display.SeriesVisibility = ['continuity', 'momentum', 'energy']

simple.Render(chart)
```

## Fortran Example

```fortran
subroutine send_monitors(node, n_iter, iterations, residuals)
    use iso_c_binding
    use conduit
    implicit none
    
    type(C_PTR), intent(inout) :: node
    integer, intent(in) :: n_iter
    real(C_FLOAT), intent(in) :: iterations(n_iter)
    real(C_FLOAT), intent(in) :: residuals(n_iter)
    
    ! Set channel type
    call conduit_node_set_path_char8_str(node, &
        "catalyst/channels/monitors/type", "mesh")
    
    ! Set coordinates
    call conduit_node_set_path_float32_ptr(node, &
        "catalyst/channels/monitors/data/coordsets/coords/values/x", &
        iterations, n_iter)
    call conduit_node_set_path_float32_ptr(node, &
        "catalyst/channels/monitors/data/coordsets/coords/values/y", &
        residuals, n_iter)
    
    ! ... topology and fields as shown above
end subroutine
```

## Full Working Example

See `examples/catalyst/` directory:
- `catalyst_pipeline_monitors.py` - Pipeline script that extracts monitor data
- `mock_simulation.py` - Python mock simulation that sends monitor data
- `README.md` - Full documentation
