#!/usr/bin/env python
"""
Test boundary layer analysis workflow.
"""
import sys
import asyncio
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

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
    
    # Boundary layer analysis prompt
    prompt = """Analyze the boundary layer at several locations along the body (x=0.3, 0.5, 0.7).
Compare the boundary layer thickness and shape factor at each location.
What does this tell us about the flow development and drag?
Save the charts to output/bl_*.png"""
    
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
