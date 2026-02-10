#!/usr/bin/env python
"""
Test all CFD visualization workflows via LLM.
Tracks token usage and costs.
"""
import sys
import asyncio
sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from paraview_llm import ExtendedParaViewMCP
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


# Cost tracking
total_input_tokens = 0
total_output_tokens = 0

def progress_callback(ptype, msg):
    if ptype == ProgressType.MCP_SELECTION:
        print(f"[call] {msg}")
    elif ptype == ProgressType.MCP:
        if len(msg) > 400:
            msg = msg[:400] + "..."
        print(f"[result] {msg}")
    elif ptype == ProgressType.MCP_ERROR:
        print(f"[ERROR] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        if len(msg) > 200:
            msg = msg[:200] + "..."
        print(f"[llm] {msg}")
    elif ptype == ProgressType.MAX_ITERATION:
        print(f"[LIMIT] {msg}")
    elif ptype == ProgressType.ERROR:
        print(f"[ERROR] {msg}")


async def main():
    global total_input_tokens, total_output_tokens
    
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
    ext = ExtendedParaViewMCP(base_mcp)
    
    llm = LLMClient(max_iteractions=25)
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(ext)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}')
    print(f'Provider: {llm.config.provider}\n')
    
    # Simple natural prompts - workflow is in the MCP instructions
    prompts = [
        "Show vortices using Q-criterion. Save to output/test_vortex.png",
        "Create streamlines in the wake. Save to output/test_streamlines.png",
        "Create a slice through the wake showing velocity. Save to output/test_slice.png",
        "Create a histogram of pressure. Save to output/test_histogram.png",
        "Show force distribution. Save to output/test_forces.png",
    ]
    
    for i, prompt in enumerate(prompts):
        print(f'\n{"="*60}')
        print(f'TEST {i+1}: {prompt[:60]}...')
        print("="*60)
        
        # Reset between tests
        sources = list(simple.GetSources().items())
        for name, proxy in sources:
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
        simple.Show(reader, view)
        simple.SetActiveSource(reader)
        
        await llm.process_prompt(prompt)
    
    # Cost summary (GPT-4o-mini pricing: $0.15/1M input, $0.60/1M output)
    print(f'\n{"="*60}')
    print("DONE - check output/*.png files")


if __name__ == "__main__":
    asyncio.run(main())
