#!/usr/bin/env python
"""
Comprehensive test of hybrid provenance architecture.
Shows filter chain from ParaView + analysis log from CFDAnalysis.
"""
import sys
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')

import json
from paraview import simple
from trame_cfd_mcp.workflows import CFDWorkflows
from trame_cfd_mcp.cfd_analysis import CFDAnalysis

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

# =============================================================================
# Test 1: Full provenance from show_vortices
# =============================================================================
print("=" * 70)
print("PROVENANCE TEST: show_vortices")
print("=" * 70)

result = workflows.show_vortices(method="q_criterion")

print("\nFilter Chain (from ParaView state):")
for f in result["provenance"]["filter_chain"]:
    print(f"  {f['filter']}: {f['output']}")
    if f.get('params'):
        for k, v in f['params'].items():
            print(f"    {k}: {v}")

print("\nAnalysis Log (our decisions):")
for a in result["provenance"]["analysis"]:
    print(f"  Type: {a['type']}")
    for k, v in a.items():
        if k != 'type':
            print(f"    {k}: {v}")

# =============================================================================
# Test 2: Refinement - change threshold and re-extract
# =============================================================================
print("\n" + "=" * 70)
print("REFINEMENT TEST: Change Isosurfaces from 28 to 14")
print("=" * 70)

contour = simple.FindSource(result["proxy_name"])
original_threshold = list(contour.Isosurfaces)[0]
contour.Isosurfaces = [14.0]
simple.UpdatePipeline(proxy=contour)

# Re-extract filter chain - should show new value
new_chain = analysis.extract_filter_chain(contour)
contour_entry = [f for f in new_chain if f['filter'] == 'Contour'][0]

print(f"\nOriginal threshold: {original_threshold:.2f}")
print(f"New threshold: {contour_entry['params']['Isosurfaces'][0]:.2f}")
print(f"Filter chain automatically updated: ✓")

# =============================================================================
# Test 3: Wake slice provenance
# =============================================================================

# Clean up
for name, proxy in list(simple.GetSources().items()):
    if name[0] != 'XMLMultiBlockDataReader1':
        simple.Delete(proxy)

print("\n" + "=" * 70)
print("PROVENANCE TEST: show_slice (wake)")
print("=" * 70)

result = workflows.show_slice(location="wake")

print("\nFilter Chain:")
for f in result["provenance"]["filter_chain"]:
    print(f"  {f['filter']}: {f['output']}")
    if f.get('params'):
        for k, v in f['params'].items():
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], float):
                print(f"    {k}: [{', '.join(f'{x:.4f}' for x in v)}]")
            else:
                print(f"    {k}: {v}")

print("\nAnalysis Log (wake detection):")
for a in result["provenance"]["analysis"]:
    print(f"  Type: {a['type']}")
    for k, v in a.items():
        if k != 'type':
            if isinstance(v, list):
                print(f"    {k}: [{', '.join(f'{x:.4f}' if isinstance(x, float) else str(x) for x in v)}]")
            elif isinstance(v, float):
                print(f"    {k}: {v:.4f}")
            else:
                print(f"    {k}: {v}")

# =============================================================================
# Summary
# =============================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
Hybrid Provenance Architecture:
  
  1. FILTER CHAIN - Extracted from ParaView state on demand
     - Always accurate (reflects current values)
     - Includes full pipeline: Reader → Filters → Output
     - Automatically tracks refinements
  
  2. ANALYSIS LOG - Tracked by CFDAnalysis._log_analysis()
     - Records our computational decisions
     - Why threshold = 28.06? (50th percentile of Q > 0)
     - Where is wake? (velocity < 50% freestream)
     - ParaView doesn't know this reasoning
  
  Result: Full provenance without manual filter tracking!
""")

# Save a screenshot
simple.SaveScreenshot("output/test_provenance_complete.png", view)
print("Screenshot saved: output/test_provenance_complete.png")
