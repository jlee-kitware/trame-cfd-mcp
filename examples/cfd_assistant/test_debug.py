#!/usr/bin/env python
"""
Debug test - verbose logging of LLM tool calls.
"""
import sys
import asyncio
import os
import json
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


def progress_callback(ptype, msg):
    # Print everything to understand the flow
    prefix = f"[{ptype.value:15}]"
    if len(msg) > 600:
        msg = msg[:600] + "..."
    print(f"{prefix} {msg}")


async def main():
    os.makedirs("output", exist_ok=True)
    
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
    
    llm = LLMClient()
    llm.set_progress_handler(progress_callback)
    llm.register_mcp(ext)
    await llm.initialize()
    
    # Get reader name
    reader_name = None
    for n, p in simple.GetSources().items():
        if p == reader:
            reader_name = n[0]
            break
    
    # Print what tools exist
    print("=" * 60)
    print(f"TOOLS ({len(llm.tools)}):")
    print("=" * 60)
    for t in sorted(llm.tools, key=lambda x: x['name']):
        print(f"  {t['name']}")
    print("=" * 60)
    
    # Test just vortex
    print("\n" + "=" * 60)
    print("TEST: Vortex Q-criterion")
    print("=" * 60)
    query = f"""Show vortices using Q-criterion for {reader_name}. 
    
Steps:
1. Call compute_vortex_field(proxy_name="{reader_name}", method="q_criterion") - returns field_name, proxy_name, threshold
2. Call hide_all()
3. Call create("Contour", input_proxy=<proxy_name from step 1>)
4. Call update_string_property(proxy_name=<name from step 3>, property_name="ContourBy", property_value=["POINTS", <field_name from step 1>])
5. Call update_list_property(proxy_name=<name from step 3>, property_name="Isosurfaces", property_value=[<threshold from step 1>])
6. Call update_color(proxy_name=<name from step 3>, field_name="Velocity")
7. Call reset_camera()
"""
    print(f"QUERY: {query}\n")
    
    await llm.process_prompt(query)
    
    print("\n" + "=" * 60)
    print("FINAL PIPELINE STATE:")
    print("=" * 60)
    for name, p in simple.GetSources().items():
        rep = simple.GetRepresentation(p, view)
        vis = rep.Visibility if rep else 'no rep'
        print(f"  {name[0]:40} visible={vis}")
    
    simple.Render()
    simple.SaveScreenshot('output/debug_vortex.png', view)
    print("\nSaved: output/debug_vortex.png")


if __name__ == "__main__":
    asyncio.run(main())
