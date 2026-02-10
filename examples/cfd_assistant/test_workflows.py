#!/usr/bin/env python
"""
Test all CFD workflows using WorkflowMCP.
High-level tools only - LLM does intent matching, workflows execute deterministically.
"""
import sys
import asyncio
sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from paraview_llm import WorkflowMCP, TrackedLLMClient
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import ProgressType


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
        if len(msg) > 300:
            msg = msg[:300] + "..."
        print(f"[result] {msg}")
    elif ptype == ProgressType.MCP_ERROR:
        print(f"[ERROR] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        if len(msg) > 150:
            msg = msg[:150] + "..."
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
    
    llm = TrackedLLMClient(max_iteractions=10)
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}\n')
    
    # Simple natural prompts
    prompts = [
        ("vortex", "Show vortices. Save to output/test_vortex.png"),
        ("streamlines", "Show streamlines. Save to output/test_streamlines.png"),
        ("slice", "Show a slice through the wake. Save to output/test_slice.png"),
        ("histogram", "Show pressure histogram. Save to output/test_histogram.png"),
        ("forces", "Show force distribution. Save to output/test_forces.png"),
    ]
    
    for name, prompt in prompts:
        print(f'\n{"="*60}')
        print(f'TEST: {name}')
        print(f'PROMPT: {prompt}')
        print("="*60)
        
        # Reset between tests
        sources = list(simple.GetSources().items())
        for sname, proxy in sources:
            if proxy != reader:
                try:
                    simple.Delete(proxy)
                except:
                    pass
        
        for v in simple.GetViews():
            if v != view:
                try:
                    simple.Delete(v)
                except:
                    pass
        
        simple.SetActiveView(view)
        simple.SetActiveSource(reader)
        simple.Show(reader, view)
        simple.ResetCamera(view)
        simple.Render(view)
        
        await llm.process_prompt(prompt)
    
    print(f'\n{"="*60}')
    llm.print_report()
    print("DONE - check output/*.png files")


if __name__ == "__main__":
    asyncio.run(main())
