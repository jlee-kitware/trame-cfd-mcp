#!/usr/bin/env python
"""CFD Chat app based on ptc.Lite with pipeline browser"""
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
        """
        Get current chat session cost and usage statistics.
        
        Returns token counts, estimated cost, and model info.
        Call this to see how much the current session has cost.
        """
        return self._llm_client.get_cost()
    
    def reset_session_cost(self) -> dict:
        """
        Reset the cost tracking counters to zero.
        
        Use this to start tracking cost for a new task.
        """
        self._llm_client.reset_cost()
        return {"status": "reset", "message": "Cost counters reset to zero"}
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration with cost tools added."""
        base_mcp = self._workflow_mcp.mcp
        
        # Add cost tools
        base_mcp["tools"] = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        
        return base_mcp


class CFDChat(Lite):
    """CFD Chat app extending ParaView Lite with LLM chat."""
    
    def __init__(self, data_file=None):
        # Load data first so Lite sees it
        if data_file and os.path.exists(data_file):
            reader = simple.OpenDataFile(data_file)
            simple.UpdatePipeline()
            simple.Show()
            simple.ResetCamera()
            print(f"Loaded: {data_file}")
        
        # Initialize Lite (gets view, toolbar with pipeline browser, etc.)
        super().__init__()
        
        self.state.trame__title = "CFD Analysis Assistant"
        
        # Setup LLM
        print("Setting up LLM client...")
        self.llm_client = LLMClient(max_iteractions=15)
        
        # Build MCP chain: ParaViewMCP -> WorkflowMCP -> CFDChatMCP (adds cost)
        base_mcp = ParaViewMCP(self)
        workflow_mcp = WorkflowMCP(base_mcp)
        chat_mcp = CFDChatMCP(workflow_mcp, self.llm_client)
        
        self.llm_client.register_mcp(chat_mcp)
        print("MCP registered")
        
        # Add chat widget
        self._add_chat()
    
    def _add_chat(self):
        # Force chat to start expanded
        self.state["trame_llm_chat_1_collapsed"] = False
        
        # Add chat widget to main UI
        with self.ui:
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


def main():
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        data_file = '/Users/jeff.lee/gitsync/trame-cfd-mcp/examples/cfd_assistant/test.vtm'
    
    print(f"Starting CFD Chat with: {data_file}")
    print("Click branch icon in left toolbar for pipeline browser")
    print("Chat icon in bottom-right corner")
    print("Keyboard: 'p' = pipeline, 'c' = color, 'r' = reset camera")
    
    app = CFDChat(data_file=data_file)
    app.start(open_browser=True)


if __name__ == "__main__":
    main()
