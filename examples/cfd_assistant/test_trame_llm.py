"""
Test trame_llm ParaView MCP with direct prompts.

This tests what the base trame_llm can do without our CFD extension.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType


class MinimalApp:
    """Minimal app stub for ParaViewMCP."""
    def update(self): 
        simple.Render()
    def reset_camera(self): 
        simple.ResetCamera()
    class ctrl:
        class on_active_proxy_change:
            @staticmethod
            def exists(): return False
        class on_data_change:
            @staticmethod
            def exists(): return False


def progress_handler(msg_type: ProgressType, msg: str):
    """Print progress messages."""
    print(f"[{msg_type.value:15}] {msg[:100]}")


async def test_prompt(llm_client, prompt: str):
    """Test a single prompt."""
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)
    
    await llm_client.process_prompt(prompt)
    
    # Show what was created
    print("\nPipeline after prompt:")
    for name, proxy in simple.GetSources().items():
        print(f"  {name[0]}")


async def main():
    # Load data
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    print("Data loaded. Available fields:")
    di = reader.GetPointDataInformation()
    for i in range(di.GetNumberOfArrays()):
        print(f"  {di.GetArray(i).GetName()}")
    
    # Setup LLM client with ParaViewMCP
    app = MinimalApp()
    pv_mcp = ParaViewMCP(app)
    
    llm_client = LLMClient(max_iteractions=10)
    llm_client.register_mcp(pv_mcp)
    llm_client.set_progress_handler(progress_handler)
    
    await llm_client.initialize()
    
    print(f"\nDiscovered {len(llm_client.tools)} tools:")
    for tool in llm_client.tools:
        print(f"  {tool['name']}")
    
    # Test prompts - see what trame_llm can do on its own
    test_prompts = [
        "Create a slice and color it by pressure",
        # "Create a slice at z=0 with normal pointing in the z direction, color it by pressure",
        # "Show me streamlines seeded from a point at the inlet",
        # "Create a contour of pressure at value 0.9",
    ]
    
    for prompt in test_prompts:
        await test_prompt(llm_client, prompt)
        
        # Save screenshot
        simple.Render(view)
        filename = prompt.replace(" ", "_")[:30] + ".png"
        simple.SaveScreenshot(f"output/trame_llm_{filename}", view, ImageResolution=[1024, 768])
        print(f"Saved: output/trame_llm_{filename}")


if __name__ == "__main__":
    asyncio.run(main())
