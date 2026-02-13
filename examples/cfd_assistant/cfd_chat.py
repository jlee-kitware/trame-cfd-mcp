#!/usr/bin/env python
"""
Interactive CFD Analysis Assistant

A Trame application with chat interface for CFD analysis using
the WorkflowMCP tools (boundary layer analysis, vortex detection, etc.)

Usage:
    pvpython cfd_chat.py [data_file.vtm]

Environment variables (in .env file):
    LLM_PROVIDER=openai
    LLM_MODEL=gpt-4
    OPENAI_API_KEY=your-key
"""
import sys
import os
import asyncio

# Python 3.14+ compatibility: ensure event loop exists
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# Add paths
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

# Prevent ParaView from creating GUI windows
os.environ.setdefault("PV_ALLOW_BATCH_INTERACTION", "1")
os.environ.setdefault("DISPLAY", "")

from paraview import simple

# Use offscreen rendering
simple._DisableFirstRenderCameraReset()

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3, paraview, html
from trame.widgets import llm

from trame_llm.core import LLMClient, ProgressType
from trame_cfd_mcp import WorkflowMCP
from trame_llm.paraview import ParaViewMCP


class CFDChatApp:
    def __init__(self, server=None, data_file=None):
        self.server = server or get_server(client_type="vue3")
        self.state = self.server.state
        self.ctrl = self.server.controller
        
        # Initialize state
        self.state.trame__title = "CFD Analysis Assistant"
        self.state.data_file = "No data loaded"
        self.state.data_loaded = False
        
        # Create view for web rendering (not native window)
        self.view = simple.CreateRenderView()
        self.view.ViewSize = [1024, 768]
        self.view.Background = [0.1, 0.1, 0.12]
        self.view.EnableRenderOnInteraction = 0
        self.view.InteractionMode = "3D"
        
        # Load data if provided
        if data_file and os.path.exists(data_file):
            self.reader = simple.OpenDataFile(data_file)
            simple.UpdatePipeline()
            simple.Show(self.reader, self.view)
            simple.ResetCamera(self.view)
            self.state.data_loaded = True
            self.state.data_file = os.path.basename(data_file)
        else:
            self.reader = None
        
        # Setup LLM client with CFD workflows
        self.llm_client = LLMClient(max_iteractions=15)
        
        # Register MCPs
        base_mcp = ParaViewMCP(self)
        workflow_mcp = WorkflowMCP(base_mcp)
        self.llm_client.register_mcp(workflow_mcp)
        
        # Build UI
        self._build_ui()
    
    def update(self):
        """Called by MCP when view needs refresh"""
        self.ctrl.view_update()
    
    def reset_camera(self):
        """Reset camera to fit all visible data"""
        simple.ResetCamera(self.view)
        self.update()
    
    def _build_ui(self):
        with SinglePageLayout(self.server) as layout:
            layout.title.set_text("CFD Analysis Assistant")
            
            with layout.toolbar:
                vuetify3.VSpacer()
                html.Span("{{ data_file }}", classes="text-caption mr-4")
                vuetify3.VIcon(
                    "mdi-check-circle",
                    color="green",
                    v_if="data_loaded",
                )
                vuetify3.VIcon(
                    "mdi-alert-circle", 
                    color="orange",
                    v_else=True,
                )
            
            with layout.content:
                with vuetify3.VContainer(fluid=True, classes="fill-height pa-0"):
                    with vuetify3.VRow(classes="fill-height ma-0"):
                        # ParaView render view (left side)
                        with vuetify3.VCol(cols=8, classes="pa-0"):
                            view_widget = paraview.VtkRemoteView(
                                self.view,
                                interactive_ratio=1,
                                style="height: 100%; width: 100%;",
                            )
                            self.ctrl.view_update = view_widget.update
                            self.ctrl.view_reset_camera = view_widget.reset_camera
                        
                        # Chat panel (right side)
                        with vuetify3.VCol(cols=4, classes="pa-0", style="overflow-y: auto;"):
                            llm.Chat(
                                app_name="cfd_assistant",
                                enabled_message_types=[
                                    ProgressType.REQUEST,
                                    ProgressType.LLM_RESPONSE,
                                    ProgressType.MCP_SELECTION,
                                    ProgressType.MCP,
                                    ProgressType.MCP_ERROR,
                                    ProgressType.ERROR,
                                ],
                                llm_client=self.llm_client,
                                style="height: 100%;",
                            )
    
    def start(self, **kwargs):
        self.server.start(open_browser=True, **kwargs)


def main():
    # Get data file from command line or use default
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        data_file = '/Users/jeff.lee/gitsync/trame-cfd-mcp/examples/cfd_assistant/test.vtm'
    
    print(f"Loading: {data_file}")
    print("Starting server... Open http://localhost:8080")
    
    app = CFDChatApp(data_file=data_file)
    app.start()


if __name__ == "__main__":
    main()
