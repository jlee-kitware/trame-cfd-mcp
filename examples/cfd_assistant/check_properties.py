"""
Debug: Check actual ParaView 6 property names
"""
from paraview import simple

print("=" * 60)
print("ParaView 6 Property Names")
print("=" * 60)

# Gradient filter
print("\n[1] Gradient filter properties:")
wavelet = simple.Wavelet()
simple.UpdatePipeline()
grad = simple.Gradient(Input=wavelet)
for prop in grad.ListProperties():
    print(f"    {prop}")

# Contour filter
print("\n[2] Contour filter properties:")
contour = simple.Contour(Input=wavelet)
for prop in contour.ListProperties():
    print(f"    {prop}")

# Slice filter
print("\n[3] Slice filter properties:")
slice = simple.Slice(Input=wavelet)
for prop in slice.ListProperties():
    print(f"    {prop}")

# Check SliceType sub-properties
print("\n[4] SliceType (implicit function) properties:")
print(f"    SliceType value: {slice.SliceType}")
print(f"    SliceType type: {type(slice.SliceType)}")
if hasattr(slice.SliceType, 'Normal'):
    print(f"    SliceType.Normal: {slice.SliceType.Normal}")
if hasattr(slice.SliceType, 'Origin'):
    print(f"    SliceType.Origin: {slice.SliceType.Origin}")
