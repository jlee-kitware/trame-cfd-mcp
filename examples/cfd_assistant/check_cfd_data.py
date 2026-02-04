"""
Test with real CFD data: test.vtm
"""
from paraview import simple

print("=" * 60)
print("Loading CFD Data: test.vtm")
print("=" * 60)

# Load the data
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()
simple.SetActiveSource(reader)

print(f"\n[1] Reader type: {type(reader).__name__}")

# Get data info
info = reader.GetDataInformation()
print(f"[2] Data type: {info.GetDataClassName()}")
print(f"[3] Bounds: {info.GetBounds()}")

# Check fields
print("\n[4] Point Data Arrays:")
point_data = reader.GetPointDataInformation()
for i in range(point_data.GetNumberOfArrays()):
    arr = point_data.GetArray(i)
    print(f"    {arr.GetName()}: {arr.GetNumberOfComponents()} components, range={arr.GetRange()}")

print("\n[5] Cell Data Arrays:")
cell_data = reader.GetCellDataInformation()
for i in range(cell_data.GetNumberOfArrays()):
    arr = cell_data.GetArray(i)
    print(f"    {arr.GetName()}: {arr.GetNumberOfComponents()} components, range={arr.GetRange()}")
