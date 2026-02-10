#!/usr/bin/env python
"""Test vortex isosurface visualization via LLM - all methods."""
import sys
import asyncio
import os
sys.path.insert(0, '/Users/jeff.lee/gitsync/paraview_llm/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')

from dotenv import load_dotenv
load_dotenv()

from paraview import simple
from paraview_llm import ExtendedParaViewMCP
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient, ProgressType

def setup():
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    return reader, view

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

os.makedirs("output", exist_ok=True)

def progress_callback(ptype, msg):
    if ptype == ProgressType.MCP_SELECTION:
        print(f"[tool] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        print(f"[response] {msg[:200]}...")

async def run_test(name, query, method):
    # Clean slate
    for n, p in list(simple.GetSources().items()):
        simple.Delete(p)
    
    reader, view = setup()
    
    reader_name = None
    for n, p in simple.GetSources().items():
        if p == reader:
            reader_name = n[0]
            break
    
    app = MinimalApp()
    base_mcp = ParaViewMCP(app)
    ext = ExtendedParaViewMCP(base_mcp)
    
    llm = LLMClient()
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(ext)
    await llm.initialize()
    
    print(f'\n{"="*60}')
    print(f'=== {name} ===')
    full_query = query.format(reader_name=reader_name)
    print(f'QUERY: {full_query}')
    await llm.process_prompt(full_query)
    
    simple.Render()
    filename = f'output/test_vortex_{method}.png'
    simple.SaveScreenshot(filename, view)
    print(f'Saved: {filename}')

async def main():
    tests = [
        ("Q-criterion", "Create a vortex isosurface using Q-criterion for {reader_name}", "q"),
        ("Vorticity magnitude", "Create a vortex isosurface using vorticity magnitude for {reader_name}", "vorticity"),
        ("Lambda2", "Create a vortex isosurface using lambda2 criterion for {reader_name}", "lambda2"),
    ]
    
    for name, query, method in tests:
        await run_test(name, query, method)

asyncio.run(main())
