#!/usr/bin/env python
"""
Debug Catalyst Live connection - very verbose.
"""
import sys
import time
import pathlib
_repo_src = pathlib.Path(__file__).parent.parent.parent / 'src'
if _repo_src.exists():
    sys.path.insert(0, str(_repo_src))

from paraview import simple, servermanager

print("=== Catalyst Live Debug ===")
print()

# Get process module info
pm = servermanager.vtkProcessModule.GetProcessModule()
print(f"Process ID: {pm.GetPartitionId()}")
print(f"Number of processes: {pm.GetNumberOfLocalPartitions()}")
print()

print("Attempting to create Live connection...")
print("(This will listen on port 22222)")
print()

try:
    link = servermanager.ConnectToCatalyst("localhost", 22222)
    print(f"Link created: {link}")
    print(f"Link class: {link.GetClassName()}")
    
    # Try to initialize
    print("\nInitializing link...")
    link.InvokeCommand('Initialize')
    print("Initialize called")
    
    print("\nNow start simulation in another terminal:")
    print("  cd /path/to/catalyst-examples/ParaView/PythonSteering")
    print("  export PYTHONPATH=/path/to/catalyst_build/lib/pythonX.Y/site-packages:$PYTHONPATH")
    print("  pvpython fedriver_simple.py catalyst_pipeline_live_simple.py")
    print()
    
    # Process events in a loop
    nam = pm.GetNetworkAccessManager()
    
    for i in range(600):  # 60 seconds
        # Process network events
        result = nam.ProcessEvents(100)  # 100ms
        
        # Check for sources
        sources = simple.GetSources()
        if sources:
            print(f"\n[{i}] Sources found: {list(sources.keys())}")
            for (name, _id), proxy in sources.items():
                try:
                    info = proxy.GetDataInformation()
                    print(f"  {name}: {info.GetDataClassName()}, {info.GetNumberOfPoints()} pts")
                except:
                    print(f"  {name}: (no data info)")
        
        if i % 10 == 0:
            print(f"[{i}] Waiting... (ProcessEvents returned: {result})")
        
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nStopped by user")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
