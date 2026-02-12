#!/usr/bin/env python
"""
Test boundary layer analysis with debug section chart.
No LLM - directly tests the workflow functions.
"""
import sys
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')

from paraview import simple
from trame_cfd_mcp.workflows import CFDWorkflows
from trame_cfd_mcp.cfd_analysis import CFDAnalysis


def main():
    # Setup
    reader = simple.OpenDataFile('test.vtm')
    simple.UpdatePipeline()
    
    view = simple.CreateRenderView()
    view.ViewSize = [1024, 768]
    simple.SetActiveView(view)
    simple.Show(reader, view)
    simple.ResetCamera()
    
    analysis = CFDAnalysis()
    workflows = CFDWorkflows(analysis)
    
    # Sample boundary layer at multiple x/c locations
    x_locations = [0.03, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    span_fraction = 0.5  # mid-span
    
    print(f"Boundary Layer Analysis at {span_fraction*100:.0f}% span")
    print("=" * 60)
    print(f"{'x/c':>6} {'actual':>8} {'δ':>10} {'δ*':>10} {'θ':>10} {'H':>6}")
    print("-" * 60)
    
    bl_results = []
    for xc in x_locations:
        result = workflows.show_boundary_layer(x_over_chord=xc, span_fraction=span_fraction)
        bl_results.append(result)
        
        if 'error' in result:
            print(f"{xc:6.2f} ERROR: {result['error']}")
        else:
            actual_xc = result['x_over_chord']
            delta = result['delta']
            delta_star = result['delta_star']
            theta = result['theta']
            H = result['shape_factor']
            print(f"{xc:6.2f} {actual_xc:8.3f} {delta:10.5f} {delta_star:10.5f} {theta:10.5f} {H:6.2f}")
    
    print("-" * 60)
    
    # Create debug section chart (uses internal cache from show_boundary_layer calls)
    print("\nCreating debug section chart...")
    debug_result = workflows.create_section_debug_chart(
        title=f"Section at {span_fraction*100:.0f}% span with BL probe locations"
    )
    print(f"Debug chart: {debug_result}")
    
    # Save all charts
    print("\nSaving charts...")
    chart_idx = 0
    for v in simple.GetViews():
        if hasattr(v, 'ChartTitle'):
            filename = f'output/bl_debug_{chart_idx}.png'
            simple.SaveScreenshot(filename, v)
            print(f"  {filename}: {v.ChartTitle}")
            chart_idx += 1
    
    # Save individual BL profiles
    for i, result in enumerate(bl_results):
        if 'error' not in result:
            xc = result['x_over_chord']
            # The chart was already created by show_boundary_layer
            # We just need to identify which chart corresponds to which x/c
    
    print("\nDONE")


if __name__ == "__main__":
    main()
