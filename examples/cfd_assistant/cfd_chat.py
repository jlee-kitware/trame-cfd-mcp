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
from trame_cfd_mcp import WorkflowMCP, CFDChatMCP
from trame_llm.paraview import ParaViewMCP

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
