"""
Better CFD visualization with proper camera angle
"""
from paraview import simple

# Load data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

print("=" * 60)
print("CFD Visualization")
print("=" * 60)

# Get bounds
bounds = reader.GetDataInformation().GetBounds()
print(f"Data bounds: {bounds}")
center = [(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2]
print(f"Center: {center}")

# Create Gradient for Q criterion
print("\n[1] Creating Q criterion...")
grad = simple.Gradient(Input=reader)
grad.ScalarArray = ['POINTS', 'Velocity']
grad.ComputeQCriterion = 1
simple.UpdatePipeline()

# Create Q contour
print("[2] Creating Q isosurfaces (Q=100, 500, 1000)...")
contour = simple.Contour(Input=grad)
contour.ContourBy = ['POINTS', 'Q Criterion']
contour.Isosurfaces = [100, 500, 1000]
simple.UpdatePipeline()
simple.Show(contour)
simple.ColorBy(simple.GetDisplayProperties(contour), ('POINTS', 'Q Criterion'))

# Create velocity slice at center (YZ plane)
print("[3] Creating velocity slice...")
slice = simple.Slice(Input=reader)
slice.SliceType.Normal = [1, 0, 0]  # X normal = YZ plane
slice.SliceType.Origin = center
simple.UpdatePipeline()
simple.Show(slice)
simple.ColorBy(simple.GetDisplayProperties(slice), ('POINTS', 'Velocity'))

# Create pressure surface
print("[4] Creating pressure surface...")
surface = simple.ExtractSurface(Input=reader)
simple.UpdatePipeline()
simple.Show(surface)
simple.ColorBy(simple.GetDisplayProperties(surface), ('POINTS', 'p'))
# Make it slightly transparent
disp = simple.GetDisplayProperties(surface)
disp.Opacity = 0.3

# Hide original reader
simple.Hide(reader)
simple.Hide(grad)

# Setup camera - isometric view
print("[5] Setting camera...")
view = simple.GetActiveViewOrCreate('RenderView')
view.CameraPosition = [center[0] + 20, center[1] + 10, center[2] + 15]
view.CameraFocalPoint = center
view.CameraViewUp = [0, 1, 0]

# Render
simple.Render()

# Save
print("\n[6] Saving screenshot...")
simple.SaveScreenshot("output/cfd_viz.png", ImageResolution=[1920, 1080])
print("Saved to output/cfd_viz.png")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
