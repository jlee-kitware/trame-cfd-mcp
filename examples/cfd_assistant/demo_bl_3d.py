#!/usr/bin/env python
"""
Demo: Boundary Layer Analysis with 3D Visualization

Shows velocity slice through the span station with probe locations
colored by shape factor (H) to indicate flow state.
"""
import sys
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')

from paraview import simple
from trame_cfd_mcp.cfd_analysis import CFDAnalysis

# Load data
reader = simple.OpenDataFile('test.vtm')
simple.UpdatePipeline()

# Setup view
view = simple.CreateRenderView()
view.ViewSize = [1600, 900]
view.Background = [0.1, 0.1, 0.12]
view.OrientationAxesVisibility = 0
simple.SetActiveView(view)

analysis = CFDAnalysis()

# Step 1: Get boundary layer data at multiple locations
print("Analyzing boundary layer...")
probe_data = []
for xc in [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
    r = analysis.compute_boundary_layer_profile(x_over_chord=xc, span_fraction=0.5)
    if 'error' not in r:
        probe_data.append(r)
        status = 'SEPARATION' if r['shape_factor'] > 4 else ('laminar' if r['shape_factor'] > 2.2 else 'turbulent')
        print(f"  x/c={r['x_over_chord']:.2f}: H={r['shape_factor']:.1f} ({status})")

span_y = probe_data[0]['span_absolute']

# Step 2: Create velocity slice at span station, clipped to body region
print(f"\nCreating velocity slice at y={span_y:.3f} (50% span)...")
merge = simple.MergeBlocks(Input=reader)
simple.UpdatePipeline(proxy=merge)

slice_filter = simple.Slice(Input=merge)
slice_filter.SliceType = 'Plane'
slice_filter.SliceType.Origin = [0.5, span_y, 0.0]
slice_filter.SliceType.Normal = [0, 1, 0]
simple.UpdatePipeline(proxy=slice_filter)

# Clip to body region (remove farfield)
clip = simple.Clip(Input=slice_filter)
clip.ClipType = 'Box'
clip.ClipType.Position = [0.15, span_y - 0.01, -0.12]
clip.ClipType.Length = [0.85, 0.02, 0.24]
clip.Invert = 1  # Keep inside
simple.UpdatePipeline(proxy=clip)

# Show clipped slice with velocity coloring
clip_display = simple.Show(clip, view)
simple.ColorBy(clip_display, ('POINTS', 'Velocity', 'Magnitude'))

vel_lut = simple.GetColorTransferFunction('Velocity')
vel_lut.ApplyPreset('Jet', True)
vel_lut.RescaleTransferFunction(0.0, 0.95)

clip_display.SetScalarBarVisibility(view, True)
cb = simple.GetScalarBar(vel_lut, view)
cb.Title = 'Velocity'
cb.TitleFontSize = 20
cb.LabelFontSize = 16

# Step 3: Add probe location markers
print("\nAdding probe markers...")
for i, p in enumerate(probe_data):
    pt = p['surface_point']
    norm = p['surface_normal']
    H = p['shape_factor']
    delta = p['delta']
    
    # Create line from surface along normal (length = 4x delta for visibility)
    line = simple.Line()
    line.Point1 = [pt[0], span_y, pt[2]]
    end_pt = [pt[0] + delta * 4 * norm[0], span_y, pt[2] + delta * 4 * norm[2]]
    line.Point2 = end_pt
    simple.UpdatePipeline(proxy=line)
    
    tube = simple.Tube(Input=line)
    tube.Radius = 0.003
    simple.UpdatePipeline(proxy=tube)
    
    display = simple.Show(tube, view)
    
    # Color by flow state
    if H > 3.5:
        display.DiffuseColor = [1.0, 0.2, 0.2]  # Red - separation
    elif H > 2.0:
        display.DiffuseColor = [1.0, 0.6, 0.2]  # Orange - transitional/laminar
    else:
        display.DiffuseColor = [0.2, 0.5, 1.0]  # Blue - turbulent

# Step 4: Set camera - view from front-side to see suction surface and all probes
view.CameraPosition = [0.0, span_y - 0.4, 0.15]
view.CameraFocalPoint = [0.5, span_y, 0.02]
view.CameraViewUp = [0, 0, 1]

simple.Render(view)
simple.SaveScreenshot('output/demo_bl_3d.png', view)
print("\nSaved output/demo_bl_3d.png")

print("""
Legend:
  Red probes   = separation (H > 3.5)
  Orange probes = transitional/laminar (2.0 < H < 3.5)  
  Blue probes  = turbulent (H < 2.0)
  
Velocity colormap shows flow field:
  Blue  = low velocity (stagnation, boundary layer)
  Green/Yellow = moderate-high velocity
  Red   = freestream velocity
""")
