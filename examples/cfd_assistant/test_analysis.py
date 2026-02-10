#!/usr/bin/env python
"""
Test multi-step analysis - let LLM explore the flow physics.
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
    
    collector = ResultCollector(truncate_console=400)
    
    llm = TrackedLLMClient(max_iteractions=20)
    llm.set_progress_handler(collector.progress_callback)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}\n')
    
    # Open-ended analysis prompt
    prompt = """Analyze this CFD dataset to understand the flow physics. 
I want to understand the wake structure and how it relates to drag.
Create the visualizations you need and explain what you find.
Save each visualization to output/analysis_*.png"""
    
    print(f'PROMPT: {prompt}')
    print("="*60)
    
    await llm.process_prompt(prompt)
    
    collector.save_json("output/analysis_results.json")
    
    print("\n" + "="*60)
    llm.print_report()
    print("DONE - check output/analysis_*.png files")


if __name__ == "__main__":
    asyncio.run(main())
