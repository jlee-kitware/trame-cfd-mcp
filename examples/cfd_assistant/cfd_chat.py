#!/usr/bin/env python
"""
CFD Analysis Chat - Interactive visualization with optional Catalyst Live.

Usage:
    # Load static data file
    pvpython cfd_chat.py data.vtm
    
    # Connect to live simulation
    pvpython cfd_chat.py --live --host localhost --port 22222
    
    # Both: load file and enable live connection
    pvpython cfd_chat.py data.vtm --live

UI Features:
    - Pipeline browser: click branch icon (left toolbar) or press 'p'
    - Live chart: click chart icon (top-right) - opens on LEFT side
    - Live connection: click broadcast icon (top-right, only with --live)
    - Chat: click chat icon (bottom-right)

Live Workflow Example:
    1. Start simulation: pvpython fedriver_monitors.py catalyst_pipeline_monitors.py
    2. Start app: pvpython cfd_chat.py --live
    3. Click broadcast icon to connect
    4. Chat: "extract monitors" - starts monitoring
    5. Click chart icon to see live residual convergence
    6. Chat: "extract grid" then "show grid" to see mesh
"""
import sys
import os
import asyncio
import argparse

os.environ.setdefault("VTK_MAX_TEXTURE_SIZE", "2048")
os.environ.setdefault("PV_PLUGIN_DEBUG", "0")

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple

import ptc
from ptc.apps.lite import Lite
from trame.widgets import vuetify3 as v3, html

try:
    from trame.widgets import plotly as trame_plotly
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("Warning: trame-plotly not available, live charts disabled")

from trame.widgets import llm
from trame_llm.core import LLMClient, ProgressType
from trame_cfd_mcp import WorkflowMCP
from trame_llm.paraview import ParaViewMCP


