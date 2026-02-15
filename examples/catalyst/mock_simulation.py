#!/usr/bin/env python
"""
Mock CFD simulation that sends residual data via Catalyst.

This demonstrates how to send monitor data that can be charted
in real-time by ParaView/cfd_chat_live.py.

Usage:
    # Terminal 1: Start this mock simulation
    export CATALYST_IMPLEMENTATION_PATHS=/path/to/paraview/lib/catalyst
    export CATALYST_IMPLEMENTATION_NAME=paraview
    python mock_simulation.py catalyst_pipeline_monitors.py
    
    # Terminal 2: Connect with ParaView
    pvpython ../cfd_assistant/cfd_chat_live.py --host localhost --port 22222
"""

import sys
import time
import math
import numpy as np

# Try to import Catalyst
try:
    import catalyst
    import catalyst_conduit as conduit
    HAS_CATALYST = True
except ImportError:
    print("Warning: catalyst module not found. Running in demo mode.")
    print("To use real Catalyst, ensure CATALYST_IMPLEMENTATION_PATHS is set.")
    HAS_CATALYST = False


class MockCFDSolver:
    """
    Simulates a CFD solver with convergence history.
    """
    
    def __init__(self, max_iterations=1000):
        self.max_iterations = max_iterations
        self.current_iteration = 0
        self.dt = 0.001
        
        # Residual history (pre-allocate)
        self.iterations = np.zeros(max_iterations, dtype=np.float32)
        self.time_history = np.zeros(max_iterations, dtype=np.float32)
        self.residual_continuity = np.zeros(max_iterations, dtype=np.float32)
        self.residual_momentum = np.zeros(max_iterations, dtype=np.float32)
        self.residual_energy = np.zeros(max_iterations, dtype=np.float32)
        
        # Force history
        self.drag = np.zeros(max_iterations, dtype=np.float32)
        self.lift = np.zeros(max_iterations, dtype=np.float32)
        
        # Initial residuals (high)
        self._base_residual = 1e-1
    
    def step(self):
        """Advance one iteration."""
        if self.current_iteration >= self.max_iterations:
            return False
        
        i = self.current_iteration
        t = i * self.dt
        
        # Store iteration/time
        self.iterations[i] = float(i)
        self.time_history[i] = t
        
        # Simulate residual convergence (exponential decay with noise)
        decay_rate = 0.02
        noise = 0.1 * np.random.randn()
        
        self.residual_continuity[i] = self._base_residual * math.exp(-decay_rate * i) * (1 + noise)
        self.residual_momentum[i] = self._base_residual * math.exp(-decay_rate * 0.8 * i) * (1 + noise * 0.5)
        self.residual_energy[i] = self._base_residual * math.exp(-decay_rate * 0.6 * i) * (1 + noise * 0.3)
        
        # Simulate force convergence (asymptotic approach with oscillation)
        self.drag[i] = 0.025 + 0.01 * math.exp(-0.01 * i) * math.sin(0.1 * i)
        self.lift[i] = 0.35 + 0.05 * math.exp(-0.01 * i) * math.cos(0.1 * i)
        
        self.current_iteration += 1
        return True
    
    def get_time(self):
        return self.current_iteration * self.dt


def create_monitor_node(solver):
    """
    Create a Conduit node with monitor data.
    
    LIGHTWEIGHT MODE: Send only current iteration's values.
    The pipeline script accumulates history.
    """
    node = conduit.Node()
    
    n = solver.current_iteration
    if n == 0:
        return node
    
    # State info
    node["catalyst/state/timestep"] = solver.current_iteration
    node["catalyst/state/time"] = solver.get_time()
    
    # Monitor channel as a single-row table with named columns
    # The pipeline script accumulates rows over time
    monitors = node["catalyst/channels/monitors"]
    monitors["type"] = "object"  # Not a mesh, tabular data
    
    # Table structure: columns with single values
    # Column names are self-describing - can change during simulation
    data = monitors["data"]
    data["num_rows"] = 1
    
    # Each column is a 1-element array
    cols = data["columns"]
    cols["iteration"].set(np.array([float(n)], dtype=np.float32))
    cols["residual_continuity"].set(np.array([solver.residual_continuity[n-1]], dtype=np.float32))
    cols["residual_momentum"].set(np.array([solver.residual_momentum[n-1]], dtype=np.float32))
    cols["residual_energy"].set(np.array([solver.residual_energy[n-1]], dtype=np.float32))
    cols["drag"].set(np.array([solver.drag[n-1]], dtype=np.float32))
    cols["lift"].set(np.array([solver.lift[n-1]], dtype=np.float32))
    
    return node


