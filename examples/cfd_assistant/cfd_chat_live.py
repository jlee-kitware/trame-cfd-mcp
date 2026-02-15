#!/usr/bin/env python
"""
CFD Chat with Catalyst Live support.

Connects to a running simulation via Catalyst Live for real-time monitoring.

Usage:
    # Start your simulation with Catalyst (must enable Live connection)
    # Then run this:
    pvpython cfd_chat_live.py [--host localhost] [--port 22222]

Example conversation:
    You: Connect to the simulation
    Assistant: [calls connect_live] Connected to localhost:22222...

    You: What's the current timestep?
    Assistant: [calls get_live_status] Timestep 150, time=0.0015s...

    You: Show vortices
    Assistant: [calls show_vortices] Created vortex visualization...

    You: Pause the simulation so I can analyze this
    Assistant: [calls pause_simulation] Simulation paused...
"""
import sys
import os
import asyncio
import argparse

os.environ.setdefault("VTK_MAX_TEXTURE_SIZE", "2048")

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
from trame_cfd_mcp.catalyst_live import CatalystLiveMCP
from trame_llm.paraview import ParaViewMCP


def main():
    parser = argparse.ArgumentParser(description='CFD Chat with Catalyst Live')
    parser.add_argument('--host', default='localhost', help='Catalyst host')
    parser.add_argument('--port', type=int, default=22222, help='Catalyst port')
    parser.add_argument('--auto-connect', action='store_true', help='Connect immediately')
    args = parser.parse_args()
    
    # Create Lite app
    app = Lite()
    app.state.trame__title = "CFD Live Monitor"
    app.state.chart_drawer_open = False
    app.state.chart_gallery = []
    app.state.live_connected = False
    app.state.live_host = args.host
    app.state.live_port = args.port
    
    # Setup LLM with Catalyst Live support
    print("Setting up LLM client with Catalyst Live...")
    llm_client = LLMClient(max_iteractions=15)
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    live_mcp = CatalystLiveMCP(workflow_mcp, host=args.host, port=args.port)
    
    llm_client.register_mcp(live_mcp)
    print(f"MCP registered (Catalyst Live: {args.host}:{args.port})")
    
    # Auto-connect if requested
    if args.auto_connect:
        result = live_mcp.connect_live()
        print(f"Auto-connect: {result}")
        app.state.live_connected = result.get("status") == "connected"
    
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
            result = live_mcp.disconnect_live()
            app.state.live_connected = False
        else:
            result = live_mcp.connect_live(app.state.live_host, app.state.live_port)
            app.state.live_connected = result.get("status") == "connected"
    
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
        
        # Top toolbar with live status and chart button
        with html.Div(style="position: fixed; top: 70px; right: 20px; z-index: 1000; display: flex; gap: 8px;"):
            # Live connection indicator/button
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
            app_name="cfd_live",
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
    
    print("Starting CFD Live Monitor...")
    print(f"  - Catalyst Live: {args.host}:{args.port}")
    print("  - Click broadcast icon to connect/disconnect")
    print("  - Pipeline browser: press 'p'")
    print("  - Chart gallery: click chart icon")
    print("  - Chat: click chat icon (bottom-right)")
    
    app.start(open_browser=True)


if __name__ == "__main__":
    main()
