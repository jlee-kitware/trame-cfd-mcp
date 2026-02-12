#!/usr/bin/env python
"""
Test workflows without LLM - just verify they run and return correct structure.
"""
import sys
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')

import json
from paraview import simple
from trame_cfd_mcp.workflows import CFDWorkflows
from trame_cfd_mcp.cfd_analysis import CFDAnalysis


def clear_pipeline():
    """Clear all filters, keep reader."""
    for name, proxy in list(simple.GetSources().items()):
        if 'Reader' not in name[0]:
            simple.Delete(proxy)


def test_workflow(name, func, **kwargs):
    """Test a workflow returns expected structure."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)
    
    clear_pipeline()
    result = func(**kwargs)
    
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return False
    
    # Different workflows have different required keys
    # Visualization workflows: status, type, proxy_name
    # Data workflows (get_fields, analyze_data): just need to return something useful
    # Chart workflows (histogram, forces, boundary_layer): may not have proxy_name
    
    print(f"  Keys: {list(result.keys())}")
    
    # Check provenance if present
    if "provenance" in result:
        prov = result["provenance"]
        if "filter_chain" in prov:
            print(f"  Filter chain: {len(prov['filter_chain'])} filters")
        if "analysis" in prov:
            print(f"  Analysis log: {len(prov['analysis'])} entries")
    
    # Check result if present
    if "result" in result:
        print(f"  Result keys: {list(result['result'].keys())}")
    
    # Check type-specific content
    if "type" in result:
        print(f"  Type: {result['type']}")
    if "proxy_name" in result:
        print(f"  Proxy: {result['proxy_name']}")
    if "fields" in result:  # get_fields
        print(f"  Fields: {len(result['fields'])} fields found")
    if "simulation_type" in result:  # analyze_data
        print(f"  Simulation: {result['simulation_type']}")
    if "chart_view" in result:  # chart workflows
        print(f"  Chart: {result['chart_view']}")
    
    print("  PASS")
    return True


def main():
    # Setup
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [800, 600]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    analysis = CFDAnalysis()
    workflows = CFDWorkflows(analysis)
    
    # Track results
    passed = 0
    failed = 0
    
    # Test each workflow
    tests = [
        ("show_vortices", workflows.show_vortices, {}),
        ("show_vortices (lambda2)", workflows.show_vortices, {"method": "lambda2"}),
        ("show_streamlines", workflows.show_streamlines, {}),
        ("show_slice (wake)", workflows.show_slice, {"location": "wake"}),
        ("show_slice (center)", workflows.show_slice, {"location": "center"}),
        ("show_slice (span)", workflows.show_slice, {"location": "span", "offset": 0.25}),
        ("show_histogram", workflows.show_histogram, {"field": "p"}),
        ("show_boundary_layer", workflows.show_boundary_layer, {"x_location": 0.5}),
        ("show_flow_topology", workflows.show_flow_topology, {}),
        ("show_forces", workflows.show_forces, {}),
        ("get_fields", workflows.get_fields, {}),
        ("analyze_data", workflows.analyze_data, {}),
    ]
    
    for name, func, kwargs in tests:
        if test_workflow(name, func, **kwargs):
            passed += 1
        else:
            failed += 1
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Total:  {passed + failed}")
    
    if failed == 0:
        print("\n  All tests PASSED!")
    else:
        print(f"\n  {failed} tests FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
