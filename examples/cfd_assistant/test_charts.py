#!/usr/bin/env python
"""Test histogram and force distribution charts via LLM."""
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

reader = simple.OpenDataFile('test.vtm')
simple.UpdatePipeline()

# Get reader name
reader_name = None
for name, p in simple.GetSources().items():
    if p == reader:
        reader_name = name[0]
        break
print(f"Data source: {reader_name}")

view = simple.CreateRenderView()
view.ViewSize = [1024, 768]
simple.SetActiveView(view)
simple.Show(reader, view)
simple.ResetCamera()

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

app = MinimalApp()
base_mcp = ParaViewMCP(app)
ext = ExtendedParaViewMCP(base_mcp)

os.makedirs("output", exist_ok=True)

def progress_callback(ptype, msg):
    if ptype == ProgressType.MCP_SELECTION:
        print(f"[tool] {msg}")
    elif ptype == ProgressType.LLM_RESPONSE:
        print(f"[response] {msg[:300]}...")

async def run_test(llm, name, query):
    print(f'\n=== {name} ===')
    print(f'QUERY: {query}')
    ext._last_chart_view = None  # Reset chart view
    await llm.process_prompt(query)
    if ext._last_chart_view:
        simple.SaveScreenshot(f'output/test_{name}.png', ext._last_chart_view)
        print(f'Saved: output/test_{name}.png')
    else:
        print('ERROR: No chart view created')

async def main():
    llm = LLMClient()
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(ext)
    await llm.initialize()
    
    await run_test(llm, 'histogram', f'Create a histogram chart of pressure values for {reader_name}')
    await run_test(llm, 'drag_distribution', f'Create a force distribution chart showing drag for {reader_name}')
    await run_test(llm, 'lift_distribution', f'Create a force distribution chart showing lift for {reader_name}')

asyncio.run(main())
