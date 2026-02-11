#!/usr/bin/env python
"""
Test spanwise slice workflow with body context and Surface LIC.
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
    
    # Spanwise slice analysis prompt
    prompt = """Create spanwise slices at three span stations (offset=-0.3, 0.0, 0.3) to show 
the airfoil section flow patterns. Use Surface LIC representation to visualize the flow.
Save each slice to output/span_*.png and describe what the flow patterns reveal about 
separation or attachment on the wing."""
    
    print(f'PROMPT: {prompt}')
    print("="*60)
    
    await llm.process_prompt(prompt)
    
    collector.save_json("output/spanwise_slice_results.json")
    
    print("\n" + "="*60)
    llm.print_report()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
