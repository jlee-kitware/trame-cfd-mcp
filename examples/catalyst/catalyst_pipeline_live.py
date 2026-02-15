"""
Example Catalyst Pipeline with Live Visualization enabled.

This script is passed to the simulation at runtime:
    ./my_simulation catalyst_pipeline_live.py

Or with the --enable-live flag:
    ./my_simulation catalyst_pipeline_with_rendering.py --enable-live
"""

# ============================================================================
# For Catalyst V2 (Modern - ParaView 5.9+)
# ============================================================================

from paraview.catalyst import Options

# Options control Live connection
options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"  # ParaView connects here

# Scripts can define catalyst_execute or use extractors
# The data from simulation channels is automatically available


# ============================================================================
# Alternatively, use paraview.catalyst.bridge for more control
# ============================================================================

# from paraview.catalyst import bridge
# 
# @bridge.coprocess
# def catalyst_execute(info):
#     """Called each timestep by the simulation."""
#     from paraview import simple
#     
#     # Get the data from the simulation (named channel "input")
#     producer = simple.TrivialProducer(registrationName="input")
#     
#     # Optional: add visualization pipeline
#     contour = simple.Contour(Input=producer)
#     contour.ContourBy = ['POINTS', 'velocity']
#     contour.Isosurfaces = [0.5]


# ============================================================================  
# For Catalyst V1 (Legacy - ParaView < 5.9)
# ============================================================================

# from paraview import coprocessing
# 
# def CreateCoProcessor():
#     coprocessor = coprocessing.CoProcessor()
#     coprocessor.EnableLive(True, 22222)  # Enable Live on port 22222
#     coprocessor.SetUpdateFrequencies({'input': [1]})  # Every timestep
#     return coprocessor
#
# def RequestDataDescription(datadescription):
#     datadescription.GetInputDescriptionByName('input').AllFieldsOn()
#     datadescription.GetInputDescriptionByName('input').GenerateMeshOn()
#
# def DoCoProcess(datadescription):
#     coprocessor.UpdateProducers(datadescription)
