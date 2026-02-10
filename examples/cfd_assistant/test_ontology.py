#!/usr/bin/env python
"""
Test workflow with ontology-based explanation.
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
    
    llm = TrackedLLMClient(max_iteractions=10)
    llm.set_progress_handler(collector.progress_callback)
    llm.register_mcp(workflow_mcp)
    await llm.initialize()
    
    print(f'{len(llm.tools)} tools discovered')
    print(f'Model: {llm.config.model}\n')
    
    # Test with explanation request
    prompt = "Show me the vortex structures and explain what I'm seeing. What does the Q-criterion visualization tell me about the flow? Save to output/test_vortex_explained.png"
    
    print(f'PROMPT: {prompt}')
    print("="*60)
    
    await llm.process_prompt(prompt)
    
    collector.save_json("output/ontology_results.json")
    
    print("\n" + "="*60)
    llm.print_report()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
