#!/usr/bin/env python
"""
Test boundary layer analysis workflow.
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
    
    collector = ResultCollector(truncate_console=500)
    
    llm = TrackedLLMClient(max_iteractions=15)
    llm.set_progress_handler(collector.progress_callback)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}\n')
    
    # Boundary layer analysis prompt - includes 3D context visualization
    prompt = """Analyze how the boundary layer develops along the body. 
Pick an appropriate span station and sample the boundary layer at several chordwise locations.
Compare the boundary layer thickness and shape factor to understand flow development.
What does this tell us about transition and drag?
Show a 3D visualization of the probe locations on a velocity slice.
Save the charts to output/bl_*.png and the 3D view to output/bl_context.png"""
    
    print(f'PROMPT: {prompt}')
    print("="*60)
    
    collector.start_test("boundary_layer", prompt)
    await llm.process_prompt(prompt)
    
    collector.save_json("output/boundary_layer_results.json")
    
    print("\n" + "="*60)
    llm.print_report()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
