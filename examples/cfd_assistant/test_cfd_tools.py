"""
Test CFD Tools MCP with trame_llm.

Verifies that LLM can:
1. Pick appropriate tools from descriptions
2. Chain query → action (e.g., detect_wake → create_streamlines)
3. Pass data between tool calls
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
from paraview_llm.cfd_tools import CFDToolsMCP


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
    # Truncate long messages
    if len(msg) > 100:
        msg = msg[:100] + "..."
    print(f"{prefix} {msg}")


async def test_query(llm_client, query: str, view, test_name: str):
    """Test a single query."""
    print("\n" + "=" * 70)
    print(f"TEST: {test_name}")
    print(f"QUERY: {query}")
    print("=" * 70)
    
    await llm_client.process_prompt(query)
    
    # Show pipeline
    print("\nPipeline after query:")
    for name, proxy in simple.GetSources().items():
        vis = simple.GetDisplayProperties(proxy, view=view)
        visible = vis.Visibility if vis else "?"
        print(f"  {name[0]:40} visible={visible}")
    
    # Save screenshot
    simple.Render(view)
    filename = f"output/cfd_tools_{test_name}.png"
    simple.SaveScreenshot(filename, view, ImageResolution=[1024, 768])
    print(f"Saved: {filename}")


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
    cfd_tools_mcp = CFDToolsMCP(app, extended_mcp)
    
    # Register both MCPs
    llm_client = LLMClient(max_iteractions=10)
    llm_client.register_mcp(pv_mcp)        # Base ParaView tools
    llm_client.register_mcp(cfd_tools_mcp) # CFD tools
    llm_client.set_progress_handler(progress_handler)
    
    await llm_client.initialize()
    
    print(f"\nDiscovered {len(llm_client.tools)} tools:")
    for tool in llm_client.tools:
        print(f"  {tool['name']}")
    
    # Test queries - from simple to complex
    tests = [
        # Simple query tool
        ("describe_data", "What data is loaded?"),
        
        # Simple action tool  
        ("vortices", "Show me the vortices"),
        
        # Should chain: detect_wake → create_streamlines
        ("wake_chain", "Show streamlines in the wake region"),
        
        # Should chain: detect_wake → create_body_slice
        ("wake_slice", "Create a slice through the wake"),
        
        # Analysis
        ("forces", "What are the drag and lift forces?"),
    ]
    
    for test_name, query in tests:
        # Reset between tests - delete derived filters but keep reader
        sources = list(simple.GetSources().items())
        for name, proxy in sources:
            if 'Reader' not in name[0]:
                try:
                    simple.Hide(proxy, view)
                    simple.Delete(proxy)
                except:
                    pass
        
        # Ensure reader is visible and active
        simple.Show(reader, view)
        simple.SetActiveSource(reader)
        simple.ResetCamera()
        simple.Render(view)
        
        await test_query(llm_client, query, view, test_name)


if __name__ == "__main__":
    asyncio.run(main())
