#!/usr/bin/env python
"""CFD Chat app based on ptc.Lite with pipeline browser and chart gallery"""
import sys
import os
import asyncio

# Reduce OpenGL texture usage to avoid macOS driver limits
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
    """MCP wrapper that adds cost tracking tool to WorkflowMCP."""
    
    def __init__(self, workflow_mcp, llm_client):
        self._workflow_mcp = workflow_mcp
        self._llm_client = llm_client
    
    def get_session_cost(self) -> dict:
        """Get current chat session cost and usage statistics."""
        return self._llm_client.get_cost()
    
    def reset_session_cost(self) -> dict:
        """Reset the cost tracking counters to zero."""
        self._llm_client.reset_cost()
        return {"status": "reset", "message": "Cost counters reset to zero"}
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration with cost tools added."""
        base_mcp = self._workflow_mcp.mcp
        base_mcp["tools"] = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        return base_mcp


def main():
    # Load data first
    data_file = sys.argv[1] if len(sys.argv) > 1 else '/Users/jeff.lee/gitsync/trame-cfd-mcp/examples/cfd_assistant/test.vtm'
    
    if os.path.exists(data_file):
        reader = simple.OpenDataFile(data_file)
        simple.UpdatePipeline()
        simple.Show()
        simple.ResetCamera()
        print(f"Loaded: {data_file}")
    
    # Create Lite app
    app = Lite()
    app.state.trame__title = "CFD Analysis Assistant"
    app.state.chart_drawer_open = False
    app.state.chart_gallery = []
    
    # Setup LLM
    print("Setting up LLM client...")
    llm_client = LLMClient(max_iteractions=15)
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    chat_mcp = CFDChatMCP(workflow_mcp, llm_client)
    llm_client.register_mcp(chat_mcp)
    print("MCP registered")
    
    # Function to refresh charts
    def refresh_charts():
        gallery = workflow_mcp.get_chart_gallery()
        app.state.chart_gallery = gallery.get("charts", [])
    
    def toggle_chart_drawer():
        refresh_charts()
        app.state.chart_drawer_open = not app.state.chart_drawer_open
    
    def delete_chart(index):
        """Delete a chart by index."""
        workflow_mcp._analysis._chart_gallery.pop(index)
        refresh_charts()
    
    def clear_all_charts():
        """Clear all charts."""
        workflow_mcp.clear_charts()
        refresh_charts()
    
    # Add UI components
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
                        v3.VBtn(
                            icon="mdi-refresh",
                            click=refresh_charts,
                            variant="text",
                            size="small",
                            title="Refresh",
                        )
                        v3.VBtn(
                            icon="mdi-delete-sweep",
                            click=clear_all_charts,
                            variant="text",
                            size="small",
                            title="Clear all",
                            v_if="chart_gallery.length > 0",
                        )
                
                # Scrollable chart list
                with v3.VCardText(
                    classes="pa-2 flex-grow-1", 
                    style="overflow-y: auto; max-height: calc(100vh - 80px);"
                ):
                    with html.Div(v_if="chart_gallery.length === 0"):
                        html.P("No charts yet. Ask to show histogram, force distribution, or boundary layer profiles.", 
                               classes="text-grey text-body-2")
                    
                    # Expansion panels for collapsible charts
                    with v3.VExpansionPanels(multiple=True, variant="accordion"):
                        with v3.VExpansionPanel(v_for="(chart, i) in chart_gallery", key="i"):
                            with v3.VExpansionPanelTitle(classes="text-caption py-1"):
                                html.Span("{{ chart.title }}", classes="flex-grow-1")
                                v3.VBtn(
                                    icon="mdi-close",
                                    click=(delete_chart, "[i]"),
                                    variant="text",
                                    size="x-small",
                                    color="error",
                                    title="Delete chart",
                                    click_stop=True,  # Prevent expansion toggle
                                )
                            with v3.VExpansionPanelText(classes="pa-1"):
                                v3.VImg(src=("chart.image",), aspect_ratio="16/9")
        
        # Chart button - fixed position in top right
        with html.Div(style="position: fixed; top: 70px; right: 20px; z-index: 1000;"):
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
    
    print("Starting CFD Chat...")
    print("  - Pipeline browser: click branch icon in left toolbar (or press 'p')")
    print("  - Chart gallery: click chart icon in top-right")
    print("  - Chat: click chat icon in bottom-right")
    
    app.start(open_browser=True)


if __name__ == "__main__":
    main()
