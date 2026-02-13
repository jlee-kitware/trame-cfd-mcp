#!/usr/bin/env python
"""Minimal trame test - no LLM, just ParaView view"""
import sys
import os
import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

os.environ.setdefault("PV_ALLOW_BATCH_INTERACTION", "1")

from paraview import simple

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3, paraview

def main():
    server = get_server(client_type="vue3")
    state = server.state
    ctrl = server.controller
    
    # Create view
    view = simple.CreateRenderView()
    view.ViewSize = [800, 600]
    view.Background = [0.2, 0.2, 0.3]
    
    # Load data
    data_file = '/Users/jeff.lee/gitsync/trame-cfd-mcp/examples/cfd_assistant/test.vtm'
    if os.path.exists(data_file):
        reader = simple.OpenDataFile(data_file)
        simple.UpdatePipeline()
        simple.Show(reader, view)
        simple.ResetCamera(view)
        print(f"Loaded: {data_file}")
    
    # Build UI
    with SinglePageLayout(server) as layout:
        layout.title.set_text("Minimal Test")
        
        with layout.content:
            with vuetify3.VContainer(fluid=True, classes="fill-height pa-0"):
                paraview.VtkRemoteView(
                    view,
                    style="width: 100%; height: 100%;",
                )
    
    print("Starting server at http://localhost:8080")
    server.start(open_browser=True)

if __name__ == "__main__":
    main()
