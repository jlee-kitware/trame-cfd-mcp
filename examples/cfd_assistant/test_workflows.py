#!/usr/bin/env python
"""
Test all CFD workflows using WorkflowMCP.
High-level tools only - LLM reasons about what to do, workflows execute deterministically.
"""
import sys
import asyncio
import pathlib
_repo_src = pathlib.Path(__file__).parent.parent.parent / 'src'
if _repo_src.exists():
    sys.path.insert(0, str(_repo_src))
_trame_llm = os.environ.get('TRAME_LLM_SRC')
if _trame_llm:
    sys.path.insert(0, _trame_llm)

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from trame_cfd_mcp import WorkflowMCP, TrackedLLMClient
from trame_llm.paraview import ParaViewMCP
from test_utils import ResultCollector, MinimalApp


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
    
    collector = ResultCollector(truncate_console=300)
    
    llm = TrackedLLMClient(max_iteractions=10)
    llm.set_progress_handler(collector.progress_callback)
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
        
        # Start tracking this test
        collector.start_test(name, prompt)
        
        # Reset between tests
        sources = list(simple.GetSources().items())
        for sname, proxy in sources:
            if proxy != reader:
                try:
                    simple.Delete(proxy)
                except Exception:
                    pass
        
        for v in simple.GetViews():
            if v != view:
                try:
                    simple.Delete(v)
                except Exception:
                    pass
        
        simple.SetActiveView(view)
        simple.SetActiveSource(reader)
        simple.Show(reader, view)
        simple.ResetCamera(view)
        simple.Render(view)
        
        await llm.process_prompt(prompt)
    
    collector.save_json("output/workflows_results.json")
    
    print(f'\n{"="*60}')
    llm.print_report()
    print("DONE - check output/*.png files")


if __name__ == "__main__":
    asyncio.run(main())
