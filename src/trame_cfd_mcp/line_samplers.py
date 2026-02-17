"""
Line Samplers - Modular sampling strategies for line probes.

Provides different sampling distributions for probing flow fields along lines,
particularly useful for boundary layer analysis where dense near-wall sampling
is needed.

Usage:
    from trame_cfd_mcp.line_samplers import GeometricSampler, UniformSampler
    
    sampler = GeometricSampler(first_spacing=0.0001, growth_ratio=1.2)
    y_values = sampler.generate(probe_length=0.1)
"""

from abc import ABC, abstractmethod
import numpy as np

# Optional ParaView import - only needed for create_probe_line()
try:
    from paraview import simple
    PARAVIEW_AVAILABLE = True
except ImportError:
    PARAVIEW_AVAILABLE = False


class LineSampler(ABC):
    """Base class for line sampling strategies."""
    
    @abstractmethod
    def generate(self, probe_length: float) -> np.ndarray:
        """
        Generate sample positions along a line.
        
        Args:
            probe_length: Total length of the probe line
            
        Returns:
            Array of positions (arc lengths from start)
        """
        pass
    
    def sample_line(self, data_proxy, start_point: np.ndarray, 
                    direction: np.ndarray, probe_length: float,
                    field_name: str = "Velocity") -> dict:
        """
        Sample a field along a line using this sampler's distribution.
        
        Requires ParaView.
        
        Args:
            data_proxy: ParaView data proxy to sample from
            start_point: Starting point (3D coordinates)
            direction: Unit direction vector
            probe_length: Length of probe line
            field_name: Name of field to sample
            
        Returns:
            Dict with 'y' (arc lengths), 'values' (sampled field values),
            'points' (3D coordinates of sample points)
        """
        if not PARAVIEW_AVAILABLE:
            return {"error": "ParaView not available"}
        
        from vtk.util.numpy_support import vtk_to_numpy
        import vtk
        
        # Generate sample positions
        y_values = self.generate(probe_length)
        n_points = len(y_values)
        
        if n_points == 0:
            return {"error": "No sample points generated"}
        
        # Create points along the line
        points_3d = np.array([start_point + y * direction for y in y_values])
        
        # Create VTK polydata for the sample line
        vtk_points = vtk.vtkPoints()
        for pt in points_3d:
            vtk_points.InsertNextPoint(pt[0], pt[1], pt[2])
        
        # Create a polyline connecting the points
        polyline = vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(n_points)
        for i in range(n_points):
            polyline.GetPointIds().SetId(i, i)
        
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(polyline)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(vtk_points)
        polydata.SetLines(cells)
        
        # Wrap in TrivialProducer to use with ParaView
        producer = simple.TrivialProducer(registrationName="SampleLine")
        producer.GetClientSideObject().SetOutput(polydata)
        simple.UpdatePipeline(proxy=producer)
        
        # Resample the data onto our custom line
        resampled = simple.ResampleWithDataset(
            SourceDataArrays=data_proxy,
            DestinationMesh=producer
        )
        simple.UpdatePipeline(proxy=resampled)
        
        # Extract the sampled values
        resampled_data = resampled.GetClientSideObject().GetOutputDataObject(0)
        
        field_array = resampled_data.GetPointData().GetArray(field_name)
        if field_array is None:
            simple.Delete(resampled)
            simple.Delete(producer)
            return {"error": f"Field '{field_name}' not found in resampled data"}
        
        values = vtk_to_numpy(field_array)
        
        # Cleanup
        simple.Delete(resampled)
        simple.Delete(producer)
        
        return {
            "y": y_values,
            "values": values,
            "points": points_3d,
            "n_points": n_points
        }


class UniformSampler(LineSampler):
    """Uniform spacing along the line."""
    
    def __init__(self, n_points: int = 200):
        """
        Args:
            n_points: Number of sample points
        """
        self.n_points = n_points
    
    def generate(self, probe_length: float) -> np.ndarray:
        return np.linspace(0, probe_length, self.n_points)


class GeometricSampler(LineSampler):
    """
    Geometric progression - dense near start, coarser further out.
    
    Ideal for boundary layer sampling where gradients are steepest near the wall.
    """
    
    def __init__(self, first_spacing: float = 0.0001, growth_ratio: float = 1.15,
                 max_points: int = 100):
        """
        Args:
            first_spacing: Distance to first sample point from wall
            growth_ratio: Ratio between successive spacings (>1 for growing)
            max_points: Maximum number of points to generate
        """
        self.first_spacing = first_spacing
        self.growth_ratio = growth_ratio
        self.max_points = max_points
    
    def generate(self, probe_length: float) -> np.ndarray:
        positions = [0.0]  # Start at wall
        
        spacing = self.first_spacing
        y = spacing
        
        while y < probe_length and len(positions) < self.max_points:
            positions.append(y)
            spacing *= self.growth_ratio
            y += spacing
        
        # Add the endpoint if not already close
        if positions[-1] < probe_length * 0.99:
            positions.append(probe_length)
        
        return np.array(positions)


class TanhSampler(LineSampler):
    """
    Hyperbolic tangent stretching - smooth transition from dense to coarse.
    
    Common in CFD mesh generation for boundary layer grids.
    """
    
    def __init__(self, n_points: int = 50, stretch_factor: float = 2.0):
        """
        Args:
            n_points: Number of sample points
            stretch_factor: Controls clustering near wall (higher = more clustering)
        """
        self.n_points = n_points
        self.stretch_factor = stretch_factor
    
    def generate(self, probe_length: float) -> np.ndarray:
        # Uniform distribution in computational space
        eta = np.linspace(0, 1, self.n_points)
        
        # Tanh stretching
        beta = self.stretch_factor
        y_normalized = np.tanh(beta * eta) / np.tanh(beta)
        
        return y_normalized * probe_length


class BoundaryLayerSampler(LineSampler):
    """
    Adaptive sampler optimized for boundary layer profiles.
    
    Uses geometric progression near wall, then transitions to coarser
    sampling in the freestream region.
    """
    
    def __init__(self, wall_spacing: float = 0.0001, 
                 bl_growth: float = 1.1,
                 outer_growth: float = 1.3,
                 transition_fraction: float = 0.3,
                 max_points: int = 80):
        """
        Args:
            wall_spacing: First cell height near wall
            bl_growth: Growth ratio in boundary layer region
            outer_growth: Growth ratio in outer/freestream region
            transition_fraction: Fraction of probe length for BL region
            max_points: Maximum number of points
        """
        self.wall_spacing = wall_spacing
        self.bl_growth = bl_growth
        self.outer_growth = outer_growth
        self.transition_fraction = transition_fraction
        self.max_points = max_points
    
    def generate(self, probe_length: float) -> np.ndarray:
        positions = [0.0]
        transition_y = probe_length * self.transition_fraction
        
        # Boundary layer region - fine geometric growth
        spacing = self.wall_spacing
        y = spacing
        
        while y < transition_y and len(positions) < self.max_points // 2:
            positions.append(y)
            spacing *= self.bl_growth
            y += spacing
        
        # Outer region - coarser geometric growth
        while y < probe_length and len(positions) < self.max_points:
            positions.append(y)
            spacing *= self.outer_growth
            y += spacing
        
        # Ensure endpoint
        if positions[-1] < probe_length * 0.95:
            positions.append(probe_length)
        
        return np.array(positions)


# Default sampler for boundary layer analysis
DEFAULT_BL_SAMPLER = BoundaryLayerSampler()
