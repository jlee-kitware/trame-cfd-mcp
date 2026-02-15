"""
Catalyst pipeline script that extracts monitor data and creates live charts.

Usage:
    ./your_simulation catalyst_pipeline_monitors.py
    
The simulation should put monitor data in the Conduit node at:
    catalyst/channels/monitors/data/residuals/{name}: float
    catalyst/channels/monitors/data/forces/{name}: float
"""

from paraview.catalyst import Options

# Enable Live visualization
options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"

# Store history for charting
_history = {
    'iterations': [],
    'time': [],
    'residuals': {},
    'forces': {},
}


def catalyst_execute(info):
    """Called each timestep - extract monitor data."""
    
    # Get timestep info
    timestep = info.timestep
    time = info.time
    
    _history['iterations'].append(timestep)
    _history['time'].append(time)
    
    # Try to get monitor data from Conduit node
    # This requires the catalyst_conduit module
    try:
        params = info.catalyst_params
        
        # Extract residuals
        if params.has_path("channels/monitors/data/residuals"):
            res_node = params["channels/monitors/data/residuals"]
            for i in range(res_node.number_of_children()):
                child = res_node.child(i)
                name = child.name()
                value = child.value()
                if name not in _history['residuals']:
                    _history['residuals'][name] = []
                _history['residuals'][name].append(value)
        
        # Extract forces
        if params.has_path("channels/monitors/data/forces"):
            force_node = params["channels/monitors/data/forces"]
            for i in range(force_node.number_of_children()):
                child = force_node.child(i)
                name = child.name()
                value = child.value()
                if name not in _history['forces']:
                    _history['forces'][name] = []
                _history['forces'][name].append(value)
                
    except Exception as e:
        # catalyst_params may not be available in all modes
        print(f"Note: Could not access catalyst_params: {e}")
    
    # Print status
    if timestep % 100 == 0:
        print(f"[Monitor] Timestep {timestep}, time={time:.4f}")
        for name, values in _history['residuals'].items():
            if values:
                print(f"  {name}: {values[-1]:.6e}")


def get_history():
    """Get the accumulated history (for use by connected ParaView)."""
    return _history


# Alternative: Use a Table Extractor to make data available
def create_monitor_table():
    """Create a VTK table from monitor history for visualization."""
    import vtk
    from vtk.util import numpy_support
    import numpy as np
    
    table = vtk.vtkTable()
    
    if not _history['iterations']:
        return table
    
    # Add iteration column
    iters = np.array(_history['iterations'], dtype=np.float64)
    arr = numpy_support.numpy_to_vtk(iters)
    arr.SetName("Iteration")
    table.AddColumn(arr)
    
    # Add residual columns
    for name, values in _history['residuals'].items():
        if values:
            vals = np.array(values, dtype=np.float64)
            arr = numpy_support.numpy_to_vtk(vals)
            arr.SetName(name)
            table.AddColumn(arr)
    
    # Add force columns
    for name, values in _history['forces'].items():
        if values:
            vals = np.array(values, dtype=np.float64)
            arr = numpy_support.numpy_to_vtk(vals)
            arr.SetName(f"Force_{name}")
            table.AddColumn(arr)
    
    return table
