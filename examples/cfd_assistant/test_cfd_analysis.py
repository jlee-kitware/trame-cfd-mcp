"""
Test CFD Analysis MCP - Pure analysis tools + base ParaView visualization.

Demonstrates the separation:
- CFD analysis tools: compute fields, find values
- Base ParaView tools: create filters, visualize
"""

import asyncio
import sys

sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType
from paraview_llm import ExtendedParaViewMCP
from paraview_llm.cfd_analysis import CFDAnalysisMCP


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


def progress_handler(msg_type: ProgressType, msg: str):
    prefix = f"[{msg_type.value:15}]"
    if len(msg) > 120:
        msg = msg[:120] + "..."
    print(f"{prefix} {msg}")


async def test_query(llm_client, query: str, view):
    """Test a single query."""
    print("\n" + "=" * 70)
    print(f"QUERY: {query}")
    print("=" * 70)
    
    await llm_client.process_prompt(query)
    
    print("\nPipeline:")
    for name, proxy in simple.GetSources().items():
        vis = simple.GetDisplayProperties(proxy, view=view)
        visible = vis.Visibility if vis else "?"
        print(f"  {name[0]:40} visible={visible}")
    
    simple.Render(view)


async def main():
    # Load data
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    # Setup MCPs
    app = MinimalApp()
    pv_mcp = ParaViewMCP(app)
    extended_mcp = ExtendedParaViewMCP(pv_mcp)
    analysis_mcp = CFDAnalysisMCP(app, extended_mcp)
    
    # Register both MCPs
    llm_client = LLMClient(max_iteractions=10)
    llm_client.register_mcp(pv_mcp)         # Base ParaView: create, Contour, StreamTracer
    llm_client.register_mcp(analysis_mcp)   # CFD Analysis: compute_vortex_field, suggest_threshold
    llm_client.set_progress_handler(progress_handler)
    
    await llm_client.initialize()
    
    print(f"\n{len(llm_client.tools)} tools available:")
    for tool in llm_client.tools:
        print(f"  {tool['name']}")
    
    # Test the new pattern:
    # "Show vortices" should:
    #   1. compute_vortex_field() → adds Q array, returns proxy_name
    #   2. suggest_threshold("Q") → returns value
    #   3. [ParaView] create Contour on that proxy at that value
    
    queries = [
        "What data is loaded?",
        "Show me the vortices using Q-criterion",
        "Show streamlines in the wake",
    ]
    
    for query in queries:
        # Reset
        for name, proxy in list(simple.GetSources().items()):
            if 'Reader' not in name[0]:
                try:
                    simple.Hide(proxy, view)
                    simple.Delete(proxy)
                except:
                    pass
        
        simple.Show(reader, view)
        simple.SetActiveSource(reader)
        simple.ResetCamera()
        
        await test_query(llm_client, query, view)
        
        # Save screenshot
        fname = query.lower().replace(" ", "_")[:20] + ".png"
        simple.SaveScreenshot(f"output/analysis_{fname}", view, ImageResolution=[1024, 768])
        print(f"Saved: output/analysis_{fname}")


if __name__ == "__main__":
    asyncio.run(main())
