#!/usr/bin/env python
"""
Mock CFD simulation that sends residual data via Catalyst (ParaView bridge).

This version uses paraview.catalyst.bridge which works with pvpython.

Usage:
    /path/to/pvpython mock_simulation_pv.py [num_iterations]
    
Then in another terminal:
    /path/to/pvpython ../cfd_assistant/cfd_chat.py --live
"""

import sys
import time
import math
import numpy as np

from paraview.catalyst import bridge
from paraview import simple
import vtk


class MockCFDSolver:
    """Simulates a CFD solver with convergence history."""
    
    def __init__(self, max_iterations=1000):
        self.max_iterations = max_iterations
        self.current_iteration = 0
        self.dt = 0.001
        
        # Residual history
        self.iterations = np.zeros(max_iterations, dtype=np.float64)
        self.residual_continuity = np.zeros(max_iterations, dtype=np.float64)
        self.residual_momentum = np.zeros(max_iterations, dtype=np.float64)
        self.residual_energy = np.zeros(max_iterations, dtype=np.float64)
        self.drag = np.zeros(max_iterations, dtype=np.float64)
        self.lift = np.zeros(max_iterations, dtype=np.float64)
        
        self._base_residual = 1e-1
    
    def step(self):
        if self.current_iteration >= self.max_iterations:
            return False
        
        i = self.current_iteration
        
        self.iterations[i] = float(i)
        
        # Simulate convergence
        decay = 0.02
        noise = 0.1 * np.random.randn()
        
        self.residual_continuity[i] = self._base_residual * math.exp(-decay * i) * (1 + noise)
        self.residual_momentum[i] = self._base_residual * math.exp(-decay * 0.8 * i) * (1 + noise * 0.5)
        self.residual_energy[i] = self._base_residual * math.exp(-decay * 0.6 * i) * (1 + noise * 0.3)
        
        self.drag[i] = 0.025 + 0.01 * math.exp(-0.01 * i) * math.sin(0.1 * i)
        self.lift[i] = 0.35 + 0.05 * math.exp(-0.01 * i) * math.cos(0.1 * i)
        
        self.current_iteration += 1
        return True
    
    def get_time(self):
        return self.current_iteration * self.dt


def create_vtk_dataset(solver):
    """
    Create a vtkPolyData with monitor history as points.
    
    Each point represents one iteration, with point data arrays
    for residuals and forces.
    """
    n = solver.current_iteration
    if n == 0:
        return None
    
    # Create points (one per iteration)
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(n)
    for i in range(n):
        # x = iteration, y = 0, z = 0
        points.SetPoint(i, solver.iterations[i], 0.0, 0.0)
    
    # Create polydata with vertices
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    
    # Create vertex cells
    verts = vtk.vtkCellArray()
    for i in range(n):
        verts.InsertNextCell(1)
        verts.InsertCellPoint(i)
    polydata.SetVerts(verts)
    
    # Add field arrays
    def add_array(name, data):
        arr = vtk.vtkDoubleArray()
        arr.SetName(name)
        arr.SetNumberOfTuples(n)
        for i in range(n):
            arr.SetValue(i, data[i])
        polydata.GetPointData().AddArray(arr)
    
    add_array("iteration", solver.iterations[:n])
    add_array("residual_continuity", solver.residual_continuity[:n])
    add_array("residual_momentum", solver.residual_momentum[:n])
    add_array("residual_energy", solver.residual_energy[:n])
    add_array("drag", solver.drag[:n])
    add_array("lift", solver.lift[:n])
    
    return polydata


def run_simulation(num_iterations=500, output_frequency=10):
    """Run simulation with Catalyst bridge."""
    
    print(f"Starting mock CFD simulation (ParaView bridge)...")
    print(f"  Iterations: {num_iterations}")
    print(f"  Output frequency: every {output_frequency} iterations")
    print()
    
    solver = MockCFDSolver(max_iterations=num_iterations)
    
    # Initialize bridge
    bridge.initialize()
    print("Catalyst bridge initialized.")
    print("\nSimulation running... Connect ParaView to localhost:22222")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while solver.step():
            i = solver.current_iteration
            
            if i % output_frequency == 0:
                # Create VTK dataset
                dataset = create_vtk_dataset(solver)
                
                if dataset:
                    # Send to Catalyst
                    bridge.coprocess(
                        time=solver.get_time(),
                        timestep=i,
                        dataset=dataset,
                        name="monitors"
                    )
                
                print(f"Iter {i:5d}: "
                      f"res_cont={solver.residual_continuity[i-1]:.2e}, "
                      f"Cd={solver.drag[i-1]:.4f}")
            
            time.sleep(0.05)
    
    except KeyboardInterrupt:
        print("\nSimulation interrupted.")
    
    finally:
        bridge.finalize()
        print("Catalyst finalized.")
    
    print(f"\nComplete. Final iteration: {solver.current_iteration}")


if __name__ == "__main__":
    num_iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    run_simulation(num_iterations)