class CFDChatMCP:
    """MCP wrapper that adds cost tracking and optional live monitoring tools."""
    
    def __init__(self, workflow_mcp, llm_client, live_enabled=False, live_host="localhost", live_port=22222):
        self._workflow_mcp = workflow_mcp
        self._llm_client = llm_client
        self._live_enabled = live_enabled
        self._live_host = live_host
        self._live_port = live_port
        self._live_link = None
        self._display_session = None
        self._monitor_source = None
        self._monitoring_active = False
        self._extracted_sources = {}
        self._chart_config = None
        # Client-side accumulation of monitor history
        self._monitor_history = {
            'iteration': [],
            'continuity': [],
            'momentum_x': [],
            'momentum_y': [],
            'momentum_z': [],
            'energy': [],
        }
        self._last_iteration = -1
    
    @property
    def _app(self):
        """Get the trame app from the base MCP."""
        return self._workflow_mcp._base_mcp._app
    
    def _capture_chart_to_gallery(self, chart_view, title: str):
        """Capture a chart view as base64 PNG and add to workflow's gallery."""
        self._workflow_mcp._analysis._capture_chart_to_gallery(chart_view, title)
    
    def _update_gallery_chart(self, chart_view, title: str):
        """Update existing chart in gallery or add new one."""
        gallery = self._workflow_mcp._analysis._chart_gallery
        for i, entry in enumerate(gallery):
            if entry.get('title') == title:
                gallery.pop(i)
                break
        self._capture_chart_to_gallery(chart_view, title)
    
    # =========================================================================
    # Cost tracking tools
    # =========================================================================
    
    def get_session_cost(self) -> dict:
        """Get current chat session cost and usage statistics."""
        return self._llm_client.get_cost()
    
    def reset_session_cost(self) -> dict:
        """Reset the cost tracking counters to zero."""
        self._llm_client.reset_cost()
        return {"status": "reset", "message": "Cost counters reset to zero"}
    
    # =========================================================================
    # Live connection tools (only available if --live flag used)
    # =========================================================================
    
    def connect_live(self, host: str = None, port: int = None) -> dict:
        """
        Connect to a running Catalyst-enabled simulation.
        
        Args:
            host: Hostname (default from --host arg)
            port: Port number (default from --port arg)
        """
        if not self._live_enabled:
            return {"error": "Live mode not enabled. Restart with --live flag."}
        
        from paraview import servermanager
        from paraview.simple import SetActiveConnection
        
        host = host or self._live_host
        port = port or self._live_port
        
        try:
            # IMPORTANT: Save the display session before connecting to Catalyst
            # This is what ParaView GUI does - we need to restore it after connecting
            self._display_session = servermanager.ActiveConnection.Session
            
            # Connect to Catalyst - this changes the active connection
            self._live_link = servermanager.ConnectToCatalyst(host, port)
            
            # Process pending notifications (like ParaView's ProcessServerNotifications)
            pm = servermanager.vtkProcessModule.GetProcessModule()
            nam = pm.GetNetworkAccessManager()
            while nam.ProcessEvents(1) == 1:
                pass
            
            # Initialize the link
            self._live_link.InvokeCommand('Initialize')
            
            # CRITICAL: Restore the active connection to the display session
            # Without this, all subsequent operations try to work on the Catalyst
            # session instead of the local rendering session
            SetActiveConnection(servermanager.GetConnectionFromSession(self._display_session))
            
            # Ensure we have an active view
            view = simple.GetActiveView()
            if view is None:
                view = simple.GetActiveViewOrCreate('RenderView')
                print(f"[Live] Created new RenderView: {view}")
            
            return {
                "status": "connected",
                "host": host,
                "port": port,
                "tip": "Use 'pause simulation' then 'show grid' to visualize."
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def disconnect_live(self) -> dict:
        """Disconnect from the simulation."""
        if self._live_link:
            self._live_link = None
            self._display_session = None
            self._monitor_source = None
            self._monitoring_active = False
            self._extracted_sources = {}
        return {"status": "disconnected"}
    
    def is_connection_alive(self) -> bool:
        """Check if the live connection is still active."""
        if not self._live_link:
            return False
        try:
            # Try to get a property - will fail if connection dropped
            self._live_link.GetProperty('SimulationPaused')
            return True
        except:
            return False
    
    def get_live_status(self) -> dict:
        """Get current timestep and time from the live simulation."""
        if not self._live_link:
            return {"status": "not_connected"}
        
        try:
            time = simple.GetAnimationScene().TimeKeeper.Time
            return {"status": "connected", "time": time}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def pause_simulation(self) -> dict:
        """Pause the running simulation for detailed analysis."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        try:
            # Use same logic as paraview.live.PauseCatalyst
            current_state = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            if not current_state:
                self._live_link.GetProperty('SimulationPaused').SetElement(0, 1)
                self._live_link.UpdateVTKObjects()
            return {"status": "paused"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def resume_simulation(self) -> dict:
        """Resume a paused simulation."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        try:
            current_state = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            if current_state:
                self._live_link.GetProperty('SimulationPaused').SetElement(0, 0)
                self._live_link.UpdateVTKObjects()
                self._live_link.InvokeCommand('LiveChanged')
            return {"status": "resumed"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def extract_live_data(self, source_name: str) -> dict:
        """
        Extract data from the live simulation to local ParaView session.
        
        This uses the same mechanism as ParaView GUI's extract button.
        The data is copied from the simulation to the local session.
        
        Args:
            source_name: Name of the source to extract (e.g., "grid")
        """
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        if not self._display_session:
            return {"error": "Display session not available"}
        
        from paraview import servermanager
        
        try:
            # This is what paraview.live.ExtractCatalystData does:
            # 1. Create an extract from the link
            # 2. Register it in the display session
            proxy = self._live_link.CreateExtract('sources', source_name, 0)
            self._display_session.GetSessionProxyManager().RegisterProxy('sources', source_name, proxy)
            
            # Find it as a regular source
            extracted = simple.FindSource(source_name)
            
            if extracted:
                self._extracted_sources[source_name] = extracted
                
                # Get info without triggering full update
                info = extracted.GetDataInformation()
                n_points = info.GetNumberOfPoints()
                n_cells = info.GetNumberOfCells()
                
                # Update trame app to refresh pipeline browser
                if self._app:
                    self._app.update()
                    # Trigger pipeline browser refresh
                    if hasattr(self._app.server.controller, 'on_data_change'):
                        self._app.server.controller.on_data_change()
                
                return {
                    "status": "extracted",
                    "source": source_name,
                    "points": n_points,
                    "cells": n_cells,
                    "tip": "Data extracted. Use 'show grid' to visualize."
                }
            else:
                return {"status": "error", "message": f"Failed to extract '{source_name}'"}
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def show_live_source(self, source_name: str, color_by: str = None) -> dict:
        """
        Show a live source in the render view.
        
        Automatically extracts the data first if not already extracted.
        
        Args:
            source_name: Name of the source to show (e.g., "grid")
            color_by: Optional field name to color by
        """
        # Extract first if needed
        if source_name not in self._extracted_sources:
            if self._live_link:
                result = self.extract_live_data(source_name)
                if result.get("status") == "error":
                    return result
        
        # Get the source (either extracted or regular)
        source = self._extracted_sources.get(source_name) or simple.FindSource(source_name)
        
        if not source:
            available = [name for (name, _id) in simple.GetSources().keys()]
            return {"error": f"Source '{source_name}' not found. Available: {available}"}
        
        try:
            simple.SetActiveSource(source)
            rep = simple.Show(source)
            
            if color_by:
                # Use proxy's PointData/CellData interface for field lookup
                point_fields = list(source.PointData.keys())
                cell_fields = list(source.CellData.keys())
                
                location = None
                actual_name = color_by
                
                # Check point data
                for name in point_fields:
                    if name.lower() == color_by.lower():
                        location = "POINTS"
                        actual_name = name
                        break
                
                # Check cell data if not found in points
                if not location:
                    for name in cell_fields:
                        if name.lower() == color_by.lower():
                            location = "CELLS"
                            actual_name = name
                            break
                
                if location:
                    simple.ColorBy(rep, (location, actual_name))
                    rep.RescaleTransferFunctionToDataRange(True, False)
            
            view = simple.GetActiveView()
            simple.ResetCamera(view)
            simple.Render(view)
            
            # Update the trame app to refresh pipeline browser
            if self._app:
                self._app.update()
                # Trigger pipeline browser refresh
                if hasattr(self._app.server.controller, 'on_data_change'):
                    self._app.server.controller.on_data_change()
            
            return {
                "status": "shown",
                "source": source_name,
                "color_by": color_by,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def extract_monitors(self, channel_name: str = "monitors") -> dict:
        """
        Start monitoring residuals from the live simulation.
        
        Extracts once and then accumulates data on client side.
        """
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        
        try:
            from paraview.live import ExtractCatalystData, ProcessServerNotifications
            
            ProcessServerNotifications()
            extracted = ExtractCatalystData(self._live_link, channel_name)
            ProcessServerNotifications()
            
            if extracted:
                extracted.UpdatePipeline()
                self._monitor_source = extracted
                self._extracted_sources[channel_name] = extracted
                self._monitoring_active = True
                
                # Reset client-side history
                self._monitor_history = {
                    'iteration': [],
                    'continuity': [],
                    'momentum_x': [],
                    'momentum_y': [],
                    'momentum_z': [],
                    'energy': [],
                }
                self._last_iteration = -1
                
                info = extracted.GetDataInformation()
                n_points = info.GetNumberOfPoints()
                fields = list(extracted.PointData.keys())
                
                return {
                    "status": "monitoring",
                    "channel": channel_name,
                    "history_points": n_points,
                    "fields": fields,
                    "tip": "Open chart panel (top-right) to see live residuals."
                }
            else:
                available = [name for (name, _id) in simple.GetSources().keys()]
                return {
                    "status": "error", 
                    "message": f"Channel '{channel_name}' not found.",
                    "available_sources": available,
                }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def stop_monitoring(self) -> dict:
        """Stop monitoring residual values."""
        self._monitoring_active = False
        return {"status": "stopped"}
    
    def show_monitor_chart(self, 
                           x_field: str = "iteration",
                           y_fields: list | None = None,
                           log_scale: bool = True) -> dict:
        """
        Start showing the live residual chart.
        
        The chart appears in the right drawer panel and updates automatically.
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            self._monitor_source.UpdatePipeline()
            available_fields = list(self._monitor_source.PointData.keys())
            
            info = self._monitor_source.GetDataInformation()
            n_points = info.GetNumberOfPoints()
            
            # Store config (used by get_monitor_data)
            self._chart_config = {
                'x_field': x_field,
                'y_fields': y_fields or [f for f in available_fields if f not in ['iteration', 'time']],
                'log_scale': log_scale
            }
            
            return {
                "status": "chart_ready",
                "message": "Open the chart panel (top-right icon) to see live residuals",
                "history_points": n_points,
                "fields": available_fields,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def update_monitor_chart(self) -> dict:
        """Update the monitor chart with latest data from simulation.
        
        Note: The Plotly chart updates automatically. This method is kept
        for compatibility but is not needed with the live Plotly chart.
        """
        if not self._monitoring_active:
            return {"error": "Monitoring not active"}
        
        return {"status": "ok", "message": "Chart updates automatically"}
    
    def get_monitor_data(self) -> dict:
        """
        Get monitor data, accumulating new points from simulation.
        
        Extracts latest data and appends any new iterations to client-side history.
        """
        if not self._live_link or not self._monitoring_active:
            return {"error": "Not monitoring"}
        
        try:
            from paraview.live import ExtractCatalystData, ProcessServerNotifications
            from paraview import servermanager
            
            # Process events to sync with simulation
            ProcessServerNotifications()
            
            # Extract current data from simulation
            extracted = ExtractCatalystData(self._live_link, "monitors")
            if not extracted:
                return {"iteration": self._monitor_history['iteration'], 
                        "residuals": {k: v for k, v in self._monitor_history.items() if k != 'iteration'}}
            
            extracted.UpdatePipeline()
            data = servermanager.Fetch(extracted)
            
            # Unwrap composite/partitioned datasets
            while data is not None:
                if hasattr(data, 'GetPartition') and data.GetNumberOfPartitions() > 0:
                    data = data.GetPartition(0)
                elif hasattr(data, 'GetBlock') and data.GetNumberOfBlocks() > 0:
                    data = data.GetBlock(0)
                elif hasattr(data, 'GetNumberOfPoints'):
                    break  # We have a proper dataset
                else:
                    print(f"[Monitor] Unknown data type: {type(data)}")
                    data = None
                    break
            
            if data and hasattr(data, 'GetNumberOfPoints') and data.GetNumberOfPoints() > 0:
                pd = data.GetPointData()
                
                # Get all iterations from this extract
                iter_arr = pd.GetArray('iteration')
                if iter_arr:
                    for i in range(iter_arr.GetNumberOfTuples()):
                        iteration = iter_arr.GetValue(i)
                        
                        # Only add if we haven't seen this iteration
                        if iteration > self._last_iteration:
                            self._monitor_history['iteration'].append(iteration)
                            
                            for name in ['continuity', 'momentum_x', 'momentum_y', 'momentum_z', 'energy']:
                                arr = pd.GetArray(name)
                                if arr and i < arr.GetNumberOfTuples():
                                    self._monitor_history[name].append(arr.GetValue(i))
                            
                            self._last_iteration = iteration
            
            # Clean up the extracted source to avoid accumulating proxies
            simple.Delete(extracted)
            
            return {
                "iteration": self._monitor_history['iteration'],
                "residuals": {k: v for k, v in self._monitor_history.items() if k != 'iteration'}
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
    
    def get_current_monitors(self) -> dict:
        """Get the latest monitor values."""
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName()
            
            result = {"status": "ok", "data_type": data_type, "values": {}}
            
            if data_type == "vtkTable":
                row_info = info.GetRowDataInformation()
                result["num_rows"] = info.GetNumberOfRows()
                
                for i in range(row_info.GetNumberOfArrays()):
                    arr_info = row_info.GetArrayInformation(i)
                    name = arr_info.GetName()
                    ranges = arr_info.GetComponentRange(0)
                    result["values"][name] = {"min": ranges[0], "max": ranges[1]}
            else:
                point_info = info.GetPointDataInformation()
                result["num_points"] = info.GetNumberOfPoints()
                
                for i in range(point_info.GetNumberOfArrays()):
                    arr_info = point_info.GetArrayInformation(i)
                    name = arr_info.GetName()
                    ranges = arr_info.GetComponentRange(0)
                    result["values"][name] = {"min": ranges[0], "max": ranges[1]}
            
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration with all tools."""
        base_mcp = self._workflow_mcp.mcp
        
        tools = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        
        if self._live_enabled:
            tools.extend([
                self.connect_live,
                self.disconnect_live,
                self.get_live_status,
                self.pause_simulation,
                self.resume_simulation,
                self.extract_live_data,
                self.show_live_source,
                self.extract_monitors,
                self.show_monitor_chart,
                self.update_monitor_chart,
                self.get_current_monitors,
            ])
            
            base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

Workflow for visualizing live data:
1. connect_live() - Connect to simulation
2. pause_simulation() - Pause for detailed analysis
3. extract_live_data("grid") - Extract data to local session
4. show_live_source("grid", color_by="pressure") - Display with coloring

The extract step is REQUIRED when paused - it copies data from simulation memory.

Other tools:
- resume_simulation() - Continue after analysis
- extract_monitors("monitors") - Get residual data
- show_monitor_chart() - Visualize convergence
"""
        
        base_mcp["tools"] = tools
        return base_mcp


def main():
    parser = argparse.ArgumentParser(description='CFD Analysis Chat')
    parser.add_argument('data_file', nargs='?', default=None, help='Data file to load')
    parser.add_argument('--live', action='store_true', help='Enable Catalyst Live')
    parser.add_argument('--host', default='localhost', help='Catalyst host')
    parser.add_argument('--port', type=int, default=22222, help='Catalyst port')
    args = parser.parse_args()
    
    data_file = args.data_file
    if data_file is None and not args.live:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_file = os.path.join(script_dir, 'test.vtm')
        if os.path.exists(default_file):
            data_file = default_file
    
    if data_file and os.path.exists(data_file):
        reader = simple.OpenDataFile(data_file)
        simple.UpdatePipeline()
        simple.Show()
        simple.ResetCamera()
        print(f"Loaded: {data_file}")
    elif data_file:
        print(f"Warning: File not found: {data_file}")
    
    app = Lite()
    ctrl = app.server.controller
    app.state.trame__title = "CFD Analysis Assistant"
    app.state.chart_drawer_open = False
    app.state.chart_gallery = []
    app.state.live_enabled = args.live
    app.state.live_connected = False
    app.state.live_host = args.host
    app.state.live_chart_visible = False
    app.state.live_chart_status = "Not connected"
    app.state.live_port = args.port
    app.state.monitoring_active = False
    
    if args.live:
        from paraview import servermanager
        pm = servermanager.vtkProcessModule.GetProcessModule()
        nam = pm.GetNetworkAccessManager()
        
        last_source_count = [0]
        last_monitor_update = [0]
        
        def process_pv_events():
            try:
                nam.ProcessEvents(1)
                # Track source count silently (don't print every change)
                sources = simple.GetSources()
                last_source_count[0] = len(sources)
            except:
                pass
        
        def update_live_charts():
            """Update Plotly chart if monitoring is active."""
            try:
                # Check if connection dropped
                if app.state.live_connected and not chat_mcp.is_connection_alive():
                    # Connection was lost - update state
                    with app.state:
                        app.state.live_connected = False
                        app.state.monitoring_active = False
                        app.state.live_chart_status = "Simulation ended"
                    chat_mcp._monitoring_active = False
                    print("[Live] Connection to simulation dropped")
                    return
                
                # Sync monitoring_active state with chat_mcp
                if app.state.monitoring_active != chat_mcp._monitoring_active:
                    app.state.monitoring_active = chat_mcp._monitoring_active
                
                if chat_mcp._monitoring_active:
                    # Check if simulation is running (not paused)
                    paused = False
                    if chat_mcp._live_link:
                        try:
                            paused = chat_mcp._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
                        except:
                            pass
                    
                    if not paused:
                        # Get data and update Plotly figure
                        data = chat_mcp.get_monitor_data()
                        if "iteration" in data and data["iteration"]:
                            iterations = data["iteration"]
                            residuals = data.get("residuals", {})
                            
                            # Build Plotly figure
                            if PLOTLY_AVAILABLE:
                                fig = go.Figure()
                                for name, values in residuals.items():
                                    fig.add_trace(go.Scatter(
                                        x=iterations,
                                        y=values,
                                        mode='lines',
                                        name=name,
                                    ))
                                fig.update_layout(
                                    title="Residual Convergence",
                                    xaxis_title="Iteration",
                                    yaxis_title="Residual",
                                    yaxis_type="log",
                                    margin=dict(l=50, r=20, t=40, b=40),
                                    height=400,
                                    showlegend=True,
                                )
                                
                                # Update chart via state with context manager
                                if hasattr(app, 'chart_widget') and app.chart_widget:
                                    app.chart_widget.update(fig)
                                
                                with app.state:
                                    app.state.live_chart_status = f"Monitoring: {len(iterations)} iterations"
                                    app.state.flush()
                    else:
                        with app.state:
                            app.state.live_chart_status = "Simulation paused"
            except Exception as e:
                import traceback
                traceback.print_exc()
                with app.state:
                    app.state.live_chart_status = f"Error: {e}"
        
        async def live_event_loop():
            update_counter = [0]
            while True:
                process_pv_events()
                
                # Update charts every 5 iterations (0.5 seconds)
                update_counter[0] += 1
                if update_counter[0] >= 5:
                    update_live_charts()
                    update_counter[0] = 0
                
                # Push updated view to browser
                app.update()
                await asyncio.sleep(0.1)
        
        @app.server.controller.add("on_server_ready")
        def start_live_loop(**kwargs):
            asyncio.create_task(live_event_loop())
            print("Catalyst Live event processing started")
    
    print("Setting up LLM client...")
    llm_client = LLMClient(max_iteractions=15)
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    chat_mcp = CFDChatMCP(
        workflow_mcp, 
        llm_client,
        live_enabled=args.live,
        live_host=args.host,
        live_port=args.port
    )
    
    llm_client.register_mcp(chat_mcp)
    
    if args.live:
        print(f"MCP registered (Live: {args.host}:{args.port})")
    else:
        print("MCP registered")
    
    def refresh_charts():
        gallery = workflow_mcp.get_chart_gallery()
        app.state.chart_gallery = gallery.get("charts", [])
    
    def toggle_chart_drawer():
        refresh_charts()
        app.state.chart_drawer_open = not app.state.chart_drawer_open
    
    def delete_chart(index):
        workflow_mcp._analysis._chart_gallery.pop(index)
        refresh_charts()
    
    def clear_all_charts():
        workflow_mcp.clear_charts()
        refresh_charts()
    
    def toggle_live_connection():
        if app.state.live_connected:
            chat_mcp.disconnect_live()
            app.state.live_connected = False
        else:
            result = chat_mcp.connect_live()
            app.state.live_connected = result.get("status") == "connected"
    
    with app.ui:
        # Chart panel - floating card
        with v3.VCard(
            v_show="chart_drawer_open",
            style="position: fixed; top: 60px; left: 50px; z-index: 900; width: 520px; height: 550px;",
            elevation=8,
        ):
            with v3.VCardTitle(classes="d-flex justify-space-between align-center py-2 flex-shrink-0"):
                html.Span("Live Residuals", classes="text-subtitle-1")
                v3.VBtn(icon="mdi-close", click="chart_drawer_open = false", variant="text", size="small", density="compact")
            
            v3.VDivider()
            
            with v3.VCardText(classes="pa-2", style="height: calc(100% - 50px); overflow-y: auto;"):
                if PLOTLY_AVAILABLE:
                    # Show message when no data, chart when monitoring
                    with html.Div(v_if="!monitoring_active", classes="d-flex align-center justify-center", style="height: 380px;"):
                        html.P("Connect to a simulation and extract monitors to see residual data", classes="text-grey text-center")
                    
                    # Residual convergence chart - only visible when monitoring
                    with html.Div(v_show="monitoring_active", style="width: 100%; height: 400px;"):
                        initial_fig = go.Figure()
                        initial_fig.update_layout(
                            title="Residual Convergence",
                            xaxis_title="Iteration",
                            yaxis_title="Residual",
                            yaxis_type="log",
                            margin=dict(l=50, r=20, t=40, b=40),
                        )
                        app.chart_widget = trame_plotly.Figure(
                            initial_fig,
                            style="width: 100%; height: 100%;",
                        )
                else:
                    html.P("Install trame-plotly for live charts", classes="text-grey")
                
                # Status info at bottom - more padding
                html.P("{{ live_chart_status }}", classes="text-caption text-grey mt-3 mb-2")
        
        # Buttons in top-right corner - higher position to avoid chat overlap
        with html.Div(style="position: fixed; top: 12px; right: 80px; z-index: 1001; display: flex; gap: 8px;"):
            # Chart button
            v3.VBtn(
                icon="mdi-chart-line",
                click=toggle_chart_drawer,
                color=("chart_drawer_open ? 'primary' : ''",),
                variant="elevated",
                size="small",
                title="Live Residual Chart",
            )
            
            # Live connection button
            with html.Div(v_if="live_enabled"):
                v3.VBtn(
                    icon=("live_connected ? 'mdi-broadcast' : 'mdi-broadcast-off'",),
                    click=toggle_live_connection,
                    color=("live_connected ? 'success' : 'grey'",),
                    variant="elevated",
                    size="small",
                    title=("live_connected ? 'Connected' : 'Click to connect'",),
                )
        
        llm.Chat(
            app_name="cfd",
            enabled_message_types=[
                ProgressType.REQUEST,
                ProgressType.LLM_RESPONSE,
                ProgressType.MCP_SELECTION,
                ProgressType.MCP,
                ProgressType.MCP_ERROR,
                ProgressType.ERROR,
            ],
            llm_client=llm_client,
        )
    
    print("\nStarting CFD Analysis Assistant...")
    print("  - Pipeline browser: click branch icon (left toolbar) or press 'p'")
    print("  - Live chart: click chart icon (top-right)")
    if args.live:
        print(f"  - Live connection: click broadcast icon (top-right, {args.host}:{args.port})")
    print("  - Chat: click chat icon (bottom-right)")
    
    if args.live:
        print("\nLive workflow:")
        print("  1. Start simulation, click broadcast to connect")
        print("  2. 'extract monitors' to start monitoring")
        print("  3. Click chart icon to see residual convergence")
        print("  4. 'extract grid' then 'show grid' to visualize")
    
    app.start(open_browser=True)


if __name__ == "__main__":
    main()
