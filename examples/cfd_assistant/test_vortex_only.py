#!/usr/bin/env python
"""
Isolated test for vortex workflow.
Uses WorkflowMCP with high-level tools only.
"""
import sys
import asyncio
sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from paraview_llm import WorkflowMCP
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType


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


def progress_callback(ptype, msg):
    if ptype == ProgressType.MCP_SELECTION:
        print(f"[call] {msg}")
    elif ptype == ProgressType.MCP:
        print(f"[result] {msg}")
    elif ptype == ProgressType.MCP_ERROR:
        print(f"[ERROR] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        print(f"[llm] {msg}")
    elif ptype == ProgressType.MAX_ITERATION:
        print(f"[LIMIT] {msg}")
    elif ptype == ProgressType.ERROR:
        print(f"[ERROR] {msg}")


async def main():
    # Setup
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    app = MinimalApp()
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    
    llm = LLMClient(max_iteractions=10)
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}\n')
    
    prompt = "Show vortices using Q-criterion. Save to output/test_vortex.png"
    
    print(f'PROMPT: {prompt}')
    print("="*60)
    
    await llm.process_prompt(prompt)
    
    # Debug: print final pipeline state
    print("\n" + "="*60)
    print("FINAL PIPELINE STATE:")
    for name, proxy in simple.GetSources().items():
        rep = simple.GetRepresentation(proxy, view)
        vis = rep.Visibility if rep else "no rep"
        print(f"  {name[0]}: visible={vis}, type={proxy.GetXMLName()}")
        
        # For Contour, show settings
        if 'Contour' in name[0]:
            print(f"    ContourBy: {proxy.ContourBy}")
            print(f"    Isosurfaces: {proxy.Isosurfaces}")
    
    print("\nDONE - check output/test_vortex.png")


if __name__ == "__main__":
    asyncio.run(main())
