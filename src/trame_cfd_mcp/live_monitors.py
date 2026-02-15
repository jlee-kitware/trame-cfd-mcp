"""
Live residual monitor system for Catalyst.

SIMULATION SIDE (C++):
----------------------
The simulation should create a vtkTable with residual history and pass it as a channel:

```cpp
#include <vtkTable.h>
#include <vtkFloatArray.h>

// Create table with residual history
vtkNew<vtkTable> monitorTable;

vtkNew<vtkFloatArray> iterations;
iterations->SetName("Iteration");
iterations->SetNumberOfTuples(history_size);
for (int i = 0; i < history_size; i++) {
    iterations->SetValue(i, iteration_history[i]);
}
monitorTable->AddColumn(iterations);

vtkNew<vtkFloatArray> residuals;
residuals->SetName("Residual_L2");
residuals->SetNumberOfTuples(history_size);
for (int i = 0; i < history_size; i++) {
    residuals->SetValue(i, residual_history[i]);
}
monitorTable->AddColumn(residuals);

// Add to Conduit node as a channel
// Option A: Use VTK's Conduit bridge
conduit::Node meshNode;
vtkConduitSource::GetMeshFromVTKDataSet(monitorTable, meshNode);
node["catalyst/channels/monitors/data"] = meshNode;

// Option B: Put raw arrays in Conduit (simpler)
node["catalyst/channels/monitors/type"] = "mesh";  
node["catalyst/channels/monitors/data/coordsets/coords/type"] = "explicit";
node["catalyst/channels/monitors/data/coordsets/coords/values/x"].set_external(
    iteration_history, history_size);
// Use y for residuals
node["catalyst/channels/monitors/data/coordsets/coords/values/y"].set_external(
    residual_history, history_size);
```

PARAVIEW SIDE (Python):
-----------------------
Use this module to extract and chart the monitor data.
"""

from paraview import simple, servermanager
from paraview.live import ConnectToCatalyst, ExtractCatalystData, PauseCatalyst


class LiveResidualMonitor:
    """
    Connects to Catalyst Live and creates a real-time residual chart.
    
    Usage:
        monitor = LiveResidualMonitor()
        monitor.connect("localhost", 22222)
        monitor.create_residual_chart()
        
        # In your update loop:
        monitor.update()
    """
    
    def __init__(self):
        self._link = None
        self._monitor_source = None
        self._chart_view = None
        self._display = None
    
    def connect(self, host: str = "localhost", port: int = 22222) -> dict:
        """Connect to Catalyst simulation."""
        try:
            self._link = ConnectToCatalyst(host, port)
            return {"status": "connected", "host": host, "port": port}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def extract_monitors(self, channel_name: str = "monitors") -> dict:
        """
        Extract monitor data from the simulation.
        
        The simulation should provide a channel with this name containing
        the residual/monitor data.
        """
        if not self._link:
            return {"status": "error", "message": "Not connected"}
        
        try:
            self._monitor_source = ExtractCatalystData(self._link, channel_name)
            
            if self._monitor_source is None:
                return {
                    "status": "error", 
                    "message": f"Channel '{channel_name}' not found. Available channels can be seen in Pipeline Browser."
                }
            
            simple.UpdatePipeline(proxy=self._monitor_source)
            
            return {
                "status": "extracted",
                "channel": channel_name,
                "tip": "Use create_residual_chart() to visualize"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def create_residual_chart(self, 
                              x_array: str = "Iteration",
                              y_arrays: list = None,
                              log_scale: bool = True) -> dict:
        """
        Create a line chart showing residual convergence.
        
        Args:
            x_array: Name of the x-axis array (default: "Iteration")
            y_arrays: List of y-axis array names (default: all except x_array)
            log_scale: Use log scale for y-axis (default: True)
        """
        if not self._monitor_source:
            return {"status": "error", "message": "No monitor data. Call extract_monitors() first."}
        
        # Get available arrays
        info = self._monitor_source.GetDataInformation()
        
        # Create XY plot view
        self._chart_view = simple.CreateXYPlotView()
        self._chart_view.ViewSize = [800, 400]
        self._chart_view.ChartTitle = 'Residual Convergence'
        self._chart_view.BottomAxisTitle = x_array
        self._chart_view.LeftAxisTitle = 'Residual'
        self._chart_view.LeftAxisLogScale = 1 if log_scale else 0
        
        # Show the data
        self._display = simple.Show(self._monitor_source, self._chart_view)
        self._display.XArrayName = x_array
        self._display.UseIndexForXAxis = 0
        
        # Configure which series to show
        if y_arrays:
            self._display.SeriesVisibility = y_arrays
        
        simple.Render(self._chart_view)
        
        return {
            "status": "created",
            "x_array": x_array,
            "log_scale": log_scale
        }
    
    def update(self):
        """
        Update the chart with latest data from simulation.
        
        Call this periodically or when new data arrives.
        """
        if self._monitor_source:
            simple.UpdatePipeline(proxy=self._monitor_source)
        
        if self._chart_view:
            simple.Render(self._chart_view)
    
    def pause(self):
        """Pause the simulation."""
        if self._link:
            PauseCatalyst(self._link, True)
    
    def resume(self):
        """Resume the simulation."""
        if self._link:
            PauseCatalyst(self._link, False)
    
    def get_current_values(self) -> dict:
        """Get the latest residual values."""
        if not self._monitor_source:
            return {"status": "error", "message": "No monitor data"}
        
        self.update()
        
        # Get the data
        data = servermanager.Fetch(self._monitor_source)
        
        if data is None:
            return {"status": "error", "message": "No data available"}
        
        result = {"status": "ok", "values": {}}
        
        # Extract values from last row
        if hasattr(data, 'GetNumberOfRows'):
            # It's a table
            n_rows = data.GetNumberOfRows()
            n_cols = data.GetNumberOfColumns()
            
            if n_rows > 0:
                for i in range(n_cols):
                    col = data.GetColumn(i)
                    name = col.GetName()
                    value = col.GetValue(n_rows - 1)
                    result["values"][name] = value
        
        return result


# Convenience functions for use in MCP tools

_monitor = None

def get_live_monitor():
    """Get or create the global live monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = LiveResidualMonitor()
    return _monitor


def connect_and_monitor(host="localhost", port=22222, channel="monitors"):
    """
    One-shot function to connect and start monitoring.
    
    Returns the monitor instance for further interaction.
    """
    monitor = get_live_monitor()
    
    result = monitor.connect(host, port)
    if result["status"] != "connected":
        return result
    
    result = monitor.extract_monitors(channel)
    if result["status"] != "extracted":
        return result
    
    result = monitor.create_residual_chart()
    return result
