"""
Catalyst pipeline that accumulates monitor data over time.

The simulation sends ONLY the current iteration's values.
This script accumulates history and creates the chart.

SIMULATION SIDE (send only current values):
    node["catalyst/channels/monitors/data/iteration"] = current_iter;
    node["catalyst/channels/monitors/data/residual_continuity"] = res_cont;
    node["catalyst/channels/monitors/data/residual_momentum"] = res_mom;
    node["catalyst/channels/monitors/data/drag"] = Cd;
    node["catalyst/channels/monitors/data/lift"] = Cl;
"""

from paraview.catalyst import Options

# Enable Live visualization
options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"

# Accumulated history (persists across catalyst_execute calls)
_history = {
    'iteration': [],
    'time': [],
    'residual_continuity': [],
    'residual_momentum': [],
    'residual_energy': [],
    'drag': [],
    'lift': [],
}

# ParaView objects
_chart_view = None
_table_source = None


def catalyst_execute(info):
    """Called each timestep - accumulate monitor data."""
    global _chart_view, _table_source
    
    # Get timestep info
    timestep = info.timestep
    time = info.time
    
    # Try to get monitor data from Conduit node
    try:
        params = info.catalyst_params
        
        # Accumulate current values
        _history['iteration'].append(timestep)
        _history['time'].append(time)
        
        # Extract scalar monitor values
        if params.has_path("channels/monitors/data"):
            data = params["channels/monitors/data"]
            
            for key in ['residual_continuity', 'residual_momentum', 'residual_energy', 'drag', 'lift']:
                if data.has_path(key):
                    _history[key].append(float(data[key].value()))
                elif key in _history and _history[key]:
                    # Keep last value if not provided
                    _history[key].append(_history[key][-1])
                else:
                    _history[key].append(0.0)
        
        # Create/update chart every 10 iterations
        if timestep > 0 and timestep % 10 == 0:
            _update_chart()
            
    except Exception as e:
        print(f"[Monitor] Error: {e}")
    
    # Print status
    if timestep % 50 == 0:
        print(f"[Monitor] Iter {timestep}: "
              f"res={_history['residual_continuity'][-1] if _history['residual_continuity'] else 'N/A':.2e}")


def _update_chart():
    """Create or update the residual chart."""
    global _chart_view, _table_source
    
    from paraview import simple
    import vtk
    from vtk.util import numpy_support
    import numpy as np
    
    if not _history['iteration']:
        return
    
    # Create table
    vtk_table = vtk.vtkTable()
    
    # Add columns
    for name, values in _history.items():
        if values:
            arr = numpy_support.numpy_to_vtk(np.array(values, dtype=np.float64))
            arr.SetName(name)
            vtk_table.AddColumn(arr)
    
    # Create or update source
    if _table_source is None:
        _table_source = simple.TrivialProducer(registrationName="MonitorData")
    
    _table_source.GetClientSideObject().SetOutput(vtk_table)
    _table_source.UpdatePipeline()
    
    # Create chart view if needed
    if _chart_view is None:
        _chart_view = simple.CreateXYPlotView()
        _chart_view.ViewSize = [800, 400]
        _chart_view.ChartTitle = 'Residual Convergence'
        _chart_view.BottomAxisTitle = 'Iteration'
        _chart_view.LeftAxisTitle = 'Residual'
        _chart_view.LeftAxisLogScale = 1
        
        display = simple.Show(_table_source, _chart_view)
        display.XArrayName = 'iteration'
        display.UseIndexForXAxis = 0
        display.SeriesVisibility = ['residual_continuity', 'residual_momentum']
    
    simple.Render(_chart_view)


def get_history():
    """Get accumulated history (for external access)."""
    return _history.copy()
