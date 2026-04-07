import logging
#!/usr/bin/env python
"""
CFD Analysis Chat - Interactive visualization with optional Catalyst Live.

Usage:
    # Load static data file (in-process)
    pvpython cfd_chat.py data.vtm
    
    # Connect to pvserver (client-server, local or remote)
    # Start pvserver first: pvserver (default port 11111)
    # Or with custom port: pvserver --server-port=22222
    pvpython cfd_chat.py --pvserver=localhost:11111 data.vtm
    
    # Connect to live simulation
    pvpython cfd_chat.py --live --host localhost --port 22222
    
    # pvserver + live simulation
    pvpython cfd_chat.py --pvserver=localhost:11111 --live
    
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

# Add src to path if running from examples directory (development mode)
import pathlib
_repo_src = pathlib.Path(__file__).parent.parent.parent / 'src'
if _repo_src.exists():
    sys.path.insert(0, str(_repo_src))
# trame-llm: install via pip or set TRAME_LLM_SRC env var
_trame_llm = os.environ.get('TRAME_LLM_SRC')
if _trame_llm:
    sys.path.insert(0, _trame_llm)

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
    parser.add_argument('--pvserver', default=None, help='pvserver host:port (e.g. localhost:11111)')
    args, remaining = parser.parse_known_args()
    
    # Strip our args from sys.argv so trame's parser only sees its own args
    sys.argv = [sys.argv[0]] + remaining
    
    # Connect to pvserver if specified (must happen before any pipeline operations)
    remote = False
    if args.pvserver:
        sv_host, sv_port = args.pvserver.split(":")
        simple.Connect(sv_host, int(sv_port))
        remote = True
        print(f"Connected to pvserver at {args.pvserver}")
    
    data_file = args.data_file
    if data_file is None and not args.live:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_file = os.path.join(script_dir, 'test.vtm')
        if os.path.exists(default_file):
            data_file = default_file
    
    if data_file:
        # Resolve to absolute path — pvserver needs a path valid on its filesystem.
        # For co-located pvserver (same machine), this just works.
        # For remote pvserver, the user must provide a server-accessible path.
        data_file = os.path.abspath(data_file)
        
        if not remote and not os.path.exists(data_file):
            print(f"Warning: File not found: {data_file}")
        else:
            try:
                reader = simple.OpenDataFile(data_file)
                simple.UpdatePipeline()
                simple.Show()
                simple.ResetCamera()
                print(f"Loaded: {data_file}")
            except Exception as e:
                print(f"Error loading {data_file}: {e}")
                if remote:
                    print("  (path must be accessible from the pvserver filesystem)")
    
    app = Lite()
    ctrl = app.server.controller
    app.state.trame__title = "CFD Analysis Assistant"
    app.state.chart_drawer_open = False
    app.state.live_enabled = args.live
    app.state.live_connected = False
    app.state.live_host = args.host
    app.state.live_chart_visible = False
    app.state.live_chart_status = "Not connected"
    app.state.live_port = args.port
    app.state.monitoring_active = False
    app.state.analysis_chart_active = False  # True when showing analysis chart (not live)
    app.state.simulation_paused = False
    app.state.step_count = 5  # Default step count
    
    # Store chart figures directly - we'll create multiple widget slots
    app.chart_figures = []  # List of Plotly figure objects for analysis charts
    app.chart_widgets = []  # Will be populated with analysis chart widget references
    app.live_chart_widget = None  # Dedicated widget for live residual chart
    MAX_CHARTS = 10
    
    def build_chart_figure(chart_data: dict):
        """Build a Plotly figure from chart data."""
        chart_type = chart_data.get("chart_type")
        title = chart_data.get("title", "Chart")
        x_label = chart_data.get("x_label", "")
        y_label = chart_data.get("y_label", "")
        data = chart_data.get("data", {})
        
        fig = go.Figure()
        
        if chart_type == "histogram":
            fig.add_trace(go.Bar(
                x=data.get("x", []),
                y=data.get("y", []),
                name=chart_data.get("field", "Value"),
            ))
        elif chart_type == "force_distribution":
            x = data.get("x", [])
            series = data.get("series", {})
            for name, values in series.items():
                fig.add_trace(go.Scatter(x=x, y=values, mode='lines', name=name))
        elif chart_type == "boundary_layer":
            fig.add_trace(go.Scatter(
                x=data.get("x", []),
                y=data.get("y", []),
                mode='lines',
                name='BL Profile',
                line=dict(color='blue', width=2),
            ))
        elif chart_type == "section_debug":
            section = data.get("section", {})
            probes = data.get("probes", [])
            markers = data.get("markers", {})
            fig.add_trace(go.Scatter(
                x=section.get("x", []), y=section.get("y", []),
                mode='lines', name='Section', line=dict(color='black', width=2),
            ))
            colors = ['red', 'green', 'blue', 'orange', 'purple', 'cyan']
            for j, probe in enumerate(probes):
                fig.add_trace(go.Scatter(
                    x=probe.get("x", []), y=probe.get("y", []),
                    mode='lines', line=dict(color=colors[j % len(colors)], width=2),
                    showlegend=False,
                ))
            fig.add_trace(go.Scatter(
                x=markers.get("x", []), y=markers.get("y", []),
                mode='markers', name='Probe Points', marker=dict(color='red', size=8),
            ))
            fig.update_yaxes(scaleanchor="x", scaleratio=1)
        else:
            # Generic
            x = data.get("x", [])
            series = data.get("series", data.get("y", {}))
            if isinstance(series, dict):
                for name, values in series.items():
                    fig.add_trace(go.Scatter(x=x, y=values, mode='lines', name=name))
            else:
                fig.add_trace(go.Scatter(x=x, y=series, mode='lines'))
        
        fig.update_layout(
            title=dict(text=title, y=0.92, x=0.5, xanchor='center', yanchor='top', font=dict(size=14)),
            xaxis_title=x_label,
            yaxis_title=y_label,
            margin=dict(l=50, r=20, t=70, b=40),
            height=320,
            showlegend=True,
        )
        
        return fig
    
    def update_all_chart_widgets():
        """Update all chart widgets with current figures."""
        for i in range(MAX_CHARTS):
            if i < len(app.chart_figures) and i < len(app.chart_widgets):
                app.chart_widgets[i].update(app.chart_figures[i])
        
        # Update visibility state
        with app.state:
            app.state.chart_visibility = [i < len(app.chart_figures) for i in range(MAX_CHARTS)]
    
    # Initialize visibility state
    app.state.chart_visibility = [False] * MAX_CHARTS
    
    # Function to render chart from ParaView proxy (vtkTable)
    def render_chart_from_proxy(proxy_name: str):
        """Render a chart by reading data from a ParaView table proxy."""
        from paraview import servermanager
        from vtk.util.numpy_support import vtk_to_numpy
        
        logging.debug(f"[render_chart_from_proxy] Fetching proxy_name={proxy_name}")
        if not PLOTLY_AVAILABLE:
            logging.debug("[render_chart_from_proxy] Plotly not available")
            return
        
        # Get the proxy
        proxy = simple.FindSource(proxy_name)
        if proxy is None:
            logging.debug(f"[render_chart_from_proxy] Proxy {proxy_name} not found")
            return
        
        # Fetch the data
        data = servermanager.Fetch(proxy)
        if data is None:
            logging.debug(f"[render_chart_from_proxy] Failed to fetch data from {proxy_name}")
            return
        
        # Get chart metadata from field data
        field_data = data.GetFieldData()
        
        def get_string_field(name):
            arr = field_data.GetAbstractArray(name)
            if arr and arr.GetNumberOfTuples() > 0:
                return arr.GetValue(0)
            return ""
        
        chart_type = get_string_field("chart_type")
        title = get_string_field("chart_title")
        x_label = get_string_field("x_label")
        y_label = get_string_field("y_label")

        # Check workflow metadata dict (primary source, works in pvserver mode)
        if hasattr(app, '_workflow_mcp') and app._workflow_mcp:
            meta = app._workflow_mcp._workflows.get_chart_metadata(proxy_name)
            if meta:
                chart_type = meta.get("chart_type", chart_type) or chart_type
                title = meta.get("chart_title", title) or title
                x_label = meta.get("x_label", x_label) or x_label
                y_label = meta.get("y_label", y_label) or y_label

        # Fall back to parsing chart_type from proxy name (Chart_N_type)
        if not chart_type and "_" in proxy_name:
            parts = proxy_name.split("_", 2)
            if len(parts) >= 3:
                chart_type = parts[2]
        
        logging.debug(f"[render_chart_from_proxy] chart_type={chart_type}, title={title}")
        
        # Build chart data from table columns
        chart_data = {
            "chart_type": chart_type,
            "title": title,
            "x_label": x_label,
            "y_label": y_label,
            "data": {},
        }
        
        if chart_type == "boundary_layer":
            x_arr = data.GetColumnByName("u_Ue")
            y_arr = data.GetColumnByName("y_wall")
            if x_arr and y_arr:
                chart_data["data"]["x"] = vtk_to_numpy(x_arr).tolist()
                chart_data["data"]["y"] = vtk_to_numpy(y_arr).tolist()
        elif chart_type == "histogram":
            x_arr = data.GetColumnByName("bin_center")
            y_arr = data.GetColumnByName("count")
            if x_arr and y_arr:
                chart_data["data"]["x"] = vtk_to_numpy(x_arr).tolist()
                chart_data["data"]["y"] = vtk_to_numpy(y_arr).tolist()
        elif chart_type == "force_distribution":
            x_arr = data.GetColumnByName("section")
            if x_arr:
                chart_data["data"]["x"] = vtk_to_numpy(x_arr).tolist()
            chart_data["data"]["series"] = {}
            for i in range(data.GetNumberOfColumns()):
                col_name = data.GetColumnName(i)
                if col_name not in ["section", "x"]:
                    arr = data.GetColumn(i)
                    chart_data["data"]["series"][col_name] = vtk_to_numpy(arr).tolist()
        else:
            # Generic x/y
            x_arr = data.GetColumnByName("x")
            y_arr = data.GetColumnByName("y")
            if x_arr and y_arr:
                chart_data["data"]["x"] = vtk_to_numpy(x_arr).tolist()
                chart_data["data"]["y"] = vtk_to_numpy(y_arr).tolist()
        
        # Build figure and add to list
        fig = build_chart_figure(chart_data)
        
        if len(app.chart_figures) < MAX_CHARTS:
            app.chart_figures.append(fig)
        else:
            app.chart_figures.pop(0)
            app.chart_figures.append(fig)
        
        with app.state:
            app.state.chart_drawer_open = True
            app.state.analysis_chart_active = True
            app.state.live_chart_status = f"Showing {len(app.chart_figures)} chart(s)"
        
        update_all_chart_widgets()
        logging.debug(f"[render_chart_from_proxy] Added chart from {proxy_name}, total: {len(app.chart_figures)}")
    
    # Legacy function for direct chart data (still useful for some cases)
    def render_analysis_chart(chart_data: dict):
        """Add a chart to the analysis charts."""
        print(f"[render_analysis_chart] Called with chart_type={chart_data.get('chart_type')}")
        if not PLOTLY_AVAILABLE:
            print("[render_analysis_chart] Plotly not available")
            return
        
        # Build figure and add to list
        fig = build_chart_figure(chart_data)
        
        if len(app.chart_figures) < MAX_CHARTS:
            app.chart_figures.append(fig)
        else:
            # Remove oldest, add new
            app.chart_figures.pop(0)
            app.chart_figures.append(fig)
        
        with app.state:
            app.state.chart_drawer_open = True
            app.state.analysis_chart_active = True
            app.state.live_chart_status = f"Showing {len(app.chart_figures)} chart(s)"
        
        update_all_chart_widgets()
        print(f"[render_analysis_chart] Added chart, total: {len(app.chart_figures)}")
    
    def clear_analysis_charts():
        """Clear all analysis charts."""
        app.chart_figures = []
        with app.state:
            app.state.chart_visibility = [False] * MAX_CHARTS
            app.state.analysis_chart_active = False
            app.state.live_chart_status = "Charts cleared"
        # Clear all widgets
        empty_fig = go.Figure()
        empty_fig.update_layout(height=100)
        for w in app.chart_widgets:
            w.update(empty_fig)
    
    app.render_chart_from_proxy = render_chart_from_proxy
    app.render_analysis_chart = render_analysis_chart
    app.clear_analysis_charts = clear_analysis_charts

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
                    logging.debug("[Live] Connection to simulation dropped")
                    return
                
                # Sync monitoring_active state with chat_mcp
                if app.state.monitoring_active != chat_mcp._monitoring_active:
                    app.state.monitoring_active = chat_mcp._monitoring_active
                
                # Sync live_connected state (LLM may connect/disconnect via MCP)
                link_alive = chat_mcp.is_connection_alive()
                if app.state.live_connected != link_alive:
                    app.state.live_connected = link_alive
                
                # Skip live chart updates if showing an analysis chart
                if app.state.analysis_chart_active:
                    # Debug: only print occasionally to avoid spam
                    return
                
                if chat_mcp._monitoring_active:
                    # Check if simulation is running (not paused)
                    paused = False
                    if chat_mcp._live_link:
                        try:
                            paused = chat_mcp._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
                        except:
                            pass
                    
                    # Sync pause state to UI (picks up breakpoint-triggered pauses)
                    if app.state.simulation_paused != paused:
                        app.state.simulation_paused = paused
                    
                    # Always update chart - whether paused or running
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
                            
                            # Update dedicated live chart widget
                            if app.live_chart_widget:
                                app.live_chart_widget.update(fig)
                            
                            status = f"Monitoring: {len(iterations)} iterations"
                            if paused:
                                status += " (paused)"
                            with app.state:
                                app.state.live_chart_status = status
                                app.state.flush()
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
    workflow_mcp = WorkflowMCP(base_mcp, app=app)
    app._workflow_mcp = workflow_mcp  # expose for render_chart_from_proxy
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
    
    def toggle_chart_drawer():
        app.state.chart_drawer_open = not app.state.chart_drawer_open
    
    def toggle_live_connection():
        if app.state.live_connected:
            chat_mcp.disconnect_live()
            with app.state:
                app.state.live_connected = False
                app.state.simulation_paused = False
        else:
            result = chat_mcp.connect_live()
            with app.state:
                app.state.live_connected = result.get("status") == "connected"
                app.state.simulation_paused = result.get("paused", False)

    def toggle_pause():
        if not app.state.live_connected:
            return
        if app.state.simulation_paused:
            chat_mcp.resume_simulation()
            app.state.simulation_paused = False
        else:
            chat_mcp.pause_simulation()
            chat_mcp.clear_breakpoint()  # Cancel any pending step/breakpoint
            app.state.simulation_paused = True

    def step_forward():
        if not app.state.live_connected:
            return
        count = int(app.state.step_count or 5)
        result = chat_mcp.step_simulation(count)
        if result.get("status") == "error":
            logging.debug(f"[Live] Step failed: {result}")
            return
        app.state.simulation_paused = False
        # Auto-open chart panel so user sees residuals
        if not app.state.chart_drawer_open:
            app.state.chart_drawer_open = True
    
    # State for chart panel position and collapse
    app.state.setdefault("chart_collapsed", False)
    app.state.setdefault("chart_pos_x", None)  # None = use default position
    app.state.setdefault("chart_pos_y", 50)
    
    with app.ui:
        # JavaScript for dragging
        html.Script("""
            window.initDraggable = function(el) {
                if (!el || el._dragInitialized) return;
                el._dragInitialized = true;
                
                const header = el.querySelector('.drag-handle');
                if (!header) return;
                
                let isDragging = false;
                let startX, startY, startLeft, startTop;
                
                header.style.cursor = 'move';
                
                header.addEventListener('mousedown', function(e) {
                    if (e.target.closest('button')) return; // Don't drag when clicking buttons
                    isDragging = true;
                    startX = e.clientX;
                    startY = e.clientY;
                    const rect = el.getBoundingClientRect();
                    startLeft = rect.left;
                    startTop = rect.top;
                    e.preventDefault();
                });
                
                document.addEventListener('mousemove', function(e) {
                    if (!isDragging) return;
                    const dx = e.clientX - startX;
                    const dy = e.clientY - startY;
                    el.style.left = (startLeft + dx) + 'px';
                    el.style.top = (startTop + dy) + 'px';
                    el.style.right = 'auto';
                });
                
                document.addEventListener('mouseup', function() {
                    isDragging = false;
                });
            };
        """)
        
        # Chart panel - floating card, draggable and collapsible
        with v3.VCard(
            v_show="chart_drawer_open",
            style="position: fixed; top: 50px; right: 80px; z-index: 10000; width: 520px; max-height: calc(100vh - 60px);",
            elevation=8,
            ref="chartPanel",
            __events=["mounted"],
            mounted="window.initDraggable($refs.chartPanel.$el)",
        ):
            # Header with drag handle, collapse, and close buttons
            with v3.VCardTitle(
                classes="drag-handle d-flex justify-space-between align-center py-1 flex-shrink-0",
                style="user-select: none;",
            ):
                with html.Div(classes="d-flex align-center"):
                    v3.VBtn(
                        icon=("chart_collapsed ? 'mdi-chevron-right' : 'mdi-chevron-down'",),
                        click="chart_collapsed = !chart_collapsed",
                        variant="text",
                        size="x-small",
                        density="compact",
                        title="Collapse/Expand",
                    )
                    html.Span("Charts", classes="text-subtitle-2 ml-1")
                with html.Div(classes="d-flex"):
                    v3.VBtn(
                        icon="mdi-delete-outline",
                        click=(clear_analysis_charts,),
                        variant="text",
                        size="x-small",
                        density="compact",
                        title="Clear Charts",
                    )
                    v3.VBtn(icon="mdi-close", click="chart_drawer_open = false", variant="text", size="x-small", density="compact")
            
            v3.VDivider()
            
            # Scrollable content with multiple chart slots
            with v3.VExpandTransition():
                with html.Div(v_show="!chart_collapsed"):
                    with v3.VCardText(classes="pa-2", style="overflow-y: auto; max-height: calc(100vh - 120px);"):
                        if PLOTLY_AVAILABLE:
                            # Dedicated live residual chart (shown when monitoring)
                            with html.Div(
                                v_show="monitoring_active",
                                style="width: 100%; margin-bottom: 8px;",
                            ):
                                live_fig = go.Figure()
                                live_fig.update_layout(
                                    title="Residual Convergence",
                                    height=320,
                                    margin=dict(l=50, r=20, t=70, b=40)
                                )
                                app.live_chart_widget = trame_plotly.Figure(
                                    live_fig,
                                    style="width: 100%; height: 320px;"
                                )
                            
                            # Analysis chart widget slots
                            for i in range(MAX_CHARTS):
                                with html.Div(
                                    v_show=f"chart_visibility[{i}]",
                                    style="width: 100%; margin-bottom: 8px;",
                                ):
                                    initial_fig = go.Figure()
                                    initial_fig.update_layout(title=f"Chart {i+1}", height=320, margin=dict(l=50, r=20, t=70, b=40))
                                    widget = trame_plotly.Figure(initial_fig, style="width: 100%; height: 320px;")
                                    app.chart_widgets.append(widget)
                        else:
                            html.P("Install trame-plotly for charts", classes="text-grey")
                        
                        # Status info at bottom
                        html.P("{{ live_chart_status }}", classes="text-caption text-grey mt-1")
        
        # Buttons in top-right corner - z-index 10001 to stay above chat and chart panel
        with html.Div(style="position: fixed; top: 12px; right: 80px; z-index: 10001; display: flex; gap: 8px;"):
            # Chart button
            v3.VBtn(
                icon="mdi-chart-line",
                click=toggle_chart_drawer,
                color=("chart_drawer_open ? 'primary' : ''",),
                variant="elevated",
                size="small",
                title="Live Residual Chart",
            )
            
            # Live connection and transport controls
            with html.Div(v_if="live_enabled", style="display: flex; gap: 4px; align-items: center;"):
                v3.VBtn(
                    icon=("live_connected ? 'mdi-broadcast' : 'mdi-broadcast-off'",),
                    click=toggle_live_connection,
                    color=("live_connected ? 'success' : 'grey'",),
                    variant="elevated",
                    size="small",
                    title=("live_connected ? 'Connected' : 'Click to connect'",),
                )
                # Transport controls - only visible when connected
                with html.Div(v_show="live_connected", style="display: flex; gap: 2px; align-items: center;"):
                    v3.VBtn(
                        icon=("simulation_paused ? 'mdi-play' : 'mdi-pause'",),
                        click=(toggle_pause,),
                        color=("simulation_paused ? 'success' : 'warning'",),
                        variant="elevated",
                        size="small",
                        title=("simulation_paused ? 'Resume' : 'Pause'",),
                    )
                    v3.VTextField(
                        v_model=("step_count",),
                        type="number",
                        density="compact",
                        variant="outlined",
                        hide_details=True,
                        style="width: 60px; max-width: 60px;",
                        bg_color="white",
                    )
                    v3.VBtn(
                        icon="mdi-skip-forward",
                        click=(step_forward,),
                        variant="elevated",
                        size="small",
                        title="Step N iterations",
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