def create_monitor_node_full_history(solver):
    """
    Alternative: Send full history as a points mesh.
    
    Use this if you want ParaView to have complete history
    without accumulation in the pipeline script.
    More bandwidth but simpler pipeline.
    """
    node = conduit.Node()
    
    n = solver.current_iteration
    if n == 0:
        return node
    
    # State info
    node["catalyst/state/timestep"] = solver.current_iteration
    node["catalyst/state/time"] = solver.get_time()
    
    # Monitor channel as a points mesh
    monitors = node["catalyst/channels/monitors"]
    monitors["type"] = "mesh"
    
    # Coordset: iteration as x, residual as y
    coords = monitors["data/coordsets/coords"]
    coords["type"] = "explicit"
    coords["values/x"].set_external(solver.iterations[:n])
    coords["values/y"].set_external(solver.residual_continuity[:n])
    coords["values/z"].set(np.zeros(n, dtype=np.float32))
    
    # Topology: points
    topo = monitors["data/topologies/points"]
    topo["type"] = "points"
    topo["coordset"] = "coords"
    
    # Fields
    fields = monitors["data/fields"]
    
    fields["continuity/association"] = "vertex"
    fields["continuity/topology"] = "points"
    fields["continuity/values"].set_external(solver.residual_continuity[:n])
    
    fields["momentum/association"] = "vertex"
    fields["momentum/topology"] = "points"
    fields["momentum/values"].set_external(solver.residual_momentum[:n])
    
    fields["energy/association"] = "vertex"
    fields["energy/topology"] = "points"
    fields["energy/values"].set_external(solver.residual_energy[:n])
    
    fields["drag/association"] = "vertex"
    fields["drag/topology"] = "points"
    fields["drag/values"].set_external(solver.drag[:n])
    
    fields["lift/association"] = "vertex"
    fields["lift/topology"] = "points"
    fields["lift/values"].set_external(solver.lift[:n])
    
    return node


def run_simulation(pipeline_script, num_iterations=500, output_frequency=10):
    """
    Run the mock simulation with Catalyst.
    """
    print(f"Starting mock CFD simulation...")
    print(f"  Pipeline: {pipeline_script}")
    print(f"  Iterations: {num_iterations}")
    print(f"  Output frequency: every {output_frequency} iterations")
    print()
    
    solver = MockCFDSolver(max_iterations=num_iterations)
    
    if HAS_CATALYST:
        # Initialize Catalyst with the pipeline script
        node = conduit.Node()
        node["catalyst/scripts/script/filename"] = pipeline_script
        catalyst.initialize(node)
        print("Catalyst initialized.")
    else:
        print("Running without Catalyst (demo mode)")
    
    print("\nSimulation running... Connect ParaView to localhost:22222")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while solver.step():
            i = solver.current_iteration
            
            # Output at specified frequency
            if i % output_frequency == 0:
                if HAS_CATALYST:
                    node = create_monitor_node(solver)
                    catalyst.execute(node)
                
                # Print status
                print(f"Iter {i:5d}: "
                      f"res_cont={solver.residual_continuity[i-1]:.2e}, "
                      f"res_mom={solver.residual_momentum[i-1]:.2e}, "
                      f"Cd={solver.drag[i-1]:.4f}, "
                      f"Cl={solver.lift[i-1]:.4f}")
            
            # Simulate computation time
            time.sleep(0.05)
    
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")
    
    finally:
        if HAS_CATALYST:
            catalyst.finalize()
            print("Catalyst finalized.")
    
    print(f"\nSimulation complete. Final iteration: {solver.current_iteration}")
    return solver


def demo_mode():
    """Run without Catalyst - just print monitor data."""
    print("Running in demo mode (no Catalyst)")
    print("This shows what data would be sent.\n")
    
    solver = MockCFDSolver(max_iterations=100)
    
    for _ in range(100):
        solver.step()
        if solver.current_iteration % 10 == 0:
            i = solver.current_iteration - 1
            print(f"Iter {solver.current_iteration:3d}: "
                  f"res={solver.residual_continuity[i]:.2e}, "
                  f"Cd={solver.drag[i]:.4f}")
            time.sleep(0.1)
    
    print("\nDemo complete.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pipeline_script = sys.argv[1]
        num_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        run_simulation(pipeline_script, num_iterations)
    else:
        demo_mode()
