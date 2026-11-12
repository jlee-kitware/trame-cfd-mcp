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
    - Live chart: click chart icon (top-right)
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
logging.basicConfig(format="%(message)s")
logging.getLogger("trame_llm").setLevel(logging.INFO)

from paraview import simple

import ptc.react as ptc
from ptc.react.apps.lite import Lite
from trame.widgets import html, mui, react

CANVAS, SURFACE, INK, MUTED, LINE = "#F3F5F8", "#FFFFFF", "#172033", "#5A6474", "#DCE1E8"
ACCENT, ACCENT_TINT = "#0A7C8C", "#E3F2F4"
SANS = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
         "&family=IBM+Plex+Sans:wght@400;500;600&display=swap")
THEME = {
    "palette": {"mode": "light", "primary": {"main": ACCENT}, "secondary": {"main": "#6E56CF"},
                "success": {"main": "#1F883D"}, "error": {"main": "#C4314B"}, "warning": {"main": "#B35900"},
                "background": {"default": CANVAS, "paper": SURFACE}, "text": {"primary": INK, "secondary": MUTED},
                "divider": LINE},
    "typography": {"fontFamily": SANS, "fontSize": 13, "button": {"textTransform": "none", "fontWeight": 500}},
    "shape": {"borderRadius": 6},
    "components": {
        "MuiButton": {"defaultProps": {"disableElevation": True}},
        "MuiPaper": {"styleOverrides": {"outlined": {"borderColor": LINE}}},
        "MuiOutlinedInput": {"styleOverrides": {"root": {"backgroundColor": SURFACE},
                                                "notchedOutline": {"borderColor": LINE}}},
        "MuiTooltip": {"defaultProps": {"arrow": True, "enterDelay": 400}},
    },
}
MESSAGE_COLORS = {
    "blue-lighten-3": ACCENT, "blue-lighten-4": ACCENT, "blue-lighten-5": ACCENT,
    "purple-lighten-3": "#6E56CF", "red-lighten-3": "#C4314B", "yellow-lighten-3": "#B35900",
    "green-lighten-3": "#1F883D", "teal-lighten-3": "#0B5C75", "orange-lighten-3": "#B35900",
}
CSS_VARS = {
    "--ptc-toolbar-bg": SURFACE, "--ptc-toolbar-fg": MUTED, "--ptc-line": LINE,
    "--ptc-accent": ACCENT, "--ptc-accent-tint": ACCENT_TINT,
    "--tlc-surface": SURFACE, "--tlc-ink": INK, "--tlc-line": LINE, "--tlc-input-line": LINE,
    "--tlc-accent": ACCENT, "--tlc-accent-tint": ACCENT_TINT, "--tlc-font": SANS,
    "--tlc-font-size": "0.85rem", "--tlc-radius": "8px", "--tlc-title-size": "0.95rem",
    "--tlc-title-weight": "600", "--tlc-shadow": "0 4px 16px rgba(23, 32, 51, 0.12)",
    "--tlc-message-fill": "12%",
    **{f"--tlc-{name}": color for name, color in MESSAGE_COLORS.items()},
}
GLOBAL_STYLES = (
    f"@import url('{FONTS}'); "
    f"body {{ background: {CANVAS}; font-family: {SANS}; }} "
    ":root { " + " ".join(f"{k}: {v};" for k, v in CSS_VARS.items()) + " }"
)

# One layout for the live residual chart, used when it is created and on every
# update, so the figure keeps its size; uirevision keeps zoom and legend state.
LIVE_CHART_LAYOUT = dict(
    title="Residual Convergence",
    xaxis_title="Iteration",
    yaxis_title="Residual",
    yaxis_type="log",
    height=320,
    margin=dict(l=50, r=20, t=40, b=40),
    showlegend=True,
    uirevision="live-residuals",
)

