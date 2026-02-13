#!/usr/bin/env python
"""Test trame + LLM chat widget"""
import sys
import os
import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

os.environ.setdefault("PV_ALLOW_BATCH_INTERACTION", "1")

sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3, paraview
from trame.widgets import llm

from trame_llm.core import LLMClient, ProgressType
from trame_cfd_mcp import WorkflowMCP
from trame_llm.paraview import ParaViewMCP


class TestApp:
    def __init__(self):
        self.server = get_server(client_type="vue3")
        self.state = self.server.state
        self.ctrl = self.server.controller
        
        # Create view
        self.view = simple.CreateRenderView()
        self.view.ViewSize = [800, 600]
        self.view.Background = [0.2, 0.2, 0.3]
        
        # Load data
        data_file = '/Users/jeff.lee/gitsync/trame-cfd-mcp/examples/cfd_assistant/test.vtm'
        if os.path.exists(data_file):
            reader = simple.OpenDataFile(data_file)
            simple.UpdatePipeline()
            simple.Show(reader, self.view)
            simple.ResetCamera(self.view)
            print(f"Loaded: {data_file}")
        
        # Setup LLM
        print("Setting up LLM client...")
        self.llm_client = LLMClient(max_iteractions=15)
        
        base_mcp = ParaViewMCP(self)
        workflow_mcp = WorkflowMCP(base_mcp)
        self.llm_client.register_mcp(workflow_mcp)
        print("MCP registered")
        
        self._build_ui()
    
    def update(self):
        self.ctrl.view_update()
    
    def reset_camera(self):
        simple.ResetCamera(self.view)
        self.update()
    
    def _build_ui(self):
        with SinglePageLayout(self.server) as layout:
            layout.title.set_text("CFD Analysis Assistant")
            
            with layout.content:
                # ParaView view takes full width, Chat widget overlays in corner
                with vuetify3.VContainer(fluid=True, classes="fill-height pa-0"):
                    view_widget = paraview.VtkRemoteView(
                        self.view,
                        style="width: 100%; height: 100%;",
                    )
                    self.ctrl.view_update = view_widget.update
                
                # Chat widget - uses its default bottom-right overlay style
                # Click the chat icon in the bottom-right to expand
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
                    llm_client=self.llm_client,
                )
    
    def start(self):
        print("Starting server at http://localhost:8080")
        print("Click the chat icon in the bottom-right corner to open the chat panel")
        self.server.start(open_browser=True)


if __name__ == "__main__":
    app = TestApp()
    app.start()
