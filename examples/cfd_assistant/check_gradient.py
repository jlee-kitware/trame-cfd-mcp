"""
Debug: Check Gradient filter vector input
"""
from paraview import simple

wavelet = simple.Wavelet()
simple.UpdatePipeline()

# Add a vector field
calc = simple.Calculator(Input=wavelet)
calc.Function = 'coords'
calc.ResultArrayName = 'U'
simple.UpdatePipeline()

# Now create gradient on that
grad = simple.Gradient(Input=calc)

print("Gradient properties and values:")
for prop in grad.ListProperties():
    try:
        val = getattr(grad, prop)
        if hasattr(val, 'GetData'):
            val = val.GetData()
        print(f"    {prop}: {val}")
    except:
        print(f"    {prop}: <error reading>")

# Check if ScalarArray is how we select the input
print("\n\nScalarArray details:")
print(f"  Value: {grad.ScalarArray}")
print(f"  Type: {type(grad.ScalarArray)}")

# Try setting it
print("\n\nAvailable arrays on input:")
info = calc.GetPointDataInformation()
for i in range(info.GetNumberOfArrays()):
    arr = info.GetArray(i)
    print(f"  {arr.GetName()}: {arr.GetNumberOfComponents()} components")
