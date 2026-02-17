"""
Tests for trame-cfd-mcp that don't require ParaView.

These tests verify module structure, imports, and non-ParaView functionality.

Run with:
    python3 tests/test_core.py
    
Or with pytest (if installed):
    python3 -m pytest tests/test_core.py -v
"""

import sys
import json
import importlib.util
from pathlib import Path


def load_module_directly(module_name: str, file_path: str):
    """Load a module directly without triggering package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_line_samplers():
    """Test line sampler strategies (no ParaView needed)."""
    src_path = Path(__file__).parent.parent / "src" / "trame_cfd_mcp"
    line_samplers = load_module_directly('line_samplers', str(src_path / 'line_samplers.py'))
    
    UniformSampler = line_samplers.UniformSampler
    GeometricSampler = line_samplers.GeometricSampler
    BoundaryLayerSampler = line_samplers.BoundaryLayerSampler
    
    # Test uniform sampler
    sampler = UniformSampler(n_points=11)
    y_values = sampler.generate(probe_length=1.0)
    assert len(y_values) == 11, f"Expected 11 points, got {len(y_values)}"
    assert abs(y_values[0]) < 1e-10, "First point should be at 0"
    assert abs(y_values[-1] - 1.0) < 1e-10, "Last point should be at 1.0"
    print(f"✓ UniformSampler: {len(y_values)} points, range [{y_values[0]:.2f}, {y_values[-1]:.2f}]")
    
    # Test geometric sampler - points should be denser near start
    sampler = GeometricSampler(first_spacing=0.01, growth_ratio=1.2)
    y_values = sampler.generate(probe_length=1.0)
    assert len(y_values) > 5, f"Expected >5 points, got {len(y_values)}"
    spacing_first = y_values[1] - y_values[0]
    spacing_last = y_values[-1] - y_values[-2]
    assert spacing_first < spacing_last, "Geometric sampler should have increasing spacing"
    print(f"✓ GeometricSampler: {len(y_values)} points, first spacing {spacing_first:.4f} < last spacing {spacing_last:.4f}")
    
    # Test boundary layer sampler - should cluster near wall
    sampler = BoundaryLayerSampler(wall_spacing=0.01)
    y_values = sampler.generate(probe_length=1.0)
    assert len(y_values) > 10, f"Expected >10 points, got {len(y_values)}"
    near_wall_count = sum(1 for y in y_values if y < 0.2)
    assert near_wall_count > len(y_values) * 0.3, "BL sampler should have many points in near-wall region"
    print(f"✓ BoundaryLayerSampler: {len(y_values)} points, {near_wall_count} in near-wall region (<0.2)")


def test_ontology():
    """Test ontology JSON file."""
    ontology_path = Path(__file__).parent.parent / "src" / "trame_cfd_mcp" / "ontology.json"
    
    assert ontology_path.exists(), f"Ontology file not found at {ontology_path}"
    
    with open(ontology_path) as f:
        data = json.load(f)
    
    assert isinstance(data, dict), "Ontology should be a dict"
    assert len(data) > 0, "Ontology should not be empty"
    print(f"✓ Ontology: {len(data)} top-level keys")


def test_catalyst_live_syntax():
    """Test that catalyst_live.py has valid syntax."""
    src_path = Path(__file__).parent.parent / "src" / "trame_cfd_mcp" / "catalyst_live.py"
    
    import py_compile
    try:
        py_compile.compile(str(src_path), doraise=True)
        print("✓ catalyst_live.py: Valid syntax")
    except py_compile.PyCompileError as e:
        raise AssertionError(f"Syntax error in catalyst_live.py: {e}")


def run_all_tests():
    """Run all tests."""
    print("Running trame-cfd-mcp core tests (no ParaView required)\n")
    
    test_line_samplers()
    test_ontology()
    test_catalyst_live_syntax()
    
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    run_all_tests()
