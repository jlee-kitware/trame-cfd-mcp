"""
Check fields in test.vtm
"""
from paraview import simple

reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()

print("Point Data Arrays:")
point_data = reader.GetPointDataInformation()
for i in range(point_data.GetNumberOfArrays()):
    arr = point_data.GetArray(i)
    print(f"  {arr.GetName()}: {arr.GetNumberOfComponents()} components, range={arr.GetRange()}")

print("\nCell Data Arrays:")
cell_data = reader.GetCellDataInformation()
for i in range(cell_data.GetNumberOfArrays()):
    arr = cell_data.GetArray(i)
    print(f"  {arr.GetName()}: {arr.GetNumberOfComponents()} components")
