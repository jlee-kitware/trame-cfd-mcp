"""
Test trame_llm with both ParaViewMCP and CFDMCP registered.

The LLM sees ALL tools and picks what it needs:
- Basic ParaView ops → ParaViewMCP tools
- CFD analysis → CFDMCP tools
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
from paraview_llm.cfd_mcp import CFDMCP
from paraview_llm import ExtendedParaViewMCP


class MinimalApp:
    """Minimal app stub."""
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
    prefix = f"[{msg_type.value:15}]"
    # Truncate long messages
    if len(msg) > 100:
        msg = msg[:100] + "..."
    print(f"{prefix} {msg}")


async def test_prompt(llm_client, prompt: str, view, test_num: int):
    """Test a single prompt."""
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)
    
    await llm_client.process_prompt(prompt)
    
    # Show what was created
    print("\nPipeline after prompt:")
    for name, proxy in simple.GetSources().items():
        print(f"  {name[0]}")
    
    # Save screenshot
    simple.Render(view)
    filename = f"output/hybrid_test_{test_num}.png"
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
    pv_mcp = ParaViewMCP(app)  # Base ParaView tools
    
    # Extended MCP for CFD tools to use
    extended_mcp = ExtendedParaViewMCP(pv_mcp)
    cfd_mcp = CFDMCP(app, extended_mcp)  # CFD-specific tools
    
    # Create LLM client with BOTH MCPs
    llm_client = LLMClient(max_iteractions=10)
    llm_client.register_mcp(pv_mcp)   # Base tools
    llm_client.register_mcp(cfd_mcp)  # CFD tools
    llm_client.set_progress_handler(progress_handler)
    
    await llm_client.initialize()
    
    print(f"\nDiscovered {len(llm_client.tools)} tools:")
    for tool in llm_client.tools:
        print(f"  {tool['name']}")
    
    # Test prompts - mix of CFD-specific and generic
    test_prompts = [
        # CFD-specific - should use CFDMCP
        ("Show me the vortices", 1),
        
        # Generic ParaView - should use ParaViewMCP
        ("Change the color to red", 2),
        
        # CFD-specific
        ("What are the drag and lift forces?", 3),
        
        # Generic
        ("Create a slice", 4),
        
        # CFD-specific with context
        ("Show helical vortex structures", 5),
    ]
    
    for prompt, num in test_prompts:
        # Reset state between tests
        simple.Delete()
        reader = simple.OpenDataFile('test.vtm')
        simple.UpdatePipeline()
        simple.Show(reader, view)
        simple.ResetCamera()
        
        await test_prompt(llm_client, prompt, view, num)


if __name__ == "__main__":
    asyncio.run(main())