try:
    from trame.widgets import plotly as trame_plotly
    import plotly.graph_objects as go
    import plotly.io as pio

    pio.templates["cfd"] = go.layout.Template(layout=dict(
        font=dict(family=SANS, color=INK, size=12),
        colorway=[ACCENT, "#6E56CF", "#B35900", "#1F883D", "#C4314B", "#0B5C75"],
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        title=dict(font=dict(size=14)),
    ))
    pio.templates.default = "plotly_white+cfd"

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
    
    app = Lite(theme=THEME)
    app.state.ptc_light_theme = True

    rtx_available = all("EnableRenderingwithANARI" in v.ListProperties() for v in app.views)
    app.state.update({
        "rtx_available": rtx_available,
        "rtx_enabled": False,
        "rtx_panel_open": False,
        "rtx_mode": "fast",
        "rtx_ambient": 0.8,
        "rtx_ao_samples": 4,
        "rtx_ao_distance": 0.1,
        "rtx_denoise": True,
        "rtx_still_passes": 16,
        "rtx_ray_depth": 5,
        "rtx_modes": [
            {"value": "fast", "title": "Fast", "tip": "Ambient occlusion, built for interaction"},
            {"value": "interactive", "title": "Lit", "tip": "Direct light with shadows"},
            {"value": "quality", "title": "Quality", "tip": "Path traced: reflections and indirect light"},
        ],
    })
    if rtx_available:
        from paraview.modules.vtkRemotingViews import vtkPVView

        vtkPVView.SetEnableStreaming(True)

    def data_diagonal():
        source = simple.GetActiveSource()
        if source is None:
            return 1.0
        x0, x1, y0, y1, z0, z1 = source.GetDataInformation().GetBounds()
        return max(((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) ** 0.5, 1e-6)

    def composite_volume_visible():
        """VTK's ANARI volume mapper renders composite data blank and crashes on teardown."""
        for view in app.views:
            for rep in view.Representations:
                if (rep.GetProperty("Representation") is not None and rep.Visibility
                        and rep.GetPropertyValue("Representation") == "Volume"):
                    info = rep.Input.GetDataInformation() if hasattr(rep, "Input") and rep.Input else None
                    if info is not None and info.IsCompositeDataSet():
                        return True
        return False

    def apply_rtx(passes=None):
        s = app.state
        if s.rtx_enabled and composite_volume_visible():
            with s:
                s.rtx_enabled = False
                s.rtx_notice = "VisRTX can't volume render multi-block data yet; staying on OpenGL."
            return
        s.rtx_notice = ""
        for view in app.views:
            view.EnableRenderingwithANARI = 1 if s.rtx_enabled else 0
            if not s.rtx_enabled:
                continue
            view.ANARILibrary = "visrtx"
            view.ANARIRenderer = s.rtx_mode
            view.StillRender()
            params = [("ambientRadiance", 2, s.rtx_ambient)]
            if s.rtx_mode in ("fast", "interactive"):
                params += [
                    ("ambientSamples", 1, int(s.rtx_ao_samples)),
                    ("ambientOcclusionDistance", 2, s.rtx_ao_distance * data_diagonal()),
                ]
            if s.rtx_mode == "quality":
                params.append(("maxRayDepth", 1, int(s.rtx_ray_depth)))
            if s.rtx_mode != "default":
                params.append(("denoise", 0, "true" if s.rtx_denoise else "false"))
            for key, kind, value in params:
                view.ANARIRendererParameters = [key, str(kind), str(value)]
            view.ProgressivePasses = passes or int(s.rtx_still_passes)
        app.update()

    app.state.rtx_notice = ""

    @app.server.controller.add("on_representation_change")
    def rtx_guard():
        if rtx_available and app.state.rtx_enabled and composite_volume_visible():
            apply_rtx()

    @app.state.change("rtx_enabled", "rtx_mode", "rtx_ambient", "rtx_ao_samples", "rtx_ao_distance",
                      "rtx_denoise", "rtx_still_passes", "rtx_ray_depth")
    def on_rtx_settings(**_):
        if rtx_available:
            apply_rtx()

    # Any mouse, wheel or key activity renders single VisRTX passes; the view refines
    # to the still pass count once input has been quiet for RTX_IDLE seconds.
    RTX_IDLE = 0.3
    rtx_refine = {"task": None, "interactive": False}

    async def rtx_refine_when_idle():
        await asyncio.sleep(RTX_IDLE)
        rtx_refine["interactive"] = False
        for view in app.views:
            view.ProgressivePasses = int(app.state.rtx_still_passes)
        app.update()

    @app.server.controller.add("on_view_interaction")
    def rtx_interaction(event_type):
        if not (rtx_available and app.state.rtx_enabled):
            return
        if not rtx_refine["interactive"]:
            rtx_refine["interactive"] = True
            for view in app.views:
                view.ProgressivePasses = 1
        if rtx_refine["task"] is not None:
            rtx_refine["task"].cancel()
        rtx_refine["task"] = asyncio.ensure_future(rtx_refine_when_idle())
    ctrl = app.server.controller
    app.state.trame__title = "CFD assistant"
    app.state.chart_drawer_open = False
    app.state.live_enabled = args.live
    app.state.live_connected = False
    app.state.live_host = args.host
    app.state.live_chart_visible = False
    app.state.live_chart_status = "Not connected"
    app.state.live_status_text = ""
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
        elif chart_type == "projected_area_image":
            img_path = data.get("image_path", "")
            try:
                import base64
                from PIL import Image as PILImage
                with open(img_path, "rb") as fh:
                    raw = fh.read()
                b64 = base64.b64encode(raw).decode("utf-8")
                # Get actual image dimensions so Plotly fills the widget correctly
                import io
                pil_img = PILImage.open(io.BytesIO(raw))
                iw, ih = pil_img.size
                fig.add_layout_image(dict(
                    source=f"data:image/png;base64,{b64}",
                    xref="x", yref="y",
                    x=0, y=ih, sizex=iw, sizey=ih,
                    xanchor="left", yanchor="top",
                    layer="below",
                    sizing="stretch",
                ))
                fig.update_xaxes(visible=False, range=[0, iw])
                fig.update_yaxes(visible=False, range=[0, ih], scaleanchor="x", scaleratio=1)
                fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
            except Exception as e:
                fig.add_annotation(text=f"Image load failed: {e}", x=0.5, y=0.5,
                                   xref="paper", yref="paper", showarrow=False)
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
        
        live_seen = {"time": None, "auto_monitors": False}

        def update_live_status(paused):
            """Show whether the connected run is going, and start its monitors once they arrive."""
            step, quiet = chat_mcp.live_step()
            channels = chat_mcp.live_channels()
            if not channels:
                text = "Waiting for simulation data"
            else:
                text = f"{'Paused' if paused else 'Running'} at step {step}"
                if not paused and quiet > chat_mcp.LIVE_STALL_SECONDS:
                    text += f", no update for {quiet:.0f} s"
            if app.state.live_status_text != text:
                with app.state:
                    app.state.live_status_text = text
            if not live_seen["auto_monitors"] and "monitors" in channels and not chat_mcp._monitoring_active:
                live_seen["auto_monitors"] = True
                result = chat_mcp.extract_monitors("monitors")
                if result.get("status") == "monitoring":
                    with app.state:
                        app.state.monitoring_active = True
                        app.state.chart_drawer_open = True

        def refresh_live_extracts():
            """Re-execute extracted channels and re-render when the simulation sends a new step.

            Live marks extracts modified on each new timestep, but nothing updates them,
            so displays would keep showing the first payload.
            """
            if not (app.state.live_connected and chat_mcp._extracted_sources and chat_mcp._live_link):
                return
            if chat_mcp.forget_deleted_extracts():
                live_seen["auto_monitors"] = chat_mcp._monitoring_active
            step, _ = chat_mcp.live_step()
            if step == live_seen["time"]:
                return
            live_seen["time"] = step
            for name, source in list(chat_mcp._extracted_sources.items()):
                try:
                    source.UpdatePipeline()
                except Exception:
                    logging.debug("[Live] refreshing %s failed", name, exc_info=True)
            for view in app.views:
                view.StillRender()
            if app.state.ptc_drawer_pipeline:
                app.ctrl.ptc_info_update()

        def update_live_charts():
            """Update Plotly chart if monitoring is active."""
            try:
                # The steering proxy shows up with the simulation's first Live update.
                if app.state.live_connected and not app.state.steer_available:
                    refresh_steering()
                # The chat can pause or resume too; keep the header button in step with the link.
                if app.state.live_connected and chat_mcp._live_link:
                    try:
                        paused = chat_mcp._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
                        if app.state.simulation_paused != paused:
                            with app.state:
                                app.state.simulation_paused = paused
                        update_live_status(paused)
                    except Exception:
                        logging.debug("[Live] status update failed", exc_info=True)
                elif not app.state.live_connected:
                    live_seen["auto_monitors"] = False
                    if app.state.live_status_text:
                        with app.state:
                            app.state.live_status_text = ""
                refresh_live_extracts()
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
                            config = getattr(chat_mcp, "_chart_config", None) or {}
                            names = config.get("y_fields") or chat_mcp.default_chart_fields(list(residuals))
                            log = config.get("log_scale")
                            if log is None:
                                log = bool(names) and all(chat_mcp.is_residual(n) for n in names)
                            fig = go.Figure()
                            for name in names:
                                values = residuals.get(name, [])
                                fig.add_trace(go.Scatter(
                                    x=iterations[-len(values):] if values else [],
                                    y=values,
                                    mode='lines',
                                    name=name,
                                ))
                            fig.update_layout(**{
                                **LIVE_CHART_LAYOUT,
                                "title": "Residual Convergence" if log else "Monitors",
                                "yaxis_title": "Residual" if log else ", ".join(names),
                                "yaxis_type": "log" if log else "linear",
                                "uirevision": f"live-{log}-{'-'.join(names)}",
                            })
                            
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
    llm_client = LLMClient(
        max_iteractions=15,
        system_prompt=(
            "You are a CFD visualization assistant. "
            "When the user asks you to do something, call the appropriate tool directly. "
            "Do not explain what you are about to do; just call the tool. "
            "After receiving tool results, provide a concise interpretation. "
            "Do not suggest further tool calls in your text responses."
        ),
    )
    
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
    
    app.state.update({"steer_available": False, "steer_reynolds": 0, "steer_collision": -1,
                      "steer_collisions": [], "steer_has_power": False, "steer_power": 0})

    def refresh_steering():
        result = chat_mcp.get_simulation_parameters() if app.state.live_connected else {}
        params = {p["name"]: p for p in result.get("parameters", [])}
        with app.state:
            app.state.steer_available = "Reynolds" in params
            if "Reynolds" in params:
                app.state.steer_reynolds = round(params["Reynolds"]["value"])
            app.state.steer_has_power = "Power" in params
            if "Power" in params:
                app.state.steer_power = round(params["Power"]["value"], 1)
            if "Collision" in params:
                app.state.steer_collision = int(params["Collision"]["value"])
                app.state.steer_collisions = [{"text": k, "value": v}
                                              for k, v in params["Collision"]["choices"].items()]

    def apply_reynolds():
        chat_mcp.set_simulation_parameter("Reynolds", str(app.state.steer_reynolds))

    def on_reynolds_key(key):
        if key == "Enter":
            apply_reynolds()

    def apply_power():
        chat_mcp.set_simulation_parameter("Power", str(app.state.steer_power))

    def on_power_key(key):
        if key == "Enter":
            apply_power()

    def apply_collision(value):
        chat_mcp.set_simulation_parameter("Collision", str(value))

    def on_steer(name, value):
        key = {"Reynolds": "steer_reynolds", "Collision": "steer_collision", "Power": "steer_power"}.get(name)
        if key:
            with app.state:
                app.state[key] = {"steer_reynolds": round(value), "steer_collision": int(value),
                                  "steer_power": round(value, 1)}[key]

    chat_mcp.on_steer = on_steer

    def toggle_live_connection():
        if app.state.live_connected:
            chat_mcp.disconnect_live()
            with app.state:
                app.state.live_connected = False
                app.state.simulation_paused = False
                app.state.steer_available = False
        else:
            # CFD_CONNECT_PAUSED=1 holds the run at its first update until the user resumes it.
            paused = os.environ.get("CFD_CONNECT_PAUSED") == "1"
            result = chat_mcp.connect_live(pause=True if paused else None)
            with app.state:
                app.state.live_connected = result.get("status") == "connected"
                app.state.simulation_paused = result.get("paused", False)
            refresh_steering()

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
    
    app.state.setdefault("chart_collapsed", False)
    
    with app.ui_header:
        mui.GlobalStyles(styles=GLOBAL_STYLES)
        with html.Header(
            style={
                "position": "relative",
                "background": SURFACE,
                "borderBottom": f"1px solid {LINE}",
            }
        ):
            with html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "height": "52px",
                    "padding": "0 20px",
                    "gap": "16px",
                }
            ):
                with html.Div(style={"display": "flex", "alignItems": "baseline", "gap": "8px"}):
                    html.Span(
                        "CFD assistant",
                        style={
                            "fontWeight": 600,
                            "fontSize": "1.05rem",
                            "color": INK,
                            "letterSpacing": "-0.01em",
                        },
                    )
                    html.Span(
                        "LLM-guided post-processing in ParaView",
                        style={"color": MUTED, "fontSize": "0.8rem"},
                    )
                html.Div(style={"flex": "1"})

                # Live connection and transport controls
                with react.If("live_enabled"):
                    with html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center"}):
                        mui.Button(
                            [react.Bind("live_connected ? 'Connected' : 'Connect'")],
                            size="small",
                            variant=react.Bind("live_connected ? 'contained' : 'outlined'"),
                            color=react.Bind("live_connected ? 'success' : 'primary'"),
                            on_click=react.Callback(toggle_live_connection),
                        )
                        html.Span(
                            [react.Bind("live_status_text")],
                            style={"display": ptc.show_if("live_connected && live_status_text", "inline"),
                                   "color": MUTED, "fontSize": "0.8rem", "whiteSpace": "nowrap"},
                        )
                        with html.Div(
                            style={
                                "display": ptc.show_if("live_connected", "flex"),
                                "gap": "8px",
                                "alignItems": "center",
                            }
                        ):
                            mui.Button(
                                [react.Bind("simulation_paused ? 'Resume' : 'Pause'")],
                                size="small",
                                variant="outlined",
                                color=react.Bind("simulation_paused ? 'success' : 'warning'"),
                                on_click=react.Callback(toggle_pause),
                            )
                            mui.TextField(
                                label="Steps",
                                value=react.Bind("step_count"),
                                on_change=react.Callback("step_count = Number($event.target.value)"),
                                type="number",
                                size="small",
                                style={"width": "90px"},
                            )
                            mui.Button(
                                "Step",
                                size="small",
                                variant="outlined",
                                on_click=react.Callback(step_forward),
                            )
                            with react.If("steer_available"):
                                mui.TextField(
                                    label="Re",
                                    title="Reynolds number; press Enter to send it to the simulation",
                                    value=react.Bind("steer_reynolds"),
                                    on_change=react.Callback("steer_reynolds = Number($event.target.value)"),
                                    on_key_down=react.Callback(on_reynolds_key, args="[$event.key]"),
                                    on_blur=react.Callback(apply_reynolds),
                                    type="number",
                                    size="small",
                                    style={"width": "96px"},
                                )
                                with react.If("steer_has_power"):
                                    mui.TextField(
                                        label="Power",
                                        title="Heater power under the heat sink; press Enter to send it",
                                        value=react.Bind("steer_power"),
                                        on_change=react.Callback("steer_power = Number($event.target.value)"),
                                        on_key_down=react.Callback(on_power_key, args="[$event.key]"),
                                        on_blur=react.Callback(apply_power),
                                        type="number",
                                        size="small",
                                        style={"width": "96px"},
                                    )
                                with mui.ButtonGroup(size="small", title="Collision model (each is its own JIT-compiled kernel)"):
                                    for text, value in (("BGK", 0), ("TRT", 1), ("LES", 2)):
                                        mui.Button(
                                            text,
                                            variant=react.Bind(f"steer_collision === {value} ? 'contained' : 'outlined'"),
                                            on_click=react.Callback(apply_collision, args=f"[{value}]"),
                                            style={"textTransform": "none"},
                                        )

                with react.If("rtx_available"):
                    with mui.ButtonGroup(size="small"):
                        mui.Button(
                            "RTX",
                            title="Ray trace the view with NVIDIA VisRTX through ANARI",
                            variant=react.Bind("rtx_enabled ? 'contained' : 'outlined'"),
                            on_click=react.Callback("rtx_enabled = !rtx_enabled"),
                        )
                        with mui.Button(
                            title="Ray tracing settings",
                            variant=react.Bind("rtx_panel_open ? 'contained' : 'outlined'"),
                            on_click=react.Callback("rtx_panel_open = !rtx_panel_open"),
                        ):
                            ptc.Icon(icon="mdi-tune-variant", size=16)
                    html.Span(
                        [react.Bind("rtx_notice")],
                        style={"display": ptc.show_if("rtx_notice", "inline"), "color": MUTED,
                               "fontSize": "0.75rem", "maxWidth": "220px"},
                    )
                mui.Button(
                    "Charts",
                    size="small",
                    variant=react.Bind("chart_drawer_open ? 'contained' : 'outlined'"),
                    on_click=react.Callback(toggle_chart_drawer),
                )
            mui.LinearProgress(
                style={
                    "position": "absolute",
                    "left": 0,
                    "right": 0,
                    "bottom": "-1px",
                    "height": "2px",
                    "visibility": react.Bind("trame__busy ? 'visible' : 'hidden'"),
                }
            )

    label_style = {"fontSize": "0.8rem", "color": MUTED, "marginTop": "10px"}
    with app.ui:
        with ptc.FloatingPanel(
            open=react.Bind("rtx_panel_open"),
            style={"top": "68px", "right": "calc(33vw + 2rem)", "zIndex": 1300, "width": "300px"},
        ):
            with mui.Paper(variant="outlined", style={"borderRadius": "8px",
                                                     "boxShadow": "0 4px 16px rgba(23, 32, 51, 0.12)"}):
                with html.Div(classes="ptc-drag-handle", style={
                    "display": "flex", "alignItems": "center", "justifyContent": "space-between",
                    "padding": "6px 8px 6px 14px", "borderBottom": f"1px solid {LINE}"}):
                    html.Span("Ray tracing", style={"fontWeight": 600})
                    ptc.IconButton("mdi-close", on_click=react.Callback("rtx_panel_open = false"), title="Close")
                with html.Div(style={"padding": "8px 14px 14px"}):
                    with html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between"}):
                        html.Span("VisRTX", style={"fontSize": "0.85rem"})
                        mui.Switch(checked=react.Bind("rtx_enabled"), size="small",
                                   on_change=react.Callback("rtx_enabled = $event.target.checked"))
                    html.Div("Mode", style=label_style)
                    with mui.ButtonGroup(size="small", style={"width": "100%"}):
                        with react.For(items="rtx_modes", name="m"):
                            mui.Button([react.Bind("m.title")], key=react.Bind("m.value"), title=react.Bind("m.tip"),
                                       style={"flex": "1", "textTransform": "none"},
                                       variant=react.Bind("rtx_mode === m.value ? 'contained' : 'outlined'"),
                                       on_click=react.Callback("rtx_mode = m.value"))
                    html.Div([react.Bind("'Ambient light: ' + rtx_ambient")], style=label_style)
                    mui.Slider(value=react.Bind("rtx_ambient"), min=0, max=3, step=0.05, size="small",
                               on_change=react.Callback("rtx_ambient = $event.target.value"))
                    with html.Div(style={"display": ptc.show_if("rtx_mode !== 'quality'")}):
                        html.Div([react.Bind("'Ambient occlusion samples: ' + rtx_ao_samples")], style=label_style)
                        mui.Slider(value=react.Bind("rtx_ao_samples"), min=0, max=16, step=1, size="small",
                                   on_change=react.Callback("rtx_ao_samples = $event.target.value"))
                        html.Div([react.Bind("'Occlusion distance: ' + rtx_ao_distance + ' of the data size'")],
                                 style=label_style)
                        mui.Slider(value=react.Bind("rtx_ao_distance"), min=0.01, max=1, step=0.01, size="small",
                                   on_change=react.Callback("rtx_ao_distance = $event.target.value"))
                    with html.Div(style={"display": ptc.show_if("rtx_mode === 'quality'")}):
                        html.Div([react.Bind("'Ray depth: ' + rtx_ray_depth")], style=label_style)
                        mui.Slider(value=react.Bind("rtx_ray_depth"), min=1, max=10, step=1, size="small",
                                   on_change=react.Callback("rtx_ray_depth = $event.target.value"))
                    html.Div([react.Bind("'Passes when still: ' + rtx_still_passes")], style=label_style)
                    mui.Slider(value=react.Bind("rtx_still_passes"), min=1, max=64, step=1, size="small",
                               on_change=react.Callback("rtx_still_passes = $event.target.value"))
                    with html.Div(style={"display": "flex", "alignItems": "center",
                                         "justifyContent": "space-between", "marginTop": "8px"}):
                        html.Span("OptiX denoiser", style={"fontSize": "0.85rem"})
                        mui.Switch(checked=react.Bind("rtx_denoise"), size="small",
                                   on_change=react.Callback("rtx_denoise = $event.target.checked"))

        # Chart panel - floating card, draggable by its header and collapsible
        with ptc.FloatingPanel(
            open=react.Bind("chart_drawer_open"),
            style={
                "top": "120px",
                "right": "calc(33vw + 2rem)",
                "zIndex": 1200,
                "width": "520px",
            },
        ):
            with mui.Paper(
                variant="outlined",
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "maxHeight": "calc(100vh - 84px)",
                    "borderRadius": "8px",
                    "boxShadow": "0 4px 16px rgba(23, 32, 51, 0.12)",
                },
            ):
                with html.Div(
                    classes="ptc-drag-handle",
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "space-between",
                        "padding": "4px 8px 4px 4px",
                        "borderBottom": f"1px solid {LINE}",
                    },
                ):
                    with html.Div(style={"display": "flex", "alignItems": "center"}):
                        ptc.IconButton(
                            react.Bind("chart_collapsed ? 'mdi-chevron-right' : 'mdi-chevron-down'"),
                            on_click=react.Callback("chart_collapsed = !chart_collapsed"),
                            title="Collapse or expand",
                        )
                        html.Span("Charts", style={"fontWeight": 600, "color": INK})
                    with html.Div(style={"display": "flex"}):
                        ptc.IconButton(
                            "mdi-delete-outline",
                            on_click=react.Callback(clear_analysis_charts),
                            title="Clear charts",
                        )
                        ptc.IconButton(
                            "mdi-close",
                            on_click=react.Callback("chart_drawer_open = false"),
                            title="Close",
                        )

                # Scrollable content with multiple chart slots
                with html.Div(
                    style={
                        "display": ptc.show_if("!chart_collapsed"),
                        "overflowY": "auto",
                        "padding": "8px 12px",
                    }
                ):
                    if PLOTLY_AVAILABLE:
                        # Dedicated live residual chart (shown when monitoring)
                        with html.Div(
                            style={
                                "display": ptc.show_if("monitoring_active"),
                                "width": "100%",
                                "marginBottom": "8px",
                            }
                        ):
                            live_fig = go.Figure()
                            live_fig.update_layout(**LIVE_CHART_LAYOUT)
                            app.live_chart_widget = trame_plotly.Figure(
                                live_fig,
                                style={"width": "100%", "height": "320px"},
                            )

                        # Analysis chart widget slots
                        for i in range(MAX_CHARTS):
                            with html.Div(
                                style={
                                    "display": ptc.show_if(f"chart_visibility[{i}]"),
                                    "width": "100%",
                                    "marginBottom": "8px",
                                }
                            ):
                                initial_fig = go.Figure()
                                initial_fig.update_layout(
                                    title=f"Chart {i + 1}",
                                    height=320,
                                    margin=dict(l=50, r=20, t=70, b=40),
                                )
                                widget = trame_plotly.Figure(
                                    initial_fig,
                                    style={"width": "100%", "height": "320px"},
                                )
                                app.chart_widgets.append(widget)
                    else:
                        html.P("Install trame-plotly for charts", style={"color": MUTED})

                    html.Div(
                        [react.Bind("live_chart_status")],
                        style={"fontSize": "0.78rem", "color": MUTED, "marginTop": "4px"},
                    )

    with app.ui_main:
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
