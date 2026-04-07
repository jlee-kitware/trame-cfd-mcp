#!/usr/bin/env python
"""
Minimal Catalyst Live test - just ParaView without trame.

Usage:
    1. Start this script (it will listen for connections)
    2. Start the simulation in another terminal

This tests if Catalyst Live works at the ParaView level before
adding trame complexity.
"""
import sys
import time
import pathlib
_repo_src = pathlib.Path(__file__).parent.parent.parent / 'src'
if _repo_src.exists():
    sys.path.insert(0, str(_repo_src))

from paraview import simple
from paraview.live import ConnectToCatalyst, ExtractCatalystData, ProcessServerNotifications

print("Starting Catalyst Live listener...")
print("Waiting for simulation to connect on localhost:22222")
print("(Start simulation with: pvpython fedriver_simple.py catalyst_pipeline_live_simple.py)")
print()

# Connect (this starts listening)
link = ConnectToCatalyst("localhost", 22222)
print("Listening... Press Ctrl+C to stop")

try:
    while True:
        # Process incoming events
        ProcessServerNotifications()
        
        # Check for sources
        sources = simple.GetSources()
        if sources:
            print(f"Sources available: {list(sources.keys())}")
            
            # Try to extract grid data
            for (name, _id), proxy in sources.items():
                if 'grid' in name.lower():
                    info = proxy.GetDataInformation()
                    print(f"  {name}: {info.GetNumberOfPoints()} points, {info.GetNumberOfCells()} cells")
        
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping...")
