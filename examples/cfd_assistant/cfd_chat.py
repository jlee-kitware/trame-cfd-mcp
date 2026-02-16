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
    - Chart gallery: click chart icon (top-right)
    - Live connection: click broadcast icon (top-right, only with --live)
    - Chat: click chat icon (bottom-right)

Live Monitor Example:
    You: Connect to the simulation
    You: Show the residual chart
    You: What's the current drag coefficient?
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
        self._monitor_source = None
        self._monitor_history = []  # Accumulated monitor data
        self._monitor_chart = None
    
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
        
        host = host or self._live_host
        port = port or self._live_port
        
        try:
            # Use servermanager directly instead of paraview.live wrapper
            self._live_link = servermanager.ConnectToCatalyst(host, port)
            
            # Initialize the link - this is required!
            self._live_link.InvokeCommand('Initialize')
            
            # Process any pending events
            pm = servermanager.vtkProcessModule.GetProcessModule()
            nam = pm.GetNetworkAccessManager()
            for _ in range(10):  # Process a few events
                nam.ProcessEvents(100)  # 100ms timeout
            
            # Ensure we have an active view (Catalyst connection can break this)
            view = simple.GetActiveView()
            if view is None:
                view = simple.GetActiveViewOrCreate('RenderView')
                print(f"[Live] Created new RenderView: {view}")
            
            return {
                "status": "connected",
                "host": host,
                "port": port,
                "tip": "Data should appear in pipeline browser. Use list_data() to see sources."
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def disconnect_live(self) -> dict:
        """Disconnect from the simulation."""
        if self._live_link:
            self._live_link = None
            self._monitor_source = None
        return {"status": "disconnected"}
    
    def get_live_status(self) -> dict:
        """Get current timestep and time from the live simulation."""
        if not self._live_link:
            return {"status": "not_connected"}
        
        try:
            # Get current time from animation
            time = simple.GetAnimationScene().TimeKeeper.Time
            return {"status": "connected", "time": time}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def pause_simulation(self) -> dict:
        """Pause the running simulation for detailed analysis."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        from paraview.live import PauseCatalyst
        try:
            PauseCatalyst(self._live_link, True)
            return {"status": "paused"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def resume_simulation(self) -> dict:
        """Resume a paused simulation."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        from paraview.live import PauseCatalyst
        try:
            PauseCatalyst(self._live_link, False)
            return {"status": "resumed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def extract_monitors(self, channel_name: str = "monitors") -> dict:
        """
        Extract monitor data channel from the live simulation.
        
        The simulation should provide a channel with residuals/forces.
        Call this after connect_live() to access monitor data.
        
        Args:
            channel_name: Name of the monitor channel (default: "monitors")
        """
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        
        try:
            # Find the source by name in the pipeline
            # ExtractCatalystData has issues with vtkTable, so look for existing source
            sources = simple.GetSources()
            
            # Look for a source matching the channel name
            for (name, _id), proxy in sources.items():
                if channel_name.lower() in name.lower():
                    self._monitor_source = proxy
                    break
            
            # If not found by name, try ExtractCatalystData (may fail for tables)
            if self._monitor_source is None:
                from paraview.live import ExtractCatalystData
                try:
                    self._monitor_source = ExtractCatalystData(self._live_link, channel_name)
                except Exception as e:
                    # ExtractCatalystData failed - check if source exists anyway
                    sources = simple.GetSources()
                    for (name, _id), proxy in sources.items():
                        if channel_name.lower() in name.lower():
                            self._monitor_source = proxy
                            break
            
            if self._monitor_source is None:
                # List available sources for debugging
                available = [name for (name, _id) in simple.GetSources().keys()]
                return {
                    "status": "error",
                    "message": f"Channel '{channel_name}' not found.",
                    "available_sources": available,
                    "tip": "Check pipeline browser for available channels."
                }
            
            # Don't call UpdatePipeline - it triggers Fetch which fails for tables
            # Just get info
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName() if info else "unknown"
            
            return {
                "status": "extracted",
                "channel": channel_name,
                "data_type": data_type,
                "tip": "Use show_monitor_chart() to visualize residuals."
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def show_monitor_chart(self, 
                           x_field: str = "iteration",
                           y_fields: list = None,
                           log_scale: bool = True) -> dict:
        """
        Create a convergence chart from the extracted monitor data.
        
        Args:
            x_field: Field for x-axis (default: "iteration")
            y_fields: Fields to plot (default: all residual_* fields)
            log_scale: Use log scale for y-axis (default: True)
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            # Don't call UpdatePipeline - it triggers Fetch which fails for vtkTable
            # Get data info from proxy directly
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName()
            
            # Get available fields from data information
            available_fields = []
            if data_type == "vtkTable":
                # For tables, get row data (columns)
                row_info = info.GetRowDataInformation()
                for i in range(row_info.GetNumberOfArrays()):
                    available_fields.append(row_info.GetArrayInformation(i).GetName())
            else:
                # For meshes, get point data
                point_info = info.GetPointDataInformation()
                for i in range(point_info.GetNumberOfArrays()):
                    available_fields.append(point_info.GetArrayInformation(i).GetName())
            
            # Auto-detect residual fields if not specified
            if y_fields is None:
                y_fields = []
                for name in available_fields:
                    if name == x_field:
                        continue
                    if 'residual' in name.lower() or name in ['continuity', 'momentum', 'energy']:
                        y_fields.append(name)
                # If no residuals found, show all numeric fields except x
                if not y_fields:
                    y_fields = [f for f in available_fields if f != x_field]
            
            # Create XY plot view
            chart = simple.CreateXYPlotView()
            chart.ViewSize = [800, 400]
            chart.ChartTitle = "Residual Convergence"
            chart.BottomAxisTitle = x_field
            chart.LeftAxisTitle = "Residual"
            chart.LeftAxisLogScale = 1 if log_scale else 0
            
            # Show directly on chart - no PlotData filter needed for tables
            display = simple.Show(self._monitor_source, chart)
            display.XArrayName = x_field
            display.UseIndexForXAxis = 0
            
            if y_fields:
                display.SeriesVisibility = y_fields
            
            simple.Render(chart)
            
            self._monitor_chart = chart
            
            return {
                "status": "created",
                "data_type": data_type,
                "chart": "Residual Convergence",
                "x_field": x_field,
                "y_fields": y_fields,
                "available_fields": available_fields,
                "log_scale": log_scale,
                "tip": "Chart updates when you call update_monitor_chart()"
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def update_monitor_chart(self) -> dict:
        """Update the monitor chart with latest data from simulation."""
        if not self._monitor_source:
            return {"error": "No monitor data extracted"}
        
        try:
            # Don't call UpdatePipeline for vtkTable sources
            if self._monitor_chart:
                simple.Render(self._monitor_chart)
            return {"status": "updated"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_current_monitors(self) -> dict:
        """Get the latest monitor values (residuals, forces, etc.)."""
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            # Don't call UpdatePipeline - it triggers Fetch which fails for vtkTable
            # Get data info from proxy directly
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName()
            
            result = {"status": "ok", "data_type": data_type, "values": {}}
            
            if data_type == "vtkTable":
                # For tables, get row data info
                row_info = info.GetRowDataInformation()
                n_rows = info.GetNumberOfRows()
                result["num_rows"] = n_rows
                
                for i in range(row_info.GetNumberOfArrays()):
                    arr_info = row_info.GetArrayInformation(i)
                    name = arr_info.GetName()
                    # Get range (min, max) - last value would need Fetch
                    ranges = arr_info.GetComponentRange(0)
                    result["values"][name] = {"min": ranges[0], "max": ranges[1]}
            else:
                # For meshes, get point data info
                point_info = info.GetPointDataInformation()
                n_points = info.GetNumberOfPoints()
                result["num_points"] = n_points
                
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
        
        # Always add cost tools
        tools = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        
        # Add live tools if enabled
        if self._live_enabled:
            tools.extend([
                self.connect_live,
                self.disconnect_live,
                self.get_live_status,
                self.pause_simulation,
                self.resume_simulation,
                self.extract_monitors,
                self.show_monitor_chart,
                self.update_monitor_chart,
                self.get_current_monitors,
            ])
            
            base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

Connect to running Catalyst-enabled simulations:
1. connect_live(host, port) - Connect to simulation
2. extract_monitors("monitors") - Get the monitor data channel
3. show_monitor_chart() - Create residual convergence chart
4. get_current_monitors() - Get latest values (Cd, Cl, residuals)

Other live tools:
- pause_simulation() / resume_simulation() - Control simulation
- update_monitor_chart() - Refresh chart with new data
- get_live_status() - Check connection and current timestep
"""
        
        base_mcp["tools"] = tools
        return base_mcp


def main():
    parser = argparse.ArgumentParser(description='CFD Analysis Chat')
    parser.add_argument('data_file', nargs='?', default=None, help='Data file to load (.vtm, .vtu, etc.)')
    parser.add_argument('--live', action='store_true', help='Enable Catalyst Live connection')
    parser.add_argument('--host', default='localhost', help='Catalyst host (with --live)')
    parser.add_argument('--port', type=int, default=22222, help='Catalyst port (with --live)')
    args = parser.parse_args()
    
    # Default to test.vtm if no file specified and not live-only mode
    data_file = args.data_file
    if data_file is None and not args.live:
        # Look for test.vtm in same directory as script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_file = os.path.join(script_dir, 'test.vtm')
        if os.path.exists(default_file):
            data_file = default_file
    
    # Load static data if available
    if data_file and os.path.exists(data_file):
        reader = simple.OpenDataFile(data_file)
        simple.UpdatePipeline()
        simple.Show()
        simple.ResetCamera()
        print(f"Loaded: {data_file}")
    elif data_file:
        print(f"Warning: File not found: {data_file}")
    
    # Create Lite app
    app = Lite()
    app.state.trame__title = "CFD Analysis Assistant"
    app.state.chart_drawer_open = False
    app.state.chart_gallery = []
    
    # Live state (only used if --live)
    app.state.live_enabled = args.live
    app.state.live_connected = False
    app.state.live_host = args.host
    app.state.live_port = args.port
    
    # For Catalyst Live: we need to process network events
    if args.live:
        from paraview import servermanager
        pm = servermanager.vtkProcessModule.GetProcessModule()
        nam = pm.GetNetworkAccessManager()
        
        # Track sources for debugging
        last_source_count = [0]
        
        # Use trame's timer to periodically process ParaView network events
        def process_pv_events():
            try:
                nam.ProcessEvents(1)  # 1ms timeout, non-blocking
                
                # Debug: check for new sources
                sources = simple.GetSources()
                if len(sources) != last_source_count[0]:
                    print(f"[Live] Sources changed: {list(sources.keys())}")
                    last_source_count[0] = len(sources)
            except Exception as e:
                pass  # Ignore errors during event processing
        
        import asyncio
        async def live_event_loop():
            while True:
                process_pv_events()
                await asyncio.sleep(0.1)  # Every 100ms
        
        @app.server.controller.add("on_server_ready")
        def start_live_loop(**kwargs):
            asyncio.create_task(live_event_loop())
            print("Catalyst Live event processing started")
    
    # Setup LLM
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
        print(f"MCP registered (Live enabled: {args.host}:{args.port})")
    else:
        print("MCP registered")
    
    # Helper functions for UI
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
        print(f"[DEBUG] toggle_live_connection called, current state: {app.state.live_connected}")
        if app.state.live_connected:
            chat_mcp.disconnect_live()
            app.state.live_connected = False
            print("[DEBUG] Disconnected")
        else:
            print(f"[DEBUG] Calling connect_live({args.host}, {args.port})...")
            result = chat_mcp.connect_live()
            print(f"[DEBUG] connect_live result: {result}")
            app.state.live_connected = result.get("status") == "connected"
            print(f"[DEBUG] live_connected now: {app.state.live_connected}")
    
    # Build UI
    with app.ui:
        # Chart gallery drawer
        with v3.VNavigationDrawer(
            v_model=("chart_drawer_open", False),
            location="right",
            width=350,
            temporary=True,
        ):
            with v3.VCard(flat=True, classes="fill-height d-flex flex-column"):
                with v3.VCardTitle(classes="d-flex justify-space-between align-center flex-shrink-0"):
                    html.Span("Charts ({{ chart_gallery.length }})")
                    with html.Div():
                        v3.VBtn(icon="mdi-refresh", click=refresh_charts, variant="text", size="small")
                        v3.VBtn(icon="mdi-delete-sweep", click=clear_all_charts, variant="text", size="small",
                                v_if="chart_gallery.length > 0")
                
                with v3.VCardText(classes="pa-2 flex-grow-1", style="overflow-y: auto; max-height: calc(100vh - 80px);"):
                    with html.Div(v_if="chart_gallery.length === 0"):
                        html.P("No charts yet.", classes="text-grey text-body-2")
                    
                    with v3.VExpansionPanels(multiple=True, variant="accordion"):
                        with v3.VExpansionPanel(v_for="(chart, i) in chart_gallery", key="i"):
                            with v3.VExpansionPanelTitle(classes="text-caption py-1"):
                                html.Span("{{ chart.title }}", classes="flex-grow-1")
                                v3.VBtn(icon="mdi-close", click=(delete_chart, "[i]"), variant="text",
                                        size="x-small", color="error", click_stop=True)
                            with v3.VExpansionPanelText(classes="pa-1"):
                                v3.VImg(src=("chart.image",), aspect_ratio="16/9")
        
        # Top toolbar buttons
        with html.Div(style="position: fixed; top: 70px; right: 20px; z-index: 1000; display: flex; gap: 8px;"):
            # Live connection button (only shown if --live)
            with html.Div(v_if="live_enabled"):
                v3.VBtn(
                    icon=("live_connected ? 'mdi-broadcast' : 'mdi-broadcast-off'",),
                    click=toggle_live_connection,
                    color=("live_connected ? 'success' : 'grey'",),
                    variant="elevated",
                    title=("live_connected ? 'Connected to ' + live_host + ':' + live_port : 'Click to connect'",),
                )
            
            # Chart button
            v3.VBtn(
                icon="mdi-chart-line",
                click=toggle_chart_drawer,
                color="primary",
                variant="elevated",
            )
        
        # Chat widget
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
    
    # Print startup info
    print("\nStarting CFD Analysis Assistant...")
    print("  - Pipeline browser: click branch icon or press 'p'")
    print("  - Chart gallery: click chart icon (top-right)")
    if args.live:
        print(f"  - Live connection: click broadcast icon ({args.host}:{args.port})")
    print("  - Chat: click chat icon (bottom-right)")
    
    if args.live:
        print("\nLive workflow:")
        print("  1. Start your simulation with Catalyst")
        print("  2. Click broadcast icon (or ask: 'connect to the simulation')")
        print("  3. Ask: 'extract monitors' to get residual data")
        print("  4. Ask: 'show monitor chart' to visualize convergence")
    
    app.start(open_browser=True)


if __name__ == "__main__":
    main()
