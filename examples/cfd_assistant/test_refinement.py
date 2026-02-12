#!/usr/bin/env python
"""
Test workflow + refinement pattern.

Tests the LLM's ability to:
1. Create visualization with show_* workflow
2. Use provenance/tip to refine with update_* tools
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
    
    # Test refinement scenarios
    # Each test is a multi-turn conversation simulated as a single prompt
    
    tests = [
        {
            "name": "vortex_threshold",
            "prompt": (
                "Show vortices, then show MORE vortex structures by lowering the threshold. "
                "Save the final result to output/test_vortex_more.png"
            ),
            "expected_tools": ["show_vortices", "update_list_property", "save_screenshot"],
        },
        {
            "name": "vortex_wireframe",
            "prompt": (
                "Show vortices and then change them to wireframe representation. "
                "Save to output/test_vortex_wireframe.png"
            ),
            "expected_tools": ["show_vortices", "update_representation", "save_screenshot"],
        },
        {
            "name": "slice_recolor",
            "prompt": (
                "Show a slice through the wake, then recolor it by pressure instead of velocity. "
                "Save to output/test_slice_pressure.png"
            ),
            "expected_tools": ["show_slice", "update_color", "save_screenshot"],
        },
        {
            "name": "streamlines_style",
            "prompt": (
                "Show streamlines, change them to points representation, and color by pressure. "
                "Save to output/test_streamlines_points.png"
            ),
            "expected_tools": ["show_streamlines", "update_representation", "update_color", "save_screenshot"],
        },
        {
            "name": "multi_refinement",
            "prompt": (
                "Show vortices. I want to see more detail, so lower the threshold significantly. "
                "Then make them semi-transparent with opacity 0.5. "
                "Finally color by pressure. Save to output/test_vortex_refined.png"
            ),
            "expected_tools": ["show_vortices", "update_list_property", "update_display_property", "update_color", "save_screenshot"],
        },
    ]
    
    results = {}
    
    for test in tests:
        name = test["name"]
        prompt = test["prompt"]
        expected = test["expected_tools"]
        
        print(f'\n{"="*60}')
        print(f'TEST: {name}')
        print(f'PROMPT: {prompt}')
        print(f'EXPECTED TOOLS: {expected}')
        print("="*60)
        
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
        
        # Track tools called
        collector.clear()
        await llm.process_prompt(prompt)
        
        # Analyze what was called
        tools_called = collector.get_tool_names()
        
        # Check if expected tools were used
        missing = [t for t in expected if t not in tools_called]
        extra = [t for t in tools_called if t not in expected and t not in ["list_data", "get_fields", "analyze_data", "get_ontology"]]
        
        results[name] = {
            "prompt": prompt,
            "expected": expected,
            "called": tools_called,
            "missing": missing,
            "extra": extra,
            "success": len(missing) == 0
        }
        
        print(f'\nTOOLS CALLED: {tools_called}')
        print(f'MISSING: {missing}')
        print(f'SUCCESS: {results[name]["success"]}')
    
    # Summary
    print(f'\n{"="*60}')
    print("REFINEMENT TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results.values() if r["success"])
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result["success"] else "✗ FAIL"
        print(f'{status} {name}')
        if not result["success"]:
            print(f'       Missing: {result["missing"]}')
            print(f'       Called:  {result["called"]}')
    
    print(f'\n{passed}/{total} tests passed')
    
    collector.save_json("output/refinement_results.json")
    
    print(f'\n{"="*60}')
    llm.print_report()


if __name__ == "__main__":
    asyncio.run(main())
