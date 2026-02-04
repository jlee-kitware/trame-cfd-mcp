#!/usr/bin/env pvpython
"""Quick test for pressure distribution query"""

import sys
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
import asyncio

# Load data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

reader_name = None
for name, proxy in simple.GetSources().items():
    if proxy == reader:
        reader_name = name[0]
        break

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1024, 768]

# Show data
display = simple.Show(reader, view)
display.Opacity = 0.3

# Setup MCP
from trame_llm.paraview import ParaViewMCP
from paraview_llm.extended_mcp import ExtendedParaViewMCP

class MinimalApp:
    def update(self): simple.Render()
    def reset_camera(self): simple.ResetCamera()
    class ctrl:
        class on_active_proxy_change:
            @staticmethod
            def exists(): return False
        class on_data_change:
            @staticmethod
            def exists(): return False

app = MinimalApp()
base_mcp = ParaViewMCP(app)
extended_mcp = ExtendedParaViewMCP(base_mcp)

# Create LLM client and orchestrator
from trame_llm.core import LLMClient
from paraview_llm.orchestrator import Orchestrator

llm_client = LLMClient()
llm_client.register_mcp(extended_mcp)
orchestrator = Orchestrator()

async def test():
    await llm_client.initialize()
    print(f"Tools: {len(llm_client.tools)}")
    
    result = await orchestrator.run(
        user_query="show me the pressure distribution",
        llm_client=llm_client,
        data_source=reader_name
    )
    
    print(f"Result: {result}")
    simple.Render(view)
    simple.SaveScreenshot("output/pressure_test.png", view, ImageResolution=[1024, 768])
    print("Saved: output/pressure_test.png")

asyncio.run(test())
