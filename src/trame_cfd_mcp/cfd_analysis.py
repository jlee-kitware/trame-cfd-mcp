"""
CFD Analysis - Domain-specific analysis functions for CFD visualization.

Provides CFD analysis methods used by WorkflowMCP workflows.
Not intended for direct LLM use - use WorkflowMCP instead.

Methods include:
- Vortex field computation (Q-criterion, vorticity, lambda2)
- Wake detection
- Force computation and distribution
- Field statistics and histograms
- Streamline seed computation
"""

from paraview import simple
import numpy as np
import json
from pathlib import Path


# Semantic field type patterns for field resolution
FIELD_TYPE_PATTERNS = {
    "velocity": ["velocity", "vel", "u", "v", "w", "U"],
    "pressure": ["pressure", "p", "P", "press"],
    "density": ["density", "rho", "Density"],
    "temperature": ["temperature", "temp", "T", "Temperature"],
    "mach": ["mach", "Mach", "Ma"],
    "turbulent_kinetic_energy": ["tke", "k", "TurbulentKineticEnergy", "TKE"],
}


class CFDAnalysis:
    """CFD analysis functions for ParaView visualization workflows."""
    
    def __init__(self):
        self._chart_view_queue = []
        self._body_bounds_cache = {}
    
    def _resolve_field_type(self, field_type: str, proxy) -> str:
        """
        Resolve a semantic field type to actual field name in the data.
        
        Args:
            field_type: Semantic type like "velocity", "pressure", or actual field name
            proxy: ParaView proxy to search for fields
            
        Returns:
            Actual field name found in proxy, or field_type if not a semantic type
        """
        # If it's not a known semantic type, assume it's already a field name
        if field_type not in FIELD_TYPE_PATTERNS:
            return field_type
        
        patterns = FIELD_TYPE_PATTERNS[field_type]
        
        # Get available fields from proxy
        data = proxy.GetClientSideObject().GetOutputDataObject(0)
        
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            block = data.GetBlock(0)
            while block and block.IsA("vtkMultiBlockDataSet"):
                block = block.GetBlock(0)
            if block:
                data = block
        
        # Collect all field names
        all_fields = []
        for data_arrays in [data.GetPointData(), data.GetCellData()]:
            for i in range(data_arrays.GetNumberOfArrays()):
                all_fields.append(data_arrays.GetArrayName(i))
        
        # First pass: exact match (case-insensitive)
        for name in all_fields:
            name_lower = name.lower()
            for pattern in patterns:
                if pattern.lower() == name_lower:
                    return name
        
        # Second pass: pattern is a substring, but only for longer patterns (avoid "u" matching "Turbulence")
        for name in all_fields:
            name_lower = name.lower()
            for pattern in patterns:
                # Only use substring matching for patterns >= 3 chars
                if len(pattern) >= 3 and pattern.lower() in name_lower:
                    return name
        
        # Fallback: return first pattern as best guess
        return patterns[0]
    
    def _get_leaf_data(self, data):
        """
        Get first leaf dataset from potentially nested multiblock data.
        
        Args:
            data: VTK data object (may be multiblock)
            
        Returns:
            First non-multiblock dataset found, or None
        """
        if data is None:
            return None
            
        # If not multiblock, return as-is
        if not data.IsA("vtkMultiBlockDataSet"):
            return data
        
        # Recursively search blocks
        n_blocks = data.GetNumberOfBlocks()
        for i in range(n_blocks):
            block = data.GetBlock(i)
            if block is not None:
                result = self._get_leaf_data(block)
                if result is not None:
                    return result
        
        return None
    
    def _get_available_fields(self, proxy) -> dict:
        """
        Get available fields and their types from proxy.
        
        Returns:
            Dict mapping semantic type to actual field name, plus all field names
        """
        data = proxy.GetClientSideObject().GetOutputDataObject(0)
        
        # Handle multiblock - get first leaf
        data = self._get_leaf_data(data)
        
        if data is None:
            return {"all_fields": [], "resolved": {}}
        
        result = {"all_fields": [], "resolved": {}}
        
        for data_arrays in [data.GetPointData(), data.GetCellData()]:
            for i in range(data_arrays.GetNumberOfArrays()):
                name = data_arrays.GetArrayName(i)
                result["all_fields"].append(name)
                
                # Try to match to semantic type
                name_lower = name.lower()
                for field_type, patterns in FIELD_TYPE_PATTERNS.items():
                    for pattern in patterns:
                        if pattern.lower() == name_lower or pattern.lower() in name_lower:
                            result["resolved"][field_type] = name
                            break
        
        return result
    
    def get_visibility_state(self) -> dict:
        """Get visibility state of all proxies in the current view."""
        view = simple.GetActiveView()
        if view is None:
            return {"error": "No active view"}
        
        result = {}
        for name, proxy in simple.GetSources().items():
            rep = simple.GetRepresentation(proxy, view)
            if rep:
                result[name[0]] = rep.Visibility == 1
            else:
                result[name[0]] = False
        return result
    
    # =========================================================================
    # DATA VALIDATION AND CHARACTERIZATION
    # =========================================================================
    
    def _get_body_bounds(self, proxy, clip_margin: float = 0.05):
        """
        Estimate body geometry bounds by clipping away farfield domain faces.
        
        Results are cached per proxy to avoid creating temporary filters on
        every call. Call _invalidate_body_bounds() if the data changes.
        
        Args:
            proxy: ParaView proxy for the data source
            clip_margin: Fraction of domain to clip inward (default 0.05 = 5%)
            
        Returns:
            Tuple of (body_bounds, body_diag) where body_bounds is (xmin,xmax,ymin,ymax,zmin,zmax)
        """
        # Check cache
        cache_key = id(proxy)
        if cache_key in self._body_bounds_cache:
            return self._body_bounds_cache[cache_key]
        
        domain_bounds = proxy.GetDataInformation().GetBounds()
        domain_diag = float(np.sqrt(
            (domain_bounds[1] - domain_bounds[0])**2 +
            (domain_bounds[3] - domain_bounds[2])**2 +
            (domain_bounds[5] - domain_bounds[4])**2
        ))
        
        original_source = simple.GetActiveSource()  # Save for restore
        surface = None
        clip = None
        try:
            # Extract external surface
            surface = simple.ExtractSurface(Input=proxy)
            simple.UpdatePipeline(proxy=surface)
            
            # Clip away farfield faces
            dx = (domain_bounds[1] - domain_bounds[0]) * clip_margin
            dy = (domain_bounds[3] - domain_bounds[2]) * clip_margin
            dz = (domain_bounds[5] - domain_bounds[4]) * clip_margin
            
            clip = simple.Clip(Input=surface)
            clip.ClipType = 'Box'
            clip.ClipType.Bounds = [
                domain_bounds[0] + dx, domain_bounds[1] - dx,
                domain_bounds[2] + dy, domain_bounds[3] - dy,
                domain_bounds[4] + dz, domain_bounds[5] - dz
            ]
            clip.Invert = 1
            simple.UpdatePipeline(proxy=clip)
            
            body_bounds = clip.GetDataInformation().GetBounds()
            
            # Sanity check — if clip produced nothing, fall back
            num_cells = clip.GetDataInformation().GetNumberOfCells()
            if num_cells == 0:
                result = (domain_bounds, domain_diag)
            else:
                body_diag = float(np.sqrt(
                    (body_bounds[1] - body_bounds[0])**2 +
                    (body_bounds[3] - body_bounds[2])**2 +
                    (body_bounds[5] - body_bounds[4])**2
                ))
                result = (body_bounds, body_diag)
            
            self._body_bounds_cache[cache_key] = result
            return result
            
        except Exception:
            result = (domain_bounds, domain_diag)
            self._body_bounds_cache[cache_key] = result
            return result
        finally:
            # Always clean up temporary filters — delete child before parent
            if clip is not None:
                try:
                    simple.Delete(clip)
                except:
                    pass
            if surface is not None:
                try:
                    simple.Delete(surface)
                except:
                    pass
            # Restore active source
            if original_source is not None:
                simple.SetActiveSource(original_source)
    
    def _invalidate_body_bounds(self):
        """Clear cached body bounds (call if data changes)."""
        self._body_bounds_cache.clear()

    def list_data(self) -> dict:
        """
        List all loaded data sources and filters in the pipeline.
        
        Call this FIRST to discover what data is available before performing
        any analysis or visualization. Returns the names of all proxies,
        distinguishing between data readers (sources) and filters.
        
        Returns:
            Dict with 'readers' (data sources) and 'filters' lists
        """
        readers = []
        filters = []
        
        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            proxy_type = proxy.GetXMLName()
            
            # Check if it's a reader (data source) or filter
            if 'Reader' in proxy_type or proxy_type in ['OpenDataFile', 'XMLMultiBlockDataReader', 
                'XMLUnstructuredGridReader', 'XMLPolyDataReader', 'LegacyVTKReader',
                'EnSightReader', 'PVDReader', 'CGNSReader', 'ExodusIIReader']:
                readers.append({"name": proxy_name, "type": proxy_type})
            else:
                filters.append({"name": proxy_name, "type": proxy_type})
        
        return {
            "readers": readers,
            "filters": filters,
            "active_source": simple.GetActiveSource().GetXMLName() if simple.GetActiveSource() else None
        }
    
    def characterize_dataset(self, proxy_name: str = None) -> dict:
        """
        Analyze CFD dataset to characterize simulation type and available physics.
        
        Call this FIRST when working with a new dataset to understand:
        - What type of CFD simulation (incompressible, compressible, turbulent, etc.)
        - What fields are available for analysis
        - What analysis tools are applicable
        - Recommended visualization approaches
        
        Args:
            proxy_name: Data source name, or None for active source
            
        Returns:
            Dict with simulation characteristics, available fields, and recommendations
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Get data object - handle multiblock
            raw_data = proxy.GetClientSideObject().GetOutputDataObject(0)
            data = self._get_leaf_data(raw_data)
            
            if data is None:
                return {"error": "No data found in dataset"}
            
            # Collect all arrays
            point_arrays = {}
            cell_arrays = {}
            
            pd = data.GetPointData()
            for i in range(pd.GetNumberOfArrays()):
                arr = pd.GetArray(i)
                name = arr.GetName()
                point_arrays[name] = {
                    "components": arr.GetNumberOfComponents(),
                    "range": [arr.GetRange(c) for c in range(arr.GetNumberOfComponents())]
                }
            
            cd = data.GetCellData()
            for i in range(cd.GetNumberOfArrays()):
                arr = cd.GetArray(i)
                name = arr.GetName()
                cell_arrays[name] = {
                    "components": arr.GetNumberOfComponents(),
                    "range": [arr.GetRange(c) for c in range(arr.GetNumberOfComponents())]
                }
            
            # Resolve semantic fields
            all_names = list(point_arrays.keys()) + list(cell_arrays.keys())
            resolved = {}
            for field_type, patterns in FIELD_TYPE_PATTERNS.items():
                for name in all_names:
                    name_lower = name.lower()
                    for pattern in patterns:
                        if pattern.lower() == name_lower or pattern.lower() in name_lower:
                            resolved[field_type] = name
                            break
                    if field_type in resolved:
                        break
            
            # Determine simulation characteristics
            characteristics = {
                "has_velocity": "velocity" in resolved,
                "has_pressure": "pressure" in resolved,
                "has_density": "density" in resolved,
                "has_temperature": "temperature" in resolved,
                "has_mach": "mach" in resolved,
                "has_turbulence": "turbulent_kinetic_energy" in resolved,
            }
            
            # Infer simulation type
            sim_type = "unknown"
            if characteristics["has_velocity"]:
                if characteristics["has_mach"] or characteristics["has_density"]:
                    sim_type = "compressible"
                else:
                    sim_type = "incompressible"
                    
                if characteristics["has_turbulence"]:
                    sim_type += "_turbulent"
                else:
                    sim_type += "_laminar_or_rans"
            
            # Check for velocity components (u, v, w separately)
            velocity_components = []
            for name in all_names:
                name_lower = name.lower()
                if name_lower in ['u', 'v', 'w'] or name in ['u', 'v', 'w']:
                    velocity_components.append(name)
            
            # Get geometry info
            bounds = data.GetBounds()
            num_points = data.GetNumberOfPoints()
            num_cells = data.GetNumberOfCells()
            
            # Recommendations based on available data
            recommendations = []
            applicable_tools = []
            
            if characteristics["has_velocity"]:
                recommendations.append("Velocity field available - can compute vorticity, Q-criterion, streamlines")
                applicable_tools.extend([
                    "compute_vortex_field",
                    "detect_wake_region",
                    "detect_streamwise_direction",
                    "find_minimum (stagnation points)",
                    "find_maximum (freestream velocity)"
                ])
            elif len(velocity_components) >= 3:
                recommendations.append(f"Velocity components found ({velocity_components}) - use ensure_velocity_vector to combine")
                
            if characteristics["has_pressure"]:
                recommendations.append("Pressure field available - can compute forces, Cp distribution")
                applicable_tools.extend([
                    "compute_forces",
                    "create_force_distribution_chart"
                ])
                
            if not characteristics["has_velocity"] and not velocity_components:
                recommendations.append("WARNING: No velocity field found - vortex/wake analysis not possible")
            
            return {
                "simulation_type": sim_type,
                "characteristics": characteristics,
                "resolved_fields": resolved,
                "velocity_components": velocity_components,
                "point_arrays": list(point_arrays.keys()),
                "cell_arrays": list(cell_arrays.keys()),
                "geometry": {
                    "bounds": list(bounds),
                    "num_points": num_points,
                    "num_cells": num_cells
                },
                "recommendations": recommendations,
                "applicable_tools": applicable_tools
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def get_geometry_info(self, proxy_name: str = None) -> dict:
        """
        Get geometric information about a dataset: bounds, center, and extents.
        
        Use this to determine where to position slices, clips, or other filters.
        For example, to create a slice through the center of the data:
        1. Call get_geometry_info() to get the center
        2. Use the center as the slice origin
        
        Args:
            proxy_name: Data source name, or None for active source
            
        Returns:
            Dict with:
            - bounds: [xmin, xmax, ymin, ymax, zmin, zmax]
            - center: [cx, cy, cz] - geometric center
            - extents: [dx, dy, dz] - size in each direction
            - longest_axis: "x", "y", or "z" - direction of largest extent
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = list(di.GetBounds())
            
            # Calculate center
            cx = (bounds[0] + bounds[1]) / 2
            cy = (bounds[2] + bounds[3]) / 2
            cz = (bounds[4] + bounds[5]) / 2
            
            # Calculate extents
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            
            # Find longest axis
            extents = {"x": dx, "y": dy, "z": dz}
            longest_axis = max(extents, key=extents.get)
            
            return {
                "bounds": bounds,
                "center": [cx, cy, cz],
                "extents": [dx, dy, dz],
                "longest_axis": longest_axis,
                "x_range": [bounds[0], bounds[1]],
                "y_range": [bounds[2], bounds[3]],
                "z_range": [bounds[4], bounds[5]],
            }
            
        except Exception as e:
            return {"error": str(e)}

    def ensure_velocity_vector(
        self, 
        proxy_name: str = None,
        output_name: str = "Velocity",
        u_component: str = None,
        v_component: str = None, 
        w_component: str = None
    ) -> dict:
        """
        Ensure a 3-component velocity vector exists, creating it from components if needed.
        
        Many CFD solvers output velocity as separate u, v, w scalar arrays.
        This tool combines them into a single vector for use with:
        - Streamlines (StreamTracer)
        - Vortex detection (Q-criterion, vorticity)
        - Wake analysis
        
        Args:
            proxy_name: Data source name, or None for active source
            output_name: Name for the combined velocity vector (default: "Velocity")
            u_component: Name of u (x-velocity) array, auto-detected if None
            v_component: Name of v (y-velocity) array, auto-detected if None
            w_component: Name of w (z-velocity) array, auto-detected if None
            
        Returns:
            Dict with status, velocity array name, and calculator proxy name if created
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Get available fields
            fields = self._get_available_fields(proxy)
            all_fields = fields["all_fields"]
            
            # Check if velocity vector already exists
            if "velocity" in fields["resolved"]:
                vel_name = fields["resolved"]["velocity"]
                # Verify it's 3-component
                raw_data = proxy.GetClientSideObject().GetOutputDataObject(0)
                data = self._get_leaf_data(raw_data)
                
                if data is None:
                    return {"error": "No data found in dataset"}
                
                arr = data.GetPointData().GetArray(vel_name)
                if arr is None:
                    arr = data.GetCellData().GetArray(vel_name)
                
                if arr and arr.GetNumberOfComponents() == 3:
                    return {
                        "status": "exists",
                        "velocity_array": vel_name,
                        "message": f"3-component velocity vector '{vel_name}' already exists"
                    }
            
            # Auto-detect component names if not provided
            if u_component is None or v_component is None or w_component is None:
                # Common patterns for velocity components
                u_patterns = ['u', 'U', 'Ux', 'VelocityX', 'velocity_x', 'ux']
                v_patterns = ['v', 'V', 'Uy', 'VelocityY', 'velocity_y', 'uy', 'vy']
                w_patterns = ['w', 'W', 'Uz', 'VelocityZ', 'velocity_z', 'uz', 'wz']
                
                def find_component(patterns):
                    for p in patterns:
                        if p in all_fields:
                            return p
                        # Case-insensitive match
                        for f in all_fields:
                            if f.lower() == p.lower():
                                return f
                    return None
                
                if u_component is None:
                    u_component = find_component(u_patterns)
                if v_component is None:
                    v_component = find_component(v_patterns)
                if w_component is None:
                    w_component = find_component(w_patterns)
            
            # Check all components found
            missing = []
            if u_component is None:
                missing.append("u (x-velocity)")
            elif u_component not in all_fields:
                missing.append(f"u component '{u_component}'")
                
            if v_component is None:
                missing.append("v (y-velocity)")
            elif v_component not in all_fields:
                missing.append(f"v component '{v_component}'")
                
            if w_component is None:
                missing.append("w (z-velocity)")
            elif w_component not in all_fields:
                missing.append(f"w component '{w_component}'")
            
            if missing:
                return {
                    "error": f"Cannot build velocity vector - missing: {missing}",
                    "available_fields": all_fields,
                    "hint": "Provide u_component, v_component, w_component explicitly"
                }
            
            # Create Calculator to combine components
            calc = simple.Calculator(Input=proxy)
            calc.ResultArrayName = output_name
            calc.ResultArrayType = 'Float'
            # ParaView Calculator syntax for building vector
            calc.Function = f"{u_component}*iHat + {v_component}*jHat + {w_component}*kHat"
            
            simple.UpdatePipeline(proxy=calc)
            
            # Get the calculator proxy name
            calc_name = None
            for name, p in simple.GetSources().items():
                if p == calc:
                    calc_name = name[0]
                    break
            
            return {
                "status": "created",
                "velocity_array": output_name,
                "calculator_proxy": calc_name,
                "components_used": {
                    "u": u_component,
                    "v": v_component,
                    "w": w_component
                },
                "message": f"Created velocity vector '{output_name}' from ({u_component}, {v_component}, {w_component})"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def validate_for_analysis(self, analysis_type: str, proxy_name: str = None) -> dict:
        """
        Check if a dataset has the required fields for a specific analysis type.
        
        Use this before running analysis to get clear error messages about
        missing fields or prerequisites.
        
        Args:
            analysis_type: One of:
                - "vortex": Q-criterion, vorticity, lambda2 (requires velocity)
                - "forces": Drag/lift computation (requires pressure, surface mesh)
                - "wake": Wake detection (requires velocity)
                - "streamlines": Streamline tracing (requires velocity vector)
            proxy_name: Data source name, or None for active source
            
        Returns:
            Dict with validation status, missing requirements, and suggestions
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Get dataset characteristics
            char = self.characterize_dataset(proxy_name)
            if "error" in char:
                return char
            
            requirements = {
                "vortex": {
                    "required": ["velocity"],
                    "description": "Vortex detection (Q-criterion, vorticity, lambda2)"
                },
                "forces": {
                    "required": ["pressure"],
                    "description": "Force computation (drag, lift)"
                },
                "wake": {
                    "required": ["velocity"],
                    "description": "Wake detection and analysis"
                },
                "streamlines": {
                    "required": ["velocity"],
                    "description": "Streamline visualization"
                }
            }
            
            if analysis_type not in requirements:
                return {
                    "error": f"Unknown analysis type: {analysis_type}",
                    "valid_types": list(requirements.keys())
                }
            
            req = requirements[analysis_type]
            resolved = char["resolved_fields"]
            velocity_components = char.get("velocity_components", [])
            
            missing = []
            suggestions = []
            
            for field in req["required"]:
                if field not in resolved:
                    missing.append(field)
                    
                    # Provide helpful suggestions
                    if field == "velocity" and len(velocity_components) >= 3:
                        suggestions.append(
                            f"Velocity components found: {velocity_components}. "
                            "Use ensure_velocity_vector() to combine them."
                        )
                    elif field == "velocity":
                        suggestions.append(
                            f"No velocity field found. Available arrays: {char['point_arrays']}"
                        )
                    elif field == "pressure":
                        suggestions.append(
                            f"No pressure field found. Available arrays: {char['point_arrays']}"
                        )
            
            if missing:
                return {
                    "valid": False,
                    "analysis_type": analysis_type,
                    "description": req["description"],
                    "missing_fields": missing,
                    "suggestions": suggestions,
                    "available_fields": char["resolved_fields"]
                }
            
            return {
                "valid": True,
                "analysis_type": analysis_type,
                "description": req["description"],
                "resolved_fields": {f: resolved[f] for f in req["required"]},
                "ready": True
            }
            
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # QUERY AND SELECTION TOOLS
    # =========================================================================
    
    def find_by_threshold(self, field: str, threshold: float, below: bool = True, proxy_name: str = None) -> dict:
        """
        Find centroid of region where field is below/above threshold.
        
        This is a view-independent alternative to find_by_query. Uses Threshold
        filter instead of QuerySelect, so it works without an active view.
        
        Args:
            field: Field name (e.g., "Velocity", "pressure")
            threshold: Threshold value
            below: If True, find where field < threshold; if False, field > threshold
            proxy_name: Data source
            
        Returns:
            Dict with centroid location, count, and bounds
            
        Examples:
            find_by_threshold("Velocity", 0.1, below=True)  - low velocity region
            find_by_threshold("pressure", 0.5, below=False) - high pressure region
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        resolved_field = self._resolve_field_type(field, proxy)
        
        try:
            # Handle multiblock - merge first for consistent processing
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutputDataObject(0)
            
            if data is None:
                return {"error": "No data available from proxy"}
            
            # Check if multiblock and merge if needed
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
                data = merge_input.GetClientSideObject().GetOutputDataObject(0)
                cleanup_input_merge = merge_input
            else:
                cleanup_input_merge = None
                
            if data is None:
                if cleanup_input_merge:
                    simple.Delete(cleanup_input_merge)
                return {"error": "No data available after merge"}
            
            # Check field type
            arr = data.GetPointData().GetArray(resolved_field)
            if arr is None:
                arr = data.GetCellData().GetArray(resolved_field)
            
            if arr is None:
                if cleanup_input_merge:
                    simple.Delete(cleanup_input_merge)
                return {"error": f"Field '{field}' not found"}
            
            is_vector = arr.GetNumberOfComponents() > 1
            
            # Use the merged data as input if we merged
            threshold_source = cleanup_input_merge if cleanup_input_merge else proxy
            
            if is_vector:
                # Need Calculator to compute magnitude
                calc = simple.Calculator(Input=threshold_source)
                calc.ResultArrayName = "_magnitude_"
                calc.Function = f"mag({resolved_field})"
                simple.UpdatePipeline(proxy=calc)
                threshold_input = calc
                threshold_field = "_magnitude_"
            else:
                threshold_input = threshold_source
                threshold_field = resolved_field
            
            # Apply threshold
            thresh = simple.Threshold(Input=threshold_input)
            thresh.Scalars = ['POINTS', threshold_field]
            if below:
                thresh.LowerThreshold = -1e30
                thresh.UpperThreshold = threshold
            else:
                thresh.LowerThreshold = threshold
                thresh.UpperThreshold = 1e30
            thresh.ThresholdMethod = "Between"
            simple.UpdatePipeline(proxy=thresh)
            
            # Get result
            result_data = thresh.GetClientSideObject().GetOutputDataObject(0)
            
            # Handle multiblock
            if result_data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=thresh)
                simple.UpdatePipeline(proxy=merge)
                result_data = merge.GetClientSideObject().GetOutputDataObject(0)
                cleanup_merge = merge
            else:
                cleanup_merge = None
            
            num_points = result_data.GetNumberOfPoints()
            
            if num_points == 0:
                # Cleanup
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                simple.Delete(thresh)
                if is_vector:
                    simple.Delete(calc)
                if cleanup_input_merge:
                    simple.Delete(cleanup_input_merge)
                return {
                    "error": f"No points found where {field} {'<' if below else '>'} {threshold}",
                    "field": field,
                    "threshold": threshold,
                    "below": below
                }
            
            # Compute centroid
            from vtk.util.numpy_support import vtk_to_numpy
            bounds = result_data.GetBounds()
            points = vtk_to_numpy(result_data.GetPoints().GetData())
            centroid = points.mean(axis=0).tolist()
            
            # Cleanup
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            simple.Delete(thresh)
            if is_vector:
                simple.Delete(calc)
            if cleanup_input_merge:
                simple.Delete(cleanup_input_merge)
            
            return {
                "location": centroid,
                "num_points": num_points,
                "bounds": list(bounds),
                "field": field,
                "threshold": threshold,
                "condition": f"{field} {'<' if below else '>'} {threshold}"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def query_select(self, query: str, field_type: str = "POINT", proxy_name: str = None) -> dict:
        """
        Select points or cells matching a query expression (ANALYSIS ONLY).
        
        Uses full NumPy-like expression capability. Works without a view.
        
        Args:
            query: Expression like "mag(Velocity) < 0.01" or "Velocity_X < 0"
            field_type: "POINT" or "CELL"
            proxy_name: Name of proxy to query, or None for active source
            
        Returns:
            Dict with selection count and query info
            
        Examples:
            query_select("mag(Velocity) < 0.01")  - count near-zero velocity points
            query_select("p < -0.5")              - count low pressure points
            query_select("Velocity_X < 0")        - count reversed flow points
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Use ParaView's selection helper to create properly wrapped selection
            from paraview.selection import _createSelection
            import paraview.vtk as vtk
            
            # Convert field_type to element type
            ftype = vtk.vtkSelectionNode.GetFieldTypeFromString(field_type)
            element_type = vtk.vtkSelectionNode.ConvertSelectionFieldToAttributeType(ftype)
            
            selection = _createSelection('SelectionQuerySource',
                QueryString=query,
                ElementType=element_type)
            
            # Use ExtractSelection with Selection parameter directly
            # This avoids the "Failed to locate property: Input" warnings
            extracted = simple.ExtractSelection(Input=proxy, Selection=selection)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutputDataObject(0)
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                merged_data = merge.GetClientSideObject().GetOutputDataObject(0)
                num_selected = merged_data.GetNumberOfPoints() if field_type == "POINT" else merged_data.GetNumberOfCells()
                simple.Delete(merge)
            else:
                num_selected = data.GetNumberOfPoints() if field_type == "POINT" else data.GetNumberOfCells()
            
            simple.Delete(extracted)
            
            return {
                "query": query,
                "field_type": field_type,
                "num_selected": num_selected,
                "status": "Selection counted" if num_selected > 0 else "No matches"
            }
        except Exception as e:
            return {"error": str(e), "query": query}
    
    def get_selection_info(self, proxy_name: str = None) -> dict:
        """
        Get information about the current selection.
        
        Returns centroid, bounds, and count of selected points/cells.
        
        Args:
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with centroid, bounds, count
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Extract selection to get actual data
            extracted = simple.ExtractSelection(Input=proxy)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutputDataObject(0)
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutputDataObject(0)
                cleanup_merge = merge
            else:
                cleanup_merge = None
            
            num_points = data.GetNumberOfPoints()
            
            if num_points == 0:
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                simple.Delete(extracted)
                return {"error": "No selection or empty selection"}
            
            # Compute centroid and bounds (vectorized)
            from vtk.util.numpy_support import vtk_to_numpy
            bounds = data.GetBounds()
            points = vtk_to_numpy(data.GetPoints().GetData())
            centroid = points.mean(axis=0).tolist()
            
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            simple.Delete(extracted)
            
            return {
                "num_points": num_points,
                "centroid": centroid,
                "bounds": {
                    "x": [bounds[0], bounds[1]],
                    "y": [bounds[2], bounds[3]],
                    "z": [bounds[4], bounds[5]],
                }
            }
        except Exception as e:
            return {"error": str(e)}
    
    def find_by_query(self, query: str, proxy_name: str = None) -> dict:
        """
        Find the centroid of points matching a query expression.
        
        Uses full NumPy-like expression capability. Works without a view.
        
        Args:
            query: Expression like "mag(Velocity) < 0.05" or "Velocity_X < 0"
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with centroid location, count, and bounds
            
        Examples:
            find_by_query("mag(Velocity) < 0.05")  - find stagnation region
            find_by_query("p < -0.5")              - find low pressure region
            find_by_query("Velocity_X < 0")        - find recirculation zone
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Use ParaView's selection helper to create properly wrapped selection
            from paraview.selection import _createSelection
            
            selection = _createSelection('SelectionQuerySource', 
                QueryString=query,
                ElementType=0)  # 0 = POINT
            
            # Use ExtractSelection with Selection parameter directly
            # This avoids the "Failed to locate property: Input" warnings
            # that occur when using SetSelectionInput
            extracted = simple.ExtractSelection(Input=proxy, Selection=selection)
            simple.UpdatePipeline(proxy=extracted)
            
            data = extracted.GetClientSideObject().GetOutputDataObject(0)
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutputDataObject(0)
                cleanup_merge = merge
            else:
                cleanup_merge = None
            
            num_points = data.GetNumberOfPoints()
            
            if num_points == 0:
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                simple.Delete(extracted)
                return {"error": "No points match query", "query": query}
            
            # Compute centroid
            from vtk.util.numpy_support import vtk_to_numpy
            bounds = data.GetBounds()
            points = vtk_to_numpy(data.GetPoints().GetData())
            centroid = points.mean(axis=0).tolist()
            
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            simple.Delete(extracted)
            
            return {
                "location": centroid,
                "num_points": num_points,
                "bounds": list(bounds),
                "query": query
            }
        except Exception as e:
            return {"error": str(e), "query": query}

    def find_minimum(self, field: str, proxy_name: str = None, exclude_boundaries: bool = True) -> dict:
        """
        Find location where a field has minimum value/magnitude.
        
        For vector fields, finds minimum magnitude.
        Useful for finding stagnation points (min velocity).
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            exclude_boundaries: If True, exclude points near domain boundaries
            
        Returns:
            Dict with location [x,y,z] and value
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        # Compute magnitude if vector
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
        else:
            mag = arr.flatten()
        
        if exclude_boundaries:
            bounds = data.GetBounds()
            margin = 0.05
            x_margin = (bounds[1] - bounds[0]) * margin
            y_margin = (bounds[3] - bounds[2]) * margin
            z_margin = (bounds[5] - bounds[4]) * margin if bounds[5] != bounds[4] else 0
            
            # Get all points as numpy array (vectorized)
            from vtk.util.numpy_support import vtk_to_numpy
            points = vtk_to_numpy(data.GetPoints().GetData())
            
            # Vectorized boundary check
            valid_mask = (
                (points[:, 0] >= bounds[0] + x_margin) & (points[:, 0] <= bounds[1] - x_margin) &
                (points[:, 1] >= bounds[2] + y_margin) & (points[:, 1] <= bounds[3] - y_margin)
            )
            if z_margin > 0:
                valid_mask &= (points[:, 2] >= bounds[4] + z_margin) & (points[:, 2] <= bounds[5] - z_margin)
            
            valid_mask &= (mag > 1e-10)
            
            if not np.any(valid_mask):
                idx = np.argmin(mag)
            else:
                masked_mag = np.where(valid_mask, mag, np.inf)
                idx = np.argmin(masked_mag)
        else:
            idx = np.argmin(mag)
        
        location = list(data.GetPoint(idx))
        value = float(mag[idx])
        
        return {
            "min_location": location,  # Specific key for workflow chaining
            "location": location,       # Generic for compatibility
            "value": value,
            "field": field_name,
            "type": "minimum"
        }
    
    def find_maximum(self, field: str, proxy_name: str = None) -> dict:
        """
        Find location where a field has maximum value/magnitude.
        
        For vector fields, finds maximum magnitude.
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with location [x,y,z] and value
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
        else:
            mag = arr.flatten()
        
        idx = np.argmax(mag)
        location = list(data.GetPoint(idx))
        value = float(mag[idx])
        
        return {
            "max_location": location,  # Specific key for workflow chaining
            "location": location,       # Generic for compatibility
            "value": value,
            "field": field_name,
            "type": "maximum"
        }
    
    def find_high_gradient(self, field: str, proxy_name: str = None) -> dict:
        """
        Find location of maximum gradient magnitude.
        
        Uses ParaView's Gradient filter to compute the gradient field,
        then finds where gradient magnitude is highest.
        
        Useful for finding:
        - Shear layers (high velocity gradient)
        - Boundary layers
        - Mixing zones
        - Wake edges
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with location [x,y,z] and gradient_magnitude
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        resolved_field = self._resolve_field_type(field, proxy)
        
        # Remember active source
        original_active = simple.GetActiveSource()
        
        try:
            # Check if multiblock by trying to get the output type
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutputDataObject(0)
            
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                input_for_gradient = merge
                cleanup_merge = merge
            else:
                input_for_gradient = proxy
                cleanup_merge = None
            
            # Create Gradient filter
            gradient = simple.Gradient(Input=input_for_gradient)
            gradient.ScalarArray = ['POINTS', resolved_field]
            gradient.ComputeGradient = 1
            gradient.ResultArrayName = "Gradient"
            simple.UpdatePipeline(proxy=gradient)
            
            # Get gradient array
            arr, grad_data = self._get_array(gradient, "Gradient")
            
            if arr is None:
                simple.Delete(gradient)
                if cleanup_merge:
                    simple.Delete(cleanup_merge)
                return {"error": f"Could not compute gradient of '{resolved_field}'"}
            
            # Compute gradient magnitude
            if arr.ndim > 1:
                grad_mag = np.linalg.norm(arr, axis=1)
            else:
                grad_mag = np.abs(arr.flatten())
            
            idx = np.argmax(grad_mag)
            location = list(grad_data.GetPoint(idx))
            value = float(grad_mag[idx])
            
            # Cleanup
            simple.Delete(gradient)
            if cleanup_merge:
                simple.Delete(cleanup_merge)
            
            # Restore active source
            simple.SetActiveSource(original_active)
            
            return {
                "high_gradient_location": location,  # Specific key for workflow chaining
                "location": location,                 # Generic for compatibility
                "gradient_magnitude": value,
                "field": resolved_field,
                "type": "high_gradient"
            }
        except Exception as e:
            simple.SetActiveSource(original_active)
            return {"error": str(e), "field": field}
    
    def field_statistics(self, field: str, proxy_name: str = None) -> dict:
        """
        Get statistics for a field (min, max, mean, std).
        
        Args:
            field: Field name (e.g., "Velocity") or semantic type (e.g., "velocity", "pressure")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with min, max, mean, std
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Resolve semantic field type to actual field name
        field_name = self._resolve_field_type(field, proxy)
        
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}
        
        result = {"field": field_name, "num_points": len(arr)}
        
        if arr.ndim > 1 and arr.shape[1] > 1:
            mag = np.linalg.norm(arr, axis=1)
            result["magnitude"] = {
                "min": float(np.min(mag)),
                "max": float(np.max(mag)),
                "mean": float(np.mean(mag)),
                "std": float(np.std(mag)),
            }
            result["components"] = arr.shape[1]
        else:
            arr = arr.flatten()
            result["min"] = float(np.min(arr))
            result["max"] = float(np.max(arr))
            result["mean"] = float(np.mean(arr))
            result["std"] = float(np.std(arr))
            result["components"] = 1
        
        return result
    
    def field_histogram(
        self,
        field: str,
        num_bins: int = 20,
        proxy_name: str = None
    ) -> dict:
        """
        Get histogram data for a field.
        
        Returns bin edges and counts that can be used for plotting.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with bins, counts, and statistics
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        field_name = self._resolve_field_type(field, proxy)
        arr, data = self._get_array(proxy, field_name)
        if arr is None:
            return {"error": f"Field '{field}' not found"}
        
        # Use magnitude for vectors
        if arr.ndim > 1 and arr.shape[1] > 1:
            arr = np.linalg.norm(arr, axis=1)
            field_name = f"{field_name} Magnitude"
        else:
            arr = arr.flatten()
        
        counts, bin_edges = np.histogram(arr, bins=num_bins)
        
        return {
            "field": field_name,
            "num_points": len(arr),
            "bins": bin_edges.tolist(),
            "counts": counts.tolist(),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
        }
    
    def compute_vortex_field(
        self,
        method: str = "q_criterion",
        percentile: float = 50.0,
        proxy_name: str = None
    ) -> dict:
        """
        Compute vortex detection field (ANALYSIS ONLY - no visualization).
        
        Creates the vortex field array and suggests a threshold value.
        Use the returned proxy_name with create("Contour") to visualize.
        
        Methods:
        - "q_criterion": Q = 0.5*(||Ω||² - ||S||²). Positive Q = vortex. (default)
        - "vorticity": Vorticity magnitude ||ω||. High = rotation.
        - "lambda2": Second eigenvalue of S² + Ω². Negative λ2 = vortex core.
        
        Args:
            method: "q_criterion", "vorticity", or "lambda2"
            percentile: Percentile of positive values for threshold (default: 50)
            proxy_name: Source proxy name
            
        Returns:
            {field_name, proxy_name, threshold, field_range} 
            - Use proxy_name as input to create("Contour")
            - Use threshold for Isosurfaces property
            
        Example workflow:
            result = compute_vortex_field("q_criterion")
            create("Contour", input_proxy=result["proxy_name"])
            update_list_property("Isosurfaces", [result["threshold"]])
            update_color(field_name="Velocity")
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Merge blocks for gradient computation
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            
            # Compute gradient with appropriate fields
            gradient = simple.Gradient(Input=merge)
            gradient.ScalarArray = ['POINTS', 'Velocity']
            
            if method == "q_criterion":
                gradient.ComputeQCriterion = 1
                gradient.QCriterionArrayName = "Q"
                field_name = "Q"
            elif method == "vorticity":
                gradient.ComputeVorticity = 1
                gradient.VorticityArrayName = "Vorticity"
                field_name = "Vorticity"
            elif method == "lambda2":
                gradient.ComputeGradient = 1
                gradient.ResultArrayName = "VelocityGradient"
                field_name = "Lambda2"
            else:
                simple.Delete(merge)
                return {"error": f"Unknown method: {method}. Use 'q_criterion', 'vorticity', or 'lambda2'"}
            
            simple.UpdatePipeline(proxy=gradient)
            
            # For vorticity, compute magnitude
            if method == "vorticity":
                calc = simple.Calculator(Input=gradient)
                calc.ResultArrayName = "VorticityMagnitude"
                calc.Function = "mag(Vorticity)"
                simple.UpdatePipeline(proxy=calc)
                output_proxy = calc
                field_name = "VorticityMagnitude"
            elif method == "lambda2":
                # Lambda2 needs eigenvalue computation via ProgrammableFilter
                prog = simple.ProgrammableFilter(Input=gradient)
                prog.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output
out.ShallowCopy(inp.VTKObject)

grad_vtk = inp.PointData.GetArray("VelocityGradient")
n = grad_vtk.GetNumberOfTuples()
G = np.array([grad_vtk.GetTuple(i) for i in range(n)]).reshape(-1, 3, 3)

lambda2 = np.zeros(n, dtype=np.float64)
valid_mask = np.all(np.isfinite(G), axis=(1, 2))
valid_indices = np.where(valid_mask)[0]

if len(valid_indices) > 0:
    G_valid = G[valid_indices]
    S = 0.5 * (G_valid + np.transpose(G_valid, (0, 2, 1)))
    Omega = 0.5 * (G_valid - np.transpose(G_valid, (0, 2, 1)))
    M = np.matmul(S, S) + np.matmul(Omega, Omega)
    try:
        eigvals = np.linalg.eigvalsh(M)
        lambda2[valid_indices] = eigvals[:, 1]
    except:
        pass

arr = numpy_to_vtk(np.ascontiguousarray(lambda2))
arr.SetName("Lambda2")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=prog)
                output_proxy = prog
            else:
                output_proxy = gradient
            
            # Get field array for threshold calculation
            output_data = output_proxy.GetClientSideObject().GetOutputDataObject(0)
            field_vtk = output_data.GetPointData().GetArray(field_name)
            if field_vtk is None:
                return {"error": f"Could not compute {field_name}"}
            
            field_array = vtk_to_numpy(field_vtk)
            field_min, field_max = float(field_array.min()), float(field_array.max())
            
            # Compute threshold
            if method == "lambda2":
                # Lambda2: use 1% of min (small negative)
                threshold = 0.01 * field_min
            else:
                # Q-criterion, vorticity: percentile of positive values
                positive_vals = field_array[field_array > 0]
                if len(positive_vals) > 0:
                    threshold = float(np.percentile(positive_vals, percentile))
                else:
                    threshold = max(0.0, field_max * 0.01)
            
            # Get output proxy name
            output_name = None
            for name, p in simple.GetSources().items():
                if p == output_proxy:
                    output_name = name[0]
                    break
            
            # Hide intermediate filters (MergeBlocks, Gradient, etc.) so they don't block visualization
            view = simple.GetActiveView()
            if view:
                for p in [merge, gradient]:
                    if p and p != output_proxy:
                        rep = simple.GetRepresentation(p, view)
                        if rep:
                            rep.Visibility = 0
                # Also hide output proxy - user will show it via Contour
                rep = simple.GetRepresentation(output_proxy, view)
                if rep:
                    rep.Visibility = 0
            
            return {
                "field_name": field_name,
                "proxy_name": output_name,
                "threshold": float(threshold),
                "field_range": [field_min, field_max],
                "method": method,
            }
        except Exception as e:
            return {"error": str(e)}

    # NOTE: create_vortex_isosurface and create_slice removed - use compute_* then base create()
    
    def compute_forces(
        self,
        freestream_velocity: float = None,
        reference_area: float = None,
        density: float = 1.0,
        streamwise_axis: str = "x",
        lift_axis: str = "y",
        proxy_name: str = None
    ) -> dict:
        """
        Compute aerodynamic forces (drag/lift) by integrating pressure on surfaces.
        
        Integrates pressure × surface_normal over all surfaces (walls).
        Reports both dimensional forces and non-dimensional coefficients.
        
        Args:
            freestream_velocity: Reference velocity for Cd/Cl (auto-detected if None)
            reference_area: Reference area for Cd/Cl (auto-detected from bounds if None)
            density: Fluid density (default: 1.0 for non-dimensional pressure)
            streamwise_axis: Axis for drag force ("x", "y", or "z", default: "x")
            lift_axis: Axis for lift force ("x", "y", or "z", default: "y")
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with drag, lift forces and coefficients
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Merge blocks if multiblock
            data = proxy.GetClientSideObject().GetOutputDataObject(0)
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
            else:
                merge_input = proxy
            
            # Extract surfaces
            surface = simple.ExtractSurface(Input=merge_input)
            simple.UpdatePipeline(proxy=surface)
            
            # Compute normals
            normals = simple.SurfaceNormals(Input=surface)
            normals.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals)
            
            surf_data = normals.GetClientSideObject().GetOutputDataObject(0)
            
            # Handle multiblock by merging
            if surf_data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=normals)
                simple.UpdatePipeline(proxy=merge)
                surf_data = merge.GetClientSideObject().GetOutputDataObject(0)
            else:
                merge = None
            
            # Get pressure (cell data after surface extraction)
            pressure_array = surf_data.GetCellData().GetArray("p")
            if pressure_array is None:
                pressure_array = surf_data.GetCellData().GetArray("Pressure")
            if pressure_array is None:
                # Try point data and use cell centers
                pressure_array = surf_data.GetPointData().GetArray("p")
                if pressure_array is None:
                    pressure_array = surf_data.GetPointData().GetArray("Pressure")
            
            if pressure_array is None:
                if merge:
                    simple.Delete(merge)
                simple.Delete(normals)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No pressure field found (tried 'p' and 'Pressure')"}
            
            pressure = vtk_to_numpy(pressure_array)
            
            # Get surface normals (cell data)
            normal_array = surf_data.GetCellData().GetArray("Normals")
            if normal_array is None:
                if merge:
                    simple.Delete(merge)
                simple.Delete(normals)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "Could not compute surface normals"}
            
            surf_normals = vtk_to_numpy(normal_array)
            
            # Compute cell areas
            num_cells = surf_data.GetNumberOfCells()
            areas = np.zeros(num_cells)
            for i in range(num_cells):
                cell = surf_data.GetCell(i)
                if cell.GetCellType() == 5:  # VTK_TRIANGLE
                    pts = vtk_to_numpy(cell.GetPoints().GetData())
                    v1 = pts[1] - pts[0]
                    v2 = pts[2] - pts[0]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                elif cell.GetCellType() == 9:  # VTK_QUAD
                    pts = vtk_to_numpy(cell.GetPoints().GetData())
                    v1 = pts[2] - pts[0]
                    v2 = pts[3] - pts[1]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                else:
                    # Approximate with bounding box for other types
                    bounds = [0.0] * 6
                    cell.GetBounds(bounds)
                    areas[i] = (bounds[1]-bounds[0]) * (bounds[3]-bounds[2])
            
            # Handle pressure being point data (interpolate to cells)
            if len(pressure) != num_cells:
                # Point data - need to average to cells
                cell_pressure = np.zeros(num_cells)
                for i in range(num_cells):
                    cell = surf_data.GetCell(i)
                    pt_ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
                    cell_pressure[i] = np.mean([pressure[pid] for pid in pt_ids])
                pressure = cell_pressure
            
            # Axis mapping
            axis_map = {"x": 0, "y": 1, "z": 2}
            drag_idx = axis_map.get(streamwise_axis.lower(), 0)
            lift_idx = axis_map.get(lift_axis.lower(), 1)
            
            # Integrate: F = -∫ p * n * dA (negative because pressure acts inward)
            # Drag = force in streamwise direction
            # Lift = force in lift direction
            force_x = -np.sum(pressure * surf_normals[:, 0] * areas)
            force_y = -np.sum(pressure * surf_normals[:, 1] * areas)
            force_z = -np.sum(pressure * surf_normals[:, 2] * areas)
            
            forces = [force_x, force_y, force_z]
            drag = forces[drag_idx]
            lift = forces[lift_idx]
            
            # Get reference values if not provided
            if freestream_velocity is None:
                # Use max velocity magnitude as reference
                vel_array = surf_data.GetPointData().GetArray("Velocity")
                if vel_array is None:
                    # Try from original proxy
                    orig_data = proxy.GetClientSideObject().GetOutputDataObject(0)
                    if orig_data.IsA("vtkMultiBlockDataSet"):
                        orig_data = orig_data.GetBlock(0)
                    vel_array = orig_data.GetPointData().GetArray("Velocity")
                
                if vel_array is not None:
                    vel = vtk_to_numpy(vel_array)
                    freestream_velocity = float(np.max(np.linalg.norm(vel, axis=1)))
                else:
                    freestream_velocity = 1.0
            
            if reference_area is None:
                # Compute actual projected frontal area via rasterization
                # This is more accurate than bounding box approximation
                flow_dir = [0, 0, 0]
                flow_dir[drag_idx] = 1.0
                area_result = self.compute_projected_area(
                    flow_direction=flow_dir,
                    resolution=1024,  # Lower res for speed, still accurate
                    proxy_name=proxy_name
                )
                if "error" not in area_result:
                    reference_area = area_result["area"]
                else:
                    # Fallback to bounding box estimate
                    body_bounds, _ = self._get_body_bounds(proxy)
                    if drag_idx == 0:  # streamwise = x
                        reference_area = (body_bounds[3] - body_bounds[2]) * (body_bounds[5] - body_bounds[4])
                    elif drag_idx == 1:  # streamwise = y
                        reference_area = (body_bounds[1] - body_bounds[0]) * (body_bounds[5] - body_bounds[4])
                    else:  # streamwise = z
                        reference_area = (body_bounds[1] - body_bounds[0]) * (body_bounds[3] - body_bounds[2])
            
            # Compute coefficients: C = F / (0.5 * ρ * V² * A)
            dynamic_pressure = 0.5 * density * freestream_velocity ** 2
            if dynamic_pressure > 1e-10 and reference_area > 1e-10:
                Cd = drag / (dynamic_pressure * reference_area)
                Cl = lift / (dynamic_pressure * reference_area)
            else:
                Cd = Cl = float('nan')
            
            # Cleanup
            if merge:
                simple.Delete(merge)
            simple.Delete(normals)
            simple.Delete(surface)
            if merge_input != proxy:
                simple.Delete(merge_input)
            
            return {
                "drag_force": float(drag),
                "lift_force": float(lift),
                "force_x": float(force_x),
                "force_y": float(force_y),
                "force_z": float(force_z),
                "Cd": float(Cd),
                "Cl": float(Cl),
                "freestream_velocity": float(freestream_velocity),
                "reference_area": float(reference_area),
                "density": float(density),
                "total_surface_area": float(np.sum(areas)),
                "num_surface_cells": int(num_cells),
                "streamwise_axis": streamwise_axis,
                "lift_axis": lift_axis,
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def compute_force_distribution(
        self,
        force_axis: str = "auto",
        distribution_axis: str = "auto",
        num_bins: int = 40,
        proxy_name: str = None
    ) -> dict:
        """
        Compute force distribution along an axis (ANALYSIS ONLY - no visualization).
        
        Integrates pressure forces on body surfaces and returns:
        - stations: Position along distribution axis
        - sectional_force: Local force contribution per station
        - accumulated_force: Cumulative sum along the distribution axis
        
        Use field_histogram or a charting library to visualize the results.
        
        Args:
            force_axis: Force component direction:
                - "auto" or "streamwise" or "drag": Auto-detect streamwise
                - "lift": Perpendicular to streamwise
                - "x", "y", "z": Explicit axis
            distribution_axis: Axis to distribute along:
                - "auto" or "streamwise": Along flow direction
                - "span": Perpendicular to flow, largest extent
                - "x", "y", "z": Explicit axis
            num_bins: Number of stations (default: 40)
            proxy_name: Source proxy name
            
        Returns:
            {stations, sectional_force, accumulated_force, total_force, ...}
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Auto-detect streamwise and span directions
            streamwise_axis = None
            span_axis = None
            
            if force_axis in ("auto", "streamwise", "drag") or distribution_axis in ("auto", "streamwise", "span"):
                streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
                if "error" in streamwise_result:
                    return {"error": f"Could not detect streamwise direction: {streamwise_result['error']}"}
                
                streamwise = streamwise_result["streamwise"]
                streamwise_axis = streamwise[-1].lower()
                
                bounds = proxy.GetDataInformation().GetBounds()
                extents = {
                    "x": bounds[1] - bounds[0],
                    "y": bounds[3] - bounds[2],
                    "z": bounds[5] - bounds[4],
                }
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                span_axis = max(perp_axes, key=lambda a: extents[a])
            
            # Resolve force_axis
            if force_axis in ("auto", "streamwise", "drag"):
                force_axis = streamwise_axis
            elif force_axis == "lift":
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                force_axis = "y" if "y" in perp_axes else perp_axes[0]
            
            # Resolve distribution_axis
            if distribution_axis in ("auto", "streamwise"):
                distribution_axis = streamwise_axis
            elif distribution_axis == "span":
                distribution_axis = span_axis
            
            # Merge if multiblock
            data = proxy.GetClientSideObject().GetOutputDataObject(0)
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
            else:
                merge_input = proxy
            
            # Extract surface and compute normals
            surface = simple.ExtractSurface(Input=merge_input)
            simple.UpdatePipeline(proxy=surface)
            
            normals_filter = simple.SurfaceNormals(Input=surface)
            normals_filter.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals_filter)
            
            surf_data = normals_filter.GetClientSideObject().GetOutputDataObject(0)
            num_cells = surf_data.GetNumberOfCells()
            
            # Get pressure
            pressure = surf_data.GetPointData().GetArray('p')
            if pressure is None:
                pressure = surf_data.GetPointData().GetArray('Pressure')
            if pressure is None:
                simple.Delete(normals_filter)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No pressure field found"}
            
            pressure = vtk_to_numpy(pressure)
            surf_normals = vtk_to_numpy(surf_data.GetCellData().GetArray('Normals'))
            
            # Compute cell centers, areas, and pressures
            centers = np.zeros((num_cells, 3))
            areas = np.zeros(num_cells)
            cell_pressure = np.zeros(num_cells)
            
            for i in range(num_cells):
                cell = surf_data.GetCell(i)
                pts = vtk_to_numpy(cell.GetPoints().GetData())
                centers[i] = pts.mean(axis=0)
                
                if cell.GetCellType() == 5:  # Triangle
                    v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                elif cell.GetCellType() == 9:  # Quad
                    v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                
                pt_ids = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]
                cell_pressure[i] = np.mean([pressure[pid] for pid in pt_ids])
            
            # Filter for body cells (not at domain boundaries)
            bounds = surf_data.GetBounds()
            eps = 0.3
            body_mask = (
                (centers[:, 0] > bounds[0] + eps) & (centers[:, 0] < bounds[1] - eps) &
                (centers[:, 1] > bounds[2] + eps) & (centers[:, 1] < bounds[3] - eps) &
                (centers[:, 2] > bounds[4] + eps) & (centers[:, 2] < bounds[5] - eps)
            )
            
            # Cleanup filters
            simple.Delete(normals_filter)
            simple.Delete(surface)
            if merge_input != proxy:
                simple.Delete(merge_input)
            
            if body_mask.sum() == 0:
                return {"error": "No body cells found (all cells at boundaries)"}
            
            # Compute force distribution
            axis_map = {"x": 0, "y": 1, "z": 2}
            force_idx = axis_map.get(force_axis.lower(), 0)
            dist_idx = axis_map.get(distribution_axis.lower(), 0)
            
            force_per_cell = -cell_pressure * surf_normals[:, force_idx] * areas
            
            pos_body = centers[body_mask, dist_idx]
            force_body = force_per_cell[body_mask]
            
            pos_min, pos_max = pos_body.min(), pos_body.max()
            bin_edges = np.linspace(pos_min, pos_max, num_bins + 1)
            bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
            
            binned_force = np.zeros(num_bins)
            for i in range(num_bins):
                mask = (pos_body >= bin_edges[i]) & (pos_body < bin_edges[i+1])
                binned_force[i] = force_body[mask].sum()
            
            accumulated = np.cumsum(binned_force)
            
            return {
                "force_axis": force_axis,
                "distribution_axis": distribution_axis,
                "stations": bin_centers.tolist(),
                "sectional_force": binned_force.tolist(),
                "accumulated_force": accumulated.tolist(),
                "total_force": float(accumulated[-1]),
                "position_range": [float(pos_min), float(pos_max)],
                "num_body_cells": int(body_mask.sum()),
                "num_bins": num_bins,
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def compute_projected_area(
        self,
        flow_direction: list = None,
        resolution: int = 2048,
        proxy_name: str = None
    ) -> dict:
        """
        Compute projected frontal area via rasterization and pixel counting.
        
        Renders the body surface with orthographic projection aligned with the
        flow direction, then counts non-background pixels to compute area.
        This handles complex geometries, hidden surfaces, and concavities correctly.
        
        Args:
            flow_direction: Flow direction vector [x, y, z] (default: [1, 0, 0])
            resolution: Render resolution (default: 2048, higher = more accurate)
            proxy_name: Source proxy name
            
        Returns:
            Dict with:
            - area: Projected frontal area in model units squared
            - pixel_count: Number of covered pixels
            - pixel_size: Size of each pixel in model units
            - flow_direction: Normalized flow direction used
        """
        import numpy as np
        from vtk import vtkWindowToImageFilter
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        # Default flow direction
        if flow_direction is None:
            flow_direction = [1.0, 0.0, 0.0]
        flow = np.array(flow_direction, dtype=float)
        flow = flow / np.linalg.norm(flow)
        
        try:
            # Get body bounds
            body_bounds, _ = self._get_body_bounds(proxy)
            
            # Extract surface first, then clip to body region
            # (Clipping volume mesh doesn't isolate body surface correctly)
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            
            surf = simple.ExtractSurface(Input=merge)
            simple.UpdatePipeline(proxy=surf)
            
            # Clip surface to body region
            clip = simple.Clip(Input=surf)
            clip.ClipType = 'Box'
            clip.ClipType.Bounds = [
                body_bounds[0] - 0.01, body_bounds[1] + 0.01,
                body_bounds[2] - 0.01, body_bounds[3] + 0.01,
                body_bounds[4] - 0.01, body_bounds[5] + 0.01
            ]
            clip.Invert = 1  # Keep inside
            simple.UpdatePipeline(proxy=clip)
            
            # Create offscreen render view
            view = simple.CreateView('RenderView')
            view.ViewSize = [resolution, resolution]
            view.Background = [0, 0, 0]
            view.UseColorPaletteForBackground = 0  # Use explicit black background
            view.OrientationAxesVisibility = 0     # Hide orientation widget
            
            # Display with flat white color (no lighting effects)
            display = simple.Show(clip, view)
            display.Representation = 'Surface'
            display.DiffuseColor = [1, 1, 1]
            display.AmbientColor = [1, 1, 1]
            display.Specular = 0
            display.Ambient = 1.0
            display.Diffuse = 0.0
            
            # Orthographic projection
            view.CameraParallelProjection = 1
            
            # Camera alignment - look along flow direction
            cx = 0.5 * (body_bounds[0] + body_bounds[1])
            cy = 0.5 * (body_bounds[2] + body_bounds[3])
            cz = 0.5 * (body_bounds[4] + body_bounds[5])
            center = np.array([cx, cy, cz])
            
            # Place camera far upstream
            distance = 10.0
            camera_pos = center - flow * distance
            
            view.CameraPosition = camera_pos.tolist()
            view.CameraFocalPoint = center.tolist()
            
            # Choose view-up automatically (perpendicular to flow)
            up_guess = np.array([0, 0, 1])
            if abs(np.dot(up_guess, flow)) > 0.9:
                up_guess = np.array([0, 1, 0])
            
            right = np.cross(flow, up_guess)
            up = np.cross(right, flow)
            up = up / np.linalg.norm(up)
            
            view.CameraViewUp = up.tolist()
            
            # Set parallel scale to fit body with margin
            # Parallel scale = half the height of visible region
            span_y = body_bounds[3] - body_bounds[2]
            span_z = body_bounds[5] - body_bounds[4]
            parallel_scale = max(span_y, span_z) * 0.6
            view.CameraParallelScale = parallel_scale
            height = view.ViewSize[1]
            
            simple.SetActiveView(view)
            simple.Render(view)
            
            # Capture image
            w2i = vtkWindowToImageFilter()
            w2i.SetInput(view.GetRenderWindow())
            w2i.Update()
            
            image = w2i.GetOutput()
            dims = image.GetDimensions()
            vtk_array = image.GetPointData().GetScalars()
            np_img = vtk_to_numpy(vtk_array)
            
            # Reshape image (may be RGB or RGBA)
            n_components = vtk_array.GetNumberOfComponents()
            np_img = np_img.reshape(dims[1], dims[0], n_components)
            
            # Count non-background pixels (threshold > 10 to avoid noise)
            mask = np_img[:, :, 0] > 10
            covered_pixels = int(np.count_nonzero(mask))
            
            # Convert to area
            pixel_size = 2.0 * parallel_scale / height
            area = covered_pixels * pixel_size * pixel_size
            
            # Cleanup
            simple.Delete(view)
            simple.Delete(surf)
            simple.Delete(clip)
            simple.Delete(merge)
            
            return {
                "area": float(area),
                "pixel_count": covered_pixels,
                "pixel_size": float(pixel_size),
                "resolution": resolution,
                "flow_direction": flow.tolist(),
                "body_bounds": body_bounds
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def compute_flow_topology(
        self,
        proxy_name: str = None
    ) -> dict:
        """
        Compute flow topology using vortex core detection.
        
        Uses VTK's VortexCores filter to extract vortex core lines from the
        velocity field. This is more appropriate for external aerodynamics
        than VectorFieldTopology, which finds spurious critical points on
        no-slip walls.
        
        Args:
            proxy_name: Source proxy name
            
        Returns:
            Dict with:
            - vortex_cores: vtkPolyData of vortex core lines
            - n_cores: Number of vortex core line segments
            - n_points: Number of points on core lines
            - bounds: Spatial extent of vortex cores
        """
        import numpy as np
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Merge blocks first
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            
            # Check for velocity field
            data = merge.GetClientSideObject().GetOutput()
            vel = data.GetPointData().GetArray('Velocity')
            if vel is None:
                simple.Delete(merge)
                return {"error": "No Velocity field found"}
            
            # Run VortexCores filter
            vortex = simple.VortexCores(Input=merge)
            vortex.VectorField = ['POINTS', 'Velocity']
            simple.UpdatePipeline(proxy=vortex)
            
            # Get output
            cores = vortex.GetClientSideObject().GetOutput()
            
            n_points = cores.GetNumberOfPoints()
            n_cores = cores.GetNumberOfCells()
            
            # Get bounds if we have points
            bounds = None
            if n_points > 0:
                pts = vtk_to_numpy(cores.GetPoints().GetData())
                bounds = {
                    "x": [float(pts[:,0].min()), float(pts[:,0].max())],
                    "y": [float(pts[:,1].min()), float(pts[:,1].max())],
                    "z": [float(pts[:,2].min()), float(pts[:,2].max())]
                }
            
            # Keep filter alive for visualization (don't delete yet)
            # The workflow will handle cleanup
            simple.Delete(merge)
            
            return {
                "vortex_cores": cores,
                "vortex_filter": vortex,  # Keep reference for visualization
                "n_cores": n_cores,
                "n_points": n_points,
                "bounds": bounds
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def create_histogram_chart(
        self,
        field: str,
        num_bins: int = 20,
        proxy_name: str = None
    ) -> dict:
        """
        Create bar chart showing field distribution (VISUALIZATION ONLY).
        
        Uses field_histogram() for data, then creates ParaView chart.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Source proxy name
            
        Returns:
            Dict with chart info and statistics
        """
        # Save original view to restore later (charts create new views)
        original_view = simple.GetActiveView()
        
        # Get histogram data from analysis function
        hist_data = self.field_histogram(
            field=field,
            num_bins=num_bins,
            proxy_name=proxy_name
        )
        
        if "error" in hist_data:
            return hist_data
        
        try:
            proxy = self._get_proxy(proxy_name)
            original_source = simple.GetActiveSource()  # Save for restore
            field_name = hist_data["field"]
            
            # Merge if multiblock
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutputDataObject(0)
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                hist_input = merge
            else:
                merge = None
                hist_input = proxy
            
            # Create histogram filter for visualization
            hist = simple.Histogram(Input=hist_input)
            hist.SelectInputArray = ['POINTS', self._resolve_field_type(field, proxy)]
            hist.BinCount = num_bins
            
            # Use magnitude for vectors
            if "Magnitude" in field_name:
                hist.Component = 'Magnitude'
            
            simple.UpdatePipeline(proxy=hist)
            
            # Create bar chart view
            chart_view = simple.CreateBarChartView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Distribution of {field_name}'
            
            display = simple.Show(hist, chart_view)
            simple.Render(chart_view)
            
            self._chart_view_queue.append(chart_view)
            
            if merge:
                simple.Delete(merge)
            
            # Restore active source and view
            if original_source:
                simple.SetActiveSource(original_source)
            if original_view:
                simple.SetActiveView(original_view)
            
            return {
                "status": "created",
                "chart_type": "histogram",
                **hist_data
            }
            
        except Exception as e:
            return {"error": str(e)}
        
    def create_force_distribution_chart(
        self,
        force_axis: str = "auto",
        distribution_axis: str = "auto",
        num_bins: int = 40,
        proxy_name: str = None
    ) -> dict:
        """
        Create XY chart showing force distribution (VISUALIZATION ONLY).
        
        Uses compute_force_distribution() for data, then creates ParaView chart.
        
        Args:
            force_axis: "auto"/"drag", "lift", or "x"/"y"/"z"
            distribution_axis: "auto"/"streamwise", "span", or "x"/"y"/"z"
            num_bins: Number of stations (default: 40)
            proxy_name: Source proxy name
            
        Returns:
            Dict with chart info and force data
        """
        # Get force distribution data from analysis function
        dist_data = self.compute_force_distribution(
            force_axis=force_axis,
            distribution_axis=distribution_axis,
            num_bins=num_bins,
            proxy_name=proxy_name
        )
        
        if "error" in dist_data:
            return dist_data
        
        try:
            import tempfile
            import os
            
            original_source = simple.GetActiveSource()  # Save for restore
            original_view = simple.GetActiveView()  # Save view too
            
            stations = dist_data["stations"]
            sectional = dist_data["sectional_force"]
            accumulated = dist_data["accumulated_force"]
            
            # Write CSV for plotting
            csv_path = os.path.join(tempfile.gettempdir(), 'force_distribution.csv')
            with open(csv_path, 'w') as f:
                f.write('Position,Sectional_Force,Accumulated_Force\n')
                for i in range(len(stations)):
                    f.write(f'{stations[i]:.6f},{sectional[i]:.8f},{accumulated[i]:.8f}\n')
            
            # Create XY plot
            table = simple.CSVReader(FileName=[csv_path])
            simple.UpdatePipeline(proxy=table)
            
            force_names = {"x": "Drag", "y": "Lift", "z": "Side Force"}
            force_name = force_names.get(dist_data["force_axis"].lower(), "Force")
            
            chart_view = simple.CreateXYPlotView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Accumulated {force_name} Distribution'
            chart_view.BottomAxisTitle = f'{dist_data["distribution_axis"].upper()} Position'
            chart_view.LeftAxisTitle = f'{force_name}'
            
            display = simple.Show(table, chart_view)
            display.XArrayName = 'Position'
            display.UseIndexForXAxis = 0
            display.SeriesVisibility = ['Accumulated_Force', 'Sectional_Force']
            display.SeriesColor = ['Accumulated_Force', '0', '0', '0.8', 'Sectional_Force', '0.8', '0', '0']
            display.SeriesLineThickness = ['Accumulated_Force', '2', 'Sectional_Force', '2']
            
            simple.Render(chart_view)
            self._chart_view_queue.append(chart_view)
            
            # Restore active source and view
            if original_source:
                simple.SetActiveSource(original_source)
            if original_view:
                simple.SetActiveView(original_view)
            
            return {
                "status": "created",
                "chart_type": "force_distribution",
                **dist_data
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def set_view(
        self,
        direction: str = "iso",
        proxy_name: str = None
    ) -> dict:
        """
        Set camera to a standard view direction and focus on a proxy.
        
        Use this after creating visualizations like slices to ensure proper viewing angle.
        For slices, the view should be NORMAL to the slice plane.
        
        Args:
            direction: View direction - one of:
                - "front" or "+x": View from +X (looking at YZ plane)
                - "back" or "-x": View from -X
                - "top" or "+y": View from +Y (looking at XZ plane)
                - "bottom" or "-y": View from -Y
                - "right" or "+z": View from +Z (looking at XY plane)
                - "left" or "-z": View from -Z
                - "iso": Isometric view (default)
            proxy_name: Proxy to focus on (uses its bounds for framing)
            
        Returns:
            Dict with camera settings applied
        """
        view = simple.GetActiveView()
        
        # Ensure we have a RenderView (not a chart view)
        if view is None or not hasattr(view, 'ResetCamera'):
            for v in simple.GetViews():
                if hasattr(v, 'ResetCamera'):
                    view = v
                    break
            else:
                view = simple.CreateRenderView()
            simple.SetActiveView(view)
        
        # Get proxy for bounds
        proxy = self._get_proxy(proxy_name)
        if proxy:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            cx = (bounds[0] + bounds[1]) / 2
            cy = (bounds[2] + bounds[3]) / 2
            cz = (bounds[4] + bounds[5]) / 2
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            distance = max(dx, dy, dz) * 2.0
        else:
            cx, cy, cz = 0, 0, 0
            distance = 5.0
        
        # Set camera based on direction
        dir_lower = direction.lower()
        
        if dir_lower in ["front", "+x", "x"]:
            pos = [cx + distance, cy, cz]
            up = [0, 1, 0]
        elif dir_lower in ["back", "-x"]:
            pos = [cx - distance, cy, cz]
            up = [0, 1, 0]
        elif dir_lower in ["top", "+y", "y"]:
            pos = [cx, cy + distance, cz]
            up = [0, 0, -1]
        elif dir_lower in ["bottom", "-y"]:
            pos = [cx, cy - distance, cz]
            up = [0, 0, 1]
        elif dir_lower in ["right", "+z", "z"]:
            pos = [cx, cy, cz + distance]
            up = [0, 1, 0]
        elif dir_lower in ["left", "-z"]:
            pos = [cx, cy, cz - distance]
            up = [0, 1, 0]
        else:  # iso
            pos = [cx + distance*0.7, cy + distance*0.5, cz + distance*0.7]
            up = [0, 1, 0]
        
        # Apply camera settings
        view.CameraPosition = pos
        view.CameraFocalPoint = [cx, cy, cz]
        view.CameraViewUp = up
        view.CenterOfRotation = [cx, cy, cz]
        
        # Reset to fit bounds
        if proxy:
            view.ResetCamera(*bounds, False, 0.9)
        
        simple.Render(view)
        
        return {
            "status": "view_set",
            "direction": direction,
            "focal_point": [cx, cy, cz]
        }
    
    def detect_streamwise_direction(self, proxy_name: str = None) -> dict:
        """
        Detect the principal flow (streamwise) direction from velocity field.
        
        Uses magnitude-weighted average of velocity vectors to find the dominant
        flow direction. Returns the closest axis-aligned direction.
        
        Returns:
            Dict with streamwise direction (+x, -x, +y, -y, +z, -z) and confidence
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Merge blocks if needed
            cso = proxy.GetClientSideObject()
            if hasattr(cso, 'GetOutput'):
                data = cso.GetOutput()
            else:
                data = cso.GetOutputDataObject(0)
            
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutputDataObject(0)
            else:
                merge = None
            
            # Get velocity array
            vel_array = data.GetPointData().GetArray("Velocity")
            if vel_array is None:
                if merge:
                    simple.Delete(merge)
                return {"error": "No Velocity field found"}
            
            vel = vtk_to_numpy(vel_array)
            
            # Compute magnitude-weighted average direction
            mag = np.linalg.norm(vel, axis=1, keepdims=True)
            mag = np.where(mag > 1e-10, mag, 1e-10)  # avoid division by zero
            
            # Weight by magnitude squared (emphasize high-speed regions)
            weights = mag.flatten() ** 2
            weighted_vel = vel * weights[:, np.newaxis]
            total_weight = np.sum(weights)
            if total_weight < 1e-20:
                if merge:
                    simple.Delete(merge)
                return {"error": "All velocity magnitudes near zero — cannot determine flow direction"}
            avg_direction = np.sum(weighted_vel, axis=0) / total_weight
            norm = np.linalg.norm(avg_direction)
            if norm < 1e-20:
                if merge:
                    simple.Delete(merge)
                return {"error": "Velocity directions cancel out — no dominant flow direction"}
            avg_direction = avg_direction / norm
            
            if merge:
                simple.Delete(merge)
            
            # Find closest axis-aligned direction
            axes = {
                "+x": np.array([1, 0, 0]),
                "-x": np.array([-1, 0, 0]),
                "+y": np.array([0, 1, 0]),
                "-y": np.array([0, -1, 0]),
                "+z": np.array([0, 0, 1]),
                "-z": np.array([0, 0, -1]),
            }
            
            best_dir = None
            best_dot = -1
            for name, axis in axes.items():
                dot = np.dot(avg_direction, axis)
                if dot > best_dot:
                    best_dot = dot
                    best_dir = name
            
            return {
                "streamwise": best_dir,
                "direction_vector": avg_direction.tolist(),
                "confidence": float(best_dot)  # 1.0 = perfectly aligned with axis
            }
        except Exception as e:
            return {"error": str(e)}
    
    def detect_span_direction(self, proxy_name: str = None) -> dict:
        """
        Detect the spanwise direction based on body geometry and flow direction.
        
        Span is defined as the axis perpendicular to streamwise with the largest
        body extent. For a wing, this would typically be the axis along the wingspan.
        
        Returns:
            Dict with span_axis, streamwise_axis, vertical_axis, and body extents
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Get streamwise direction
            streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
            if "error" in streamwise_result:
                return streamwise_result
            
            streamwise = streamwise_result["streamwise"]
            streamwise_axis = streamwise[1]  # Extract axis letter from "+x", "-y", etc.
            
            # Get body bounds
            body_bounds, _ = self._get_body_bounds(proxy)
            
            extents = {
                "x": body_bounds[1] - body_bounds[0],
                "y": body_bounds[3] - body_bounds[2],
                "z": body_bounds[5] - body_bounds[4]
            }
            
            # Span is perpendicular axis with largest extent
            perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
            span_axis = max(perp_axes, key=lambda a: extents[a])
            
            # Vertical is the remaining axis
            vertical_axis = [a for a in perp_axes if a != span_axis][0]
            
            # Body center
            body_center = [
                (body_bounds[0] + body_bounds[1]) / 2,
                (body_bounds[2] + body_bounds[3]) / 2,
                (body_bounds[4] + body_bounds[5]) / 2
            ]
            
            return {
                "span_axis": span_axis,
                "streamwise_axis": streamwise_axis,
                "vertical_axis": vertical_axis,
                "extents": extents,
                "body_bounds": list(body_bounds),
                "body_center": body_center,
                "span_extent": extents[span_axis],
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def compute_spanwise_slice_params(
        self,
        offset: float = 0.0,
        proxy_name: str = None
    ) -> dict:
        """
        Compute slice parameters for a spanwise cut through the body.
        
        Creates a slice perpendicular to the span axis at the specified offset
        from body center. Useful for viewing airfoil sections at different span
        stations.
        
        Args:
            offset: Position along span as fraction of span extent (-1 to 1).
                    0.0 = center, 0.5 = halfway to tip, -0.5 = halfway to other tip
            proxy_name: Source proxy name
            
        Returns:
            Dict with origin, normal_vector, span_axis, and slice position info
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Get span direction info
            span_info = self.detect_span_direction(proxy_name=proxy_name)
            if "error" in span_info:
                return span_info
            
            span_axis = span_info["span_axis"]
            body_center = span_info["body_center"]
            span_extent = span_info["span_extent"]
            
            # Compute origin at offset position
            axis_idx = {"x": 0, "y": 1, "z": 2}[span_axis]
            origin = list(body_center)
            origin[axis_idx] = body_center[axis_idx] + offset * span_extent * 0.5
            
            # Normal vector along span axis
            normal_vector = [0.0, 0.0, 0.0]
            normal_vector[axis_idx] = 1.0
            
            return {
                "origin": origin,
                "normal_vector": normal_vector,
                "normal_axis": span_axis,
                "offset": offset,
                "span_position": origin[axis_idx],
                "span_extent": span_extent,
                "body_center": body_center,
                "body_bounds": span_info["body_bounds"],
                "streamwise_axis": span_info["streamwise_axis"],
                "vertical_axis": span_info["vertical_axis"],
            }
            
        except Exception as e:
            return {"error": str(e)}

    def detect_wake_region(
        self, 
        velocity_deficit: float = 0.5,
        proxy_name: str = None
    ) -> dict:
        """
        Detect wake region based on velocity deficit, constrained to downstream of body.
        
        Wake is identified as the region where velocity magnitude is less than 
        a fraction of freestream velocity. To avoid including stagnation points
        and boundary layers, the search is spatially clipped to the downstream
        half of the domain (from 75% of body extent to the farfield exit).
        
        Uses detect_streamwise_direction to determine flow direction, then
        _get_body_bounds to find the trailing edge location.
        
        Args:
            velocity_deficit: Threshold as fraction of freestream (default 0.5 = 50%)
                             Lower values find deeper wake regions
            proxy_name: Data source
            
        Returns:
            Dict with wake_centroid, wake_bounds, freestream_velocity, streamwise, trailing_edge_coord
            
        Example:
            detect_wake_region()  # Find wake with 50% velocity deficit
            detect_wake_region(velocity_deficit=0.3)  # Find deeper wake (30% deficit)
            
        Usage for streamline seeding:
            wake = detect_wake_region()
            seed = compute_streamline_seed()
            create("StreamTracer", ...)  # Use seed parameters
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        original_source = simple.GetActiveSource()  # Save for restore
        
        try:
            # Get velocity statistics to determine freestream
            stats = self.field_statistics("velocity", proxy_name=proxy_name)
            if "error" in stats:
                return stats
            
            v_freestream = stats["magnitude"]["max"]
            v_threshold = velocity_deficit * v_freestream
            
            # Get streamwise direction to constrain search to downstream region
            streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
            streamwise = streamwise_result.get("streamwise", "x")
            
            # Get body bounds to know where "downstream" starts
            body_bounds, _ = self._get_body_bounds(proxy)
            
            # Determine streamwise axis and downstream clip plane
            axis_map = {"x": 0, "+x": 0, "-x": 0,
                        "y": 1, "+y": 1, "-y": 1,
                        "z": 2, "+z": 2, "-z": 2}
            stream_idx = axis_map.get(streamwise.lower(), 0)
            is_positive = not streamwise.startswith("-")
            
            body_extent = body_bounds[stream_idx * 2 + 1] - body_bounds[stream_idx * 2]
            
            if is_positive:
                trailing_edge = body_bounds[stream_idx * 2 + 1]
                # Clip origin: 25% upstream from trailing edge into the body
                clip_coord = trailing_edge - body_extent * 0.25
                normal = [0, 0, 0]
                normal[stream_idx] = 1.0  # keep downstream (+) side
            else:
                trailing_edge = body_bounds[stream_idx * 2]
                clip_coord = trailing_edge + body_extent * 0.25
                normal = [0, 0, 0]
                normal[stream_idx] = -1.0  # keep downstream (-) side
            
            origin = list(body_bounds[0::2])  # [xmin, ymin, zmin] as starting point
            origin[stream_idx] = clip_coord
            
            # Clip data to downstream region, then query velocity deficit there
            downstream_clip = simple.Clip(Input=proxy)
            downstream_clip.ClipType = 'Plane'
            downstream_clip.ClipType.Origin = origin
            downstream_clip.ClipType.Normal = normal
            downstream_clip.Invert = 0  # keep the normal side (downstream)
            simple.UpdatePipeline(proxy=downstream_clip)
            
            # Hide clip from view — this is just for analysis
            view = simple.GetActiveView()
            if view:
                try:
                    simple.Hide(downstream_clip, view)
                except:
                    pass
            
            # Get the clip proxy name for find_by_query
            clip_name = None
            for name, p in simple.GetSources().items():
                if p == downstream_clip:
                    clip_name = name[0]
                    break
            
            # Query velocity deficit in the downstream-only region using view-independent method
            try:
                centroid_result = self.find_by_threshold("Velocity", v_threshold, below=True, proxy_name=clip_name)
            finally:
                # Always clean up the temporary clip
                try:
                    simple.Delete(downstream_clip)
                except:
                    pass
            
            if "error" in centroid_result:
                # Fall back to global deficit query (maybe unusual geometry)
                centroid_result = self.find_by_threshold("Velocity", v_threshold, below=True, proxy_name=proxy_name)
            
            if "error" in centroid_result:
                if original_source:
                    simple.SetActiveSource(original_source)
                return {
                    "error": f"No wake region found with velocity < {velocity_deficit*100:.0f}% of freestream",
                    "freestream_velocity": v_freestream,
                    "threshold": v_threshold
                }
            
            if original_source:
                simple.SetActiveSource(original_source)
            
            return {
                "wake_centroid": centroid_result.get("location", centroid_result.get("centroid")),
                "wake_bounds": centroid_result.get("bounds"),
                "num_points": centroid_result.get("num_points", centroid_result.get("count", 0)),
                "freestream_velocity": v_freestream,
                "velocity_threshold": v_threshold,
                "velocity_deficit_fraction": velocity_deficit,
                "streamwise": streamwise,
                "trailing_edge_coord": trailing_edge
            }
            
        except Exception as e:
            return {"error": str(e)}

    def compute_streamline_seed(
        self,
        proxy_name: str = None
    ) -> dict:
        """
        Compute optimal streamline seed location and radius (ANALYSIS ONLY).
        
        Uses wake detection to find the best seed placement for visualizing
        wake flow structures. Falls back to body geometry if no wake detected.
        
        Returns:
            {center, radius, num_points, max_length} - use with create("StreamTracer")
            
        Example workflow:
            seed = compute_streamline_seed(proxy_name="MyData")
            create("StreamTracer", input_proxy="MyData")
            update_string_property("SeedType", "Point Cloud")  # IMPORTANT: set seed type first!
            update_sub_property("SeedType", "Center", seed["center"])
            update_sub_property("SeedType", "Radius", seed["radius"])
            update_sub_property("SeedType", "NumberOfPoints", seed["num_points"])
            update_float_property("MaximumStreamlineLength", seed["max_length"])
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Get data bounds
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            
            domain_diag = np.sqrt(
                (bounds[1] - bounds[0])**2 +
                (bounds[3] - bounds[2])**2 +
                (bounds[5] - bounds[4])**2
            )
            
            # Get body bounds for fallback
            body_bounds, body_diag = self._get_body_bounds(proxy)
            
            # Try wake detection
            wake_result = self.detect_wake_region(proxy_name=proxy_name)
            
            if wake_result and "wake_centroid" in wake_result:
                center = wake_result["wake_centroid"]
                
                # Compute radius from wake cross-stream extent
                if "wake_bounds" in wake_result and wake_result["wake_bounds"]:
                    wb = wake_result["wake_bounds"]
                    streamwise = wake_result.get("streamwise", "x")
                    wake_extents = [wb[1] - wb[0], wb[3] - wb[2], wb[5] - wb[4]]
                    axis_map = {"x": 0, "+x": 0, "-x": 0, "y": 1, "+y": 1, "-y": 1, "z": 2, "+z": 2, "-z": 2}
                    stream_idx = axis_map.get(streamwise.lower(), 0)
                    
                    cross_extents = [e for i, e in enumerate(wake_extents) if i != stream_idx and e > 1e-10]
                    radius = max(cross_extents) * 0.5 if cross_extents else body_diag * 0.1
                else:
                    radius = body_diag * 0.1
            else:
                # Fall back to seeding downstream of body
                # Get streamwise direction to know where "downstream" is
                streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
                streamwise = streamwise_result.get("streamwise", "+x")
                
                axis_map = {"x": 0, "+x": 0, "-x": 0, "y": 1, "+y": 1, "-y": 1, "z": 2, "+z": 2, "-z": 2}
                stream_idx = axis_map.get(streamwise.lower(), 0)
                is_positive = not streamwise.startswith("-")
                
                # Body center as starting point
                center = [
                    (body_bounds[0] + body_bounds[1]) / 2,
                    (body_bounds[2] + body_bounds[3]) / 2,
                    (body_bounds[4] + body_bounds[5]) / 2
                ]
                
                # Shift center downstream by 1.5x body extent in streamwise direction
                body_extent_streamwise = body_bounds[stream_idx * 2 + 1] - body_bounds[stream_idx * 2]
                if is_positive:
                    center[stream_idx] = body_bounds[stream_idx * 2 + 1] + body_extent_streamwise * 0.5
                else:
                    center[stream_idx] = body_bounds[stream_idx * 2] - body_extent_streamwise * 0.5
                
                # Radius based on cross-stream body extents
                body_extents = [
                    body_bounds[1] - body_bounds[0],
                    body_bounds[3] - body_bounds[2],
                    body_bounds[5] - body_bounds[4],
                ]
                cross_extents = [e for i, e in enumerate(body_extents) if i != stream_idx and e > 1e-10]
                radius = max(cross_extents) * 0.5 if cross_extents else body_diag * 0.1
            
            return {
                "center": center,
                "radius": float(radius),
                "num_points": 100,
                "max_length": float(domain_diag * 10),
            }
            
        except Exception as e:
            return {"error": str(e)}

    # NOTE: create_streamlines removed - use compute_streamline_seed then base create()

    def compute_body_center(
        self,
        proxy_name: str = None
    ) -> dict:
        """
        Compute body geometry center (ANALYSIS ONLY).
        
        Estimates the center of the body by clipping away farfield boundaries.
        Useful for placing slices through the body.
        
        Returns:
            {center, bounds, diagonal} - use center for slice origin
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            body_bounds, body_diag = self._get_body_bounds(proxy)
            
            center = [
                (body_bounds[0] + body_bounds[1]) / 2,
                (body_bounds[2] + body_bounds[3]) / 2,
                (body_bounds[4] + body_bounds[5]) / 2
            ]
            
            return {
                "center": center,
                "bounds": list(body_bounds),
                "diagonal": float(body_diag),
            }
            
        except Exception as e:
            return {"error": str(e)}

    def compute_slice_params(
        self,
        normal: str = "z",
        offset: float = 0.0,
        proxy_name: str = None
    ) -> dict:
        """
        Compute slice plane parameters based on body geometry (ANALYSIS ONLY).
        
        Args:
            normal: Slice normal direction ("x", "y", "z")
            offset: Offset from body center as fraction of body extent (-1 to 1)
            
        Returns:
            {origin, normal_vector} - use with create("Slice")
            
        Example workflow:
            params = compute_slice_params(normal="z", offset=0)
            create("Slice")
            update_sub_property("SliceType", "Origin", params["origin"])
            update_sub_property("SliceType", "Normal", params["normal_vector"])
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            body_bounds, _ = self._get_body_bounds(proxy)
            
            center = [
                (body_bounds[0] + body_bounds[1]) / 2,
                (body_bounds[2] + body_bounds[3]) / 2,
                (body_bounds[4] + body_bounds[5]) / 2
            ]
            
            axis_map = {"x": 0, "y": 1, "z": 2}
            axis_idx = axis_map.get(normal.lower(), 2)
            
            # Compute offset position
            extent = body_bounds[axis_idx * 2 + 1] - body_bounds[axis_idx * 2]
            origin = list(center)
            origin[axis_idx] = center[axis_idx] + offset * extent * 0.5
            
            normal_vector = [0.0, 0.0, 0.0]
            normal_vector[axis_idx] = 1.0
            
            return {
                "origin": origin,
                "normal_vector": normal_vector,
                "normal_axis": normal,
                "body_center": center,
                "body_bounds": list(body_bounds),
            }
            
        except Exception as e:
            return {"error": str(e)}

    def set_streamwise_view(self, proxy_name: str = None) -> dict:
        """
        Set camera to an isometric view oriented along the streamwise direction.
        
        Detects flow direction and positions camera so:
        - Streamwise direction is left-to-right
        - View is from above and to the side (isometric)
        
        Returns:
            Dict with view settings and detected streamwise direction
        """
        # Detect streamwise direction
        result = self.detect_streamwise_direction(proxy_name)
        if "error" in result:
            return result
        
        streamwise = result["streamwise"]
        
        # Get proxy bounds
        proxy = self._get_proxy(proxy_name)
        if proxy:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            cx = (bounds[0] + bounds[1]) / 2
            cy = (bounds[2] + bounds[3]) / 2
            cz = (bounds[4] + bounds[5]) / 2
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            distance = max(dx, dy, dz) * 2.0
        else:
            cx, cy, cz = 0, 0, 0
            distance = 5.0
        
        view = simple.GetActiveView()
        
        # Ensure we have a RenderView (not a chart view)
        if view is None or not hasattr(view, 'ResetCamera'):
            for v in simple.GetViews():
                if hasattr(v, 'ResetCamera'):
                    view = v
                    break
            else:
                view = simple.CreateRenderView()
            simple.SetActiveView(view)
        
        # Position camera based on streamwise direction
        # Goal: streamwise is left-to-right, slight elevation
        if streamwise in ["+x", "-x"]:
            # Flow along X - view from +Z+Y quadrant
            sign = 1 if streamwise == "+x" else -1
            pos = [cx - sign * distance * 0.3, cy + distance * 0.5, cz + distance * 0.8]
            up = [0, 1, 0]
        elif streamwise in ["+y", "-y"]:
            # Flow along Y - view from +X+Z quadrant
            sign = 1 if streamwise == "+y" else -1
            pos = [cx + distance * 0.8, cy - sign * distance * 0.3, cz + distance * 0.5]
            up = [0, 0, 1] if streamwise == "+y" else [0, 0, -1]
        else:  # +z or -z
            # Flow along Z - view from +X+Y quadrant
            sign = 1 if streamwise == "+z" else -1
            pos = [cx + distance * 0.8, cy + distance * 0.5, cz - sign * distance * 0.3]
            up = [0, 1, 0]
        
        view.CameraPosition = pos
        view.CameraFocalPoint = [cx, cy, cz]
        view.CameraViewUp = up
        view.CenterOfRotation = [cx, cy, cz]
        
        if proxy:
            view.ResetCamera(*bounds, False, 0.9)
        
        simple.Render(view)
        
        return {
            "status": "view_set",
            "streamwise": streamwise,
            "confidence": result["confidence"],
            "focal_point": [cx, cy, cz]
        }
    
    def rescale_color_map(self, proxy_name: str = None) -> dict:
        """
        Rescale the color map to the data range of the current proxy.
        
        Call this after coloring a proxy by a field to ensure the color map
        spans the actual data range.
        
        Args:
            proxy_name: Proxy to rescale. If None, uses active source.
            
        Returns:
            Dict with status
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        view = simple.GetActiveView()
        if view is None:
            return {"error": "No active view"}
        
        try:
            display = simple.GetDisplayProperties(proxy, view)
            if display is None:
                return {"error": "Proxy not displayed in view"}
            
            display.RescaleTransferFunctionToDataRange(True)
            simple.Render(view)
            return {"status": "rescaled", "proxy": proxy_name or "active"}
        except Exception as e:
            return {"error": str(e)}
    
    def set_scalar_bar_visibility(self, visible: bool = True, proxy_name: str = None) -> dict:
        """
        Show or hide the scalar bar (color legend) for a proxy.
        
        Args:
            visible: True to show, False to hide.
            proxy_name: Proxy whose scalar bar to modify. If None, uses active source.
            
        Returns:
            Dict with status
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        view = simple.GetActiveView()
        if view is None:
            return {"error": "No active view"}
        
        try:
            display = simple.GetDisplayProperties(proxy, view)
            if display is None:
                return {"error": "Proxy not displayed in view"}
            
            display.SetScalarBarVisibility(view, visible)
            simple.Render(view)
            return {"status": "visible" if visible else "hidden", "proxy": proxy_name or "active"}
        except Exception as e:
            return {"error": str(e)}
    
    def hide_all(self, delete_derived: bool = False) -> dict:
        """
        Hide all proxies in the pipeline.
        
        Call this before creating new visualizations to start with a clean view.
        Then use show_data_context() to show base geometry, and visualization
        tools will show their results.
        
        Args:
            delete_derived: If True, also delete all derived proxies (filters),
                keeping only original data readers. This frees GPU texture units
                but destroys any created visualizations. Use when running many
                sequential workflows to avoid texture exhaustion.
        
        Returns:
            Dict with count of hidden proxies
        """
        view = simple.GetActiveView()
        if view is None:
            return {"status": "no_view", "hidden": 0}
        
        count = 0
        deleted = 0
        
        # Collect proxies first (can't modify during iteration)
        all_proxies = list(simple.GetSources().items())
        
        for name, proxy in all_proxies:
            try:
                simple.Hide(proxy, view)
                count += 1
            except:
                pass
        
        if delete_derived:
            # Delete all non-reader proxies to free resources
            # Readers have names like XMLMultiBlockDataReader, EnSightReader, etc.
            reader_types = {
                'XMLMultiBlockDataReader', 'XMLUnstructuredGridReader', 
                'XMLStructuredGridReader', 'XMLPolyDataReader', 'XMLImageDataReader',
                'EnSightReader', 'PVDReader', 'OpenFOAMReader', 'CGNSReader',
                'ExodusIIReader', 'LegacyVTKReader', 'STLReader', 'OBJReader',
                'PLYReader', 'CSVReader', 'POpenFOAMReader', 'NetCDFReader'
            }
            
            for name, proxy in all_proxies:
                proxy_type = proxy.__class__.__name__
                if proxy_type not in reader_types:
                    try:
                        simple.Delete(proxy)
                        deleted += 1
                    except:
                        pass
        
        simple.Render(view)
        return {"status": "hidden_all", "count": count, "deleted": deleted}

    def save_screenshot(
        self,
        filename: str,
        width: int = 1024,
        height: int = 768
    ) -> dict:
        """
        Save screenshot of the current view to a file.
        
        Saves the active view (RenderView or ChartView) to the specified file.
        Supports PNG, JPG, PDF, and other formats based on file extension.
        
        Args:
            filename: Output filename (e.g., "output/result.png")
            width: Image width in pixels (default: 1024)
            height: Image height in pixels (default: 768)
            
        Returns:
            Dict with filename and status
        """
        # Check if chart views were created - use them in order (FIFO)
        chart_views = getattr(self, '_chart_view_queue', [])
        if chart_views:
            view = chart_views.pop(0)  # Take first (oldest)
        else:
            view = simple.GetActiveView()
        
        if view is None:
            return {"error": "No active view"}
        
        try:
            # Ensure directory exists
            import os
            dirname = os.path.dirname(filename)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            
            simple.Render(view)
            simple.SaveScreenshot(filename, view, ImageResolution=[width, height])
            return {"status": "saved", "filename": filename, "width": width, "height": height}
        except Exception as e:
            return {"error": str(e)}
    
    def show_data_context(
        self,
        proxy_name: str = None,
        opacity: float = 0.3,
        color: list[float] = None,
        representation: str = None,
        clip_farfield: bool = True,
        clip_margin: float = 0.05
    ) -> dict:
        """
        Show body surface as context geometry without obscuring visualizations.
        
        For volumetric CFD data (unstructured grids, multiblock), extracts the 
        external surface and clips away farfield domain boundaries, leaving
        just the body surface. Shows it as a semi-transparent solid gray surface.
        
        For surface data (PolyData), shows as semi-transparent surface directly.
        
        The body surface provides geometric context (wing shape, vehicle body)
        while flow visualization filters (isosurfaces, streamlines, slices)
        render on top at full opacity.
        
        Workflow:
            hide_all()                    # Clear view
            show_data_context()           # Body surface as gray context
            vortex = compute_vortex_field(...)  # Compute field
            create("Contour", ...)        # Flow feature on top
            focus_on("Contour1")          # Frame the result
        
        Args:
            proxy_name: Data source to show. If None, shows first data reader found.
            opacity: Transparency level (0.0-1.0). Default 0.3 (body visible but not dominant).
            color: RGB color [r, g, b] each 0-1. If None, uses light gray [0.7, 0.7, 0.7].
            representation: Override representation type. If None, auto-detects.
            clip_farfield: If True, clips away farfield boundaries for volumetric data.
                          The farfield faces sit at the domain bounding box extremes.
                          Default True.
            clip_margin: Fraction of domain extent to clip inward from each face (0-0.5).
                        Default 0.05 (5%). Increase if farfield faces remain visible.
            
        Returns:
            Dict with proxy shown, context filter names, and display settings
        """
        view = simple.GetActiveView()
        
        # Ensure we have a RenderView (not a chart view)
        if view is None or not hasattr(view, 'ResetCamera'):
            for v in simple.GetViews():
                if hasattr(v, 'ResetCamera'):
                    view = v
                    break
            else:
                view = simple.CreateRenderView()
            simple.SetActiveView(view)
        
        # Find the data source
        proxy = None
        if proxy_name:
            proxy = self._get_proxy(proxy_name)
        else:
            for name, p in simple.GetSources().items():
                if any(x in name[0] for x in ['XMLMultiBlockDataReader', 'XMLUnstructuredGridReader', 
                                               'OpenFOAMReader', 'EnSightReader', 'CGNSReader']):
                    proxy = p
                    proxy_name = name[0]
                    break
        
        if proxy is None:
            return {"error": "No data source found"}
        
        # Detect data type
        is_volumetric = False
        try:
            di = proxy.GetDataInformation()
            data_class = di.GetDataClassName()
            is_volumetric = data_class in [
                "vtkUnstructuredGrid", "vtkMultiBlockDataSet",
                "vtkPartitionedDataSet", "vtkPartitionedDataSetCollection"
            ]
        except:
            pass
        
        context_proxy = proxy  # What we'll ultimately show
        intermediate_filters = []  # Track filters to hide
        
        if is_volumetric:
            try:
                # Step 1: Extract external surface from volume mesh
                surface = simple.ExtractSurface(Input=proxy)
                simple.UpdatePipeline(proxy=surface)
                intermediate_filters.append(surface)
                
                context_proxy = surface
                
                # Step 2: Clip away farfield domain boundaries
                if clip_farfield:
                    bounds = proxy.GetDataInformation().GetBounds()
                    # Shrink bounds inward by margin fraction
                    dx = (bounds[1] - bounds[0]) * clip_margin
                    dy = (bounds[3] - bounds[2]) * clip_margin
                    dz = (bounds[5] - bounds[4]) * clip_margin
                    
                    clip_bounds = [
                        bounds[0] + dx, bounds[1] - dx,
                        bounds[2] + dy, bounds[3] - dy,
                        bounds[4] + dz, bounds[5] - dz
                    ]
                    
                    clip = simple.Clip(Input=surface)
                    clip.ClipType = 'Box'
                    clip.ClipType.Bounds = clip_bounds
                    clip.Invert = 1  # Keep inside the box
                    simple.UpdatePipeline(proxy=clip)
                    intermediate_filters.append(clip)
                    
                    context_proxy = clip
                    
            except Exception as e:
                # Fall back to showing raw proxy as surface
                context_proxy = proxy
                intermediate_filters = []
            
            # Use Surface representation for extracted body
            if representation is None:
                representation = "Surface"
        else:
            # Surface data (PolyData) - show directly
            if representation is None:
                representation = "Surface"
        
        # Hide intermediate filters
        for f in intermediate_filters:
            if f != context_proxy:
                try:
                    simple.Hide(f, view)
                except:
                    pass
        
        # Hide the original reader
        try:
            simple.Hide(proxy, view)
        except:
            pass
        
        # Show the context proxy
        display = simple.Show(context_proxy, view)
        
        try:
            display.SetRepresentationType(representation)
        except:
            pass
        
        # Style: semi-transparent solid gray
        if color is None:
            color = [0.7, 0.7, 0.7]
        try:
            display.Opacity = opacity
            display.DiffuseColor = color
            display.AmbientColor = color
        except AttributeError:
            pass
        simple.ColorBy(display, None)  # Solid color, no scalar bar
        
        simple.Render(view)
        
        # Get filter names for reference
        context_name = None
        for name, p in simple.GetSources().items():
            if p == context_proxy:
                context_name = name[0]
                break
        
        return {
            "status": "context_shown",
            "proxy": proxy_name,
            "context_filter": context_name,
            "representation": representation,
            "opacity": opacity,
            "color": color,
            "clipped_farfield": clip_farfield and is_volumetric,
        }
    
    # Helper methods
    
    # Common field name aliases
    FIELD_ALIASES = {
        "pressure": "p",
        "Pressure": "p",
        "velocity": "Velocity",
        "U": "Velocity",
        "density": "Density",
        "rho": "Density",
    }
    
    def _resolve_field_name(self, field_name: str, proxy) -> str:
        """Resolve field name aliases and find actual field name."""
        # First check if exact name exists using ParaView's data information API
        simple.UpdatePipeline(proxy=proxy)
        
        # Use GetDataInformation for array names - works for all proxy types
        di = proxy.GetDataInformation()
        point_info = di.GetPointDataInformation()
        cell_info = di.GetCellDataInformation()
        
        # Check point data
        for i in range(point_info.GetNumberOfArrays()):
            name = point_info.GetArrayInformation(i).GetName()
            if name == field_name:
                return field_name
            if name.lower() == field_name.lower():
                return name
        
        # Check cell data
        for i in range(cell_info.GetNumberOfArrays()):
            name = cell_info.GetArrayInformation(i).GetName()
            if name == field_name:
                return field_name
            if name.lower() == field_name.lower():
                return name
        
        # Try alias
        if field_name in self.FIELD_ALIASES:
            return self._resolve_field_name(self.FIELD_ALIASES[field_name], proxy)
        
        return field_name  # Return original if not found
    
    def _get_proxy(self, proxy_name: str = None):
        """Get proxy by name or active source."""
        if proxy_name:
            return simple.FindSource(proxy_name)
        return simple.GetActiveSource()
    
    def _get_array(self, proxy, field_name: str):
        """Get VTK array as numpy array."""
        from vtk.util.numpy_support import vtk_to_numpy
        
        simple.UpdatePipeline(proxy=proxy)
        data = proxy.GetClientSideObject().GetOutputDataObject(0)
        
        merge = None
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            data = merge.GetClientSideObject().GetOutputDataObject(0)
        
        arr = data.GetPointData().GetArray(field_name)
        if arr is None:
            arr = data.GetCellData().GetArray(field_name)
        
        if arr is None:
            if merge:
                simple.Delete(merge)
            return None, None
        
        # Copy the array before deleting merge
        result = vtk_to_numpy(arr).copy()
        
        if merge:
            simple.Delete(merge)
        
        return result, data


    def compute_boundary_layer_profile(self, proxy=None, x_location: float = 0.5, 
                                        probe_length: float = None, proxy_name: str = None) -> dict:
        """
        Compute boundary layer profile data at a given streamwise location.
        
        Probes normal to the body surface and computes BL quantities using
        multiple edge detection criteria (99% velocity, Haase diagnostic).
        
        Args:
            proxy: Data proxy (default: active source)
            x_location: Streamwise location - absolute or fraction (0-1) of chord
            probe_length: Probe distance (default: 30% of chord)
            proxy_name: Proxy name for span detection
            
        Returns:
            Dict with profile data (y, u, u_normalized) and BL quantities
            (delta, delta_star, theta, shape_factor, etc.)
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        if proxy is None:
            proxy = simple.GetActiveSource()
        if proxy is None:
            return {"error": "No data source found"}
        
        if proxy_name is None:
            proxy_name = proxy.GetGlobalIDAsString()
        
        # Merge blocks
        merge = simple.MergeBlocks(Input=proxy)
        simple.UpdatePipeline(proxy=merge)
        
        # Get body bounds
        body_bounds, _ = self._get_body_bounds(proxy)
        
        # Extract and clip surface to body region
        surface = simple.ExtractSurface(Input=merge)
        simple.UpdatePipeline(proxy=surface)
        
        clip = simple.Clip(Input=surface)
        clip.ClipType = 'Box'
        clip.ClipType.Bounds = [
            body_bounds[0] - 0.01, body_bounds[1] + 0.01,
            body_bounds[2] - 0.01, body_bounds[3] + 0.01,
            body_bounds[4] - 0.01, body_bounds[5] + 0.01
        ]
        clip.Invert = 1
        simple.UpdatePipeline(proxy=clip)
        
        body_surface = simple.ExtractSurface(Input=clip)
        simple.UpdatePipeline(proxy=body_surface)
        
        normals_filter = simple.SurfaceNormals(Input=body_surface)
        simple.UpdatePipeline(proxy=normals_filter)
        
        data = normals_filter.GetClientSideObject().GetOutputDataObject(0)
        points = vtk_to_numpy(data.GetPoints().GetData())
        normal_arr = vtk_to_numpy(data.GetPointData().GetArray('Normals'))
        
        def cleanup():
            simple.Delete(normals_filter)
            simple.Delete(body_surface)
            simple.Delete(clip)
            simple.Delete(surface)
            simple.Delete(merge)
        
        if len(points) == 0:
            cleanup()
            return {"error": "No body surface points found"}
        
        # Detect geometry orientation
        span_info = self.detect_span_direction(proxy_name=proxy_name)
        span_axis = span_info.get("span_axis", "y")
        vertical_axis = span_info.get("vertical_axis", "z")
        streamwise_axis = span_info.get("streamwise_axis", "x")
        body_center = np.array(span_info["body_center"])
        
        axis_map = {"x": 0, "y": 1, "z": 2}
        span_idx = axis_map[span_axis]
        vert_idx = axis_map[vertical_axis]
        stream_idx = axis_map[streamwise_axis]
        
        # Geometry extents
        stream_min = body_bounds[stream_idx * 2]
        stream_max = body_bounds[stream_idx * 2 + 1]
        chord = stream_max - stream_min
        
        span_min = body_bounds[span_idx * 2]
        span_max = body_bounds[span_idx * 2 + 1]
        span_extent = span_max - span_min
        
        vert_min = body_bounds[vert_idx * 2]
        vert_max = body_bounds[vert_idx * 2 + 1]
        thickness = vert_max - vert_min
        vert_center = body_center[vert_idx]
        
        # Default probe_length
        if probe_length is None:
            probe_length = 0.3 * chord
        
        # Convert x_location to absolute
        if 0 <= x_location <= 1 and chord > 1:
            x_abs = stream_min + x_location * chord
        else:
            x_abs = x_location
        
        # Tolerances
        x_tolerance = 0.1 * chord
        span_tolerance = 0.2 * span_extent
        symmetry_offset = 0.05 * span_extent
        
        # Find surface point on upper surface
        mask = (
            (np.abs(points[:,stream_idx] - x_abs) < x_tolerance) &
            (np.abs(points[:,span_idx] - span_min) < span_tolerance) &
            (points[:,vert_idx] > vert_center)
        )
        candidates = np.where(mask)[0]
        
        if len(candidates) == 0:
            mask = np.abs(points[:,stream_idx] - x_abs) < 0.2 * chord
            candidates = np.where(mask)[0]
        
        if len(candidates) == 0:
            cleanup()
            return {"error": f"No surface point found near x={x_location}"}
        
        # Pick closest point
        x_diffs = np.abs(points[candidates, stream_idx] - x_abs)
        best_idx = candidates[np.argmin(x_diffs)]
        
        surface_point = points[best_idx].copy()
        surface_normal = normal_arr[best_idx].copy()
        
        # Ensure normal points outward
        from_body_center = surface_point - body_center
        if np.dot(surface_normal, from_body_center) < 0:
            surface_normal = -surface_normal
        
        # Offset from symmetry plane
        if surface_point[span_idx] < span_min + symmetry_offset:
            surface_point[span_idx] = span_min + symmetry_offset
        
        # Create line probe
        end_point = surface_point + probe_length * surface_normal
        
        line = simple.PlotOverLine(Input=merge)
        line.Point1 = surface_point.tolist()
        line.Point2 = end_point.tolist()
        line.Resolution = 200
        simple.UpdatePipeline(proxy=line)
        
        line_data = line.GetClientSideObject().GetOutputDataObject(0)
        if line_data.GetNumberOfPoints() == 0:
            simple.Delete(line)
            cleanup()
            return {"error": "Line probe returned no points"}
        
        y = vtk_to_numpy(line_data.GetPointData().GetArray('arc_length'))
        velocity = vtk_to_numpy(line_data.GetPointData().GetArray('Velocity'))
        u = np.linalg.norm(velocity, axis=1)
        
        simple.Delete(line)
        cleanup()
        
        # Handle NaN at wall (no-slip)
        n_nan = np.sum(np.isnan(u))
        if n_nan > 0:
            first_valid = np.where(~np.isnan(u))[0]
            if len(first_valid) > 0 and first_valid[0] < len(u) // 4:
                u[np.isnan(u)] = 0.0
            else:
                return {"error": f"Probe has {n_nan} NaN values away from wall"}
        
        if len(y) < 5:
            return {"error": "Insufficient data points"}
        
        # Edge velocity (local max, not freestream)
        u_edge = np.max(u)
        u_edge_idx = np.argmax(u)
        u_normalized = u / u_edge if u_edge > 0 else u
        
        # Edge detection: 99% criterion
        delta_99_idx = np.where(u_normalized[:u_edge_idx+1] >= 0.99)[0]
        delta_99 = y[delta_99_idx[0]] if len(delta_99_idx) > 0 else y[u_edge_idx]
        
        # Edge detection: Haase diagnostic
        if len(y) > 2:
            du_dy = np.abs(np.gradient(u, y))
            diagnostic = y * du_dy
            search_start = max(3, len(diagnostic) // 10)
            search_end = min(u_edge_idx + 1, len(diagnostic))
            if search_start < search_end:
                max_idx = search_start + np.argmax(diagnostic[search_start:search_end])
                delta_haase = 1.936 * y[max_idx]
            else:
                delta_haase = delta_99
        else:
            delta_haase = delta_99
        
        # Combined delta
        if abs(delta_99 - delta_haase) / max(delta_99, delta_haase, 1e-10) < 0.5:
            delta = (delta_99 + delta_haase) / 2
            edge_method = "average(99%, Haase)"
        else:
            delta = min(delta_99, delta_haase)
            edge_method = f"min(99%={delta_99:.4f}, Haase={delta_haase:.4f})"
        
        # Integral quantities within BL
        bl_mask = y <= delta
        y_bl = y[bl_mask]
        u_bl = u_normalized[bl_mask]
        
        delta_star = np.trapz(1 - u_bl, y_bl) if len(y_bl) > 1 else 0.0
        theta = np.trapz(u_bl * (1 - u_bl), y_bl) if len(y_bl) > 1 else 0.0
        shape_factor = delta_star / theta if theta > 1e-10 else float('nan')
        
        # Span location
        span_location = surface_point[span_idx]
        span_fraction = (span_location - span_min) / span_extent if span_extent > 0 else 0
        
        return {
            "y": y.tolist(),
            "u": u.tolist(),
            "u_normalized": u_normalized.tolist(),
            "u_edge": float(u_edge),
            "u_edge_idx": int(u_edge_idx),
            "delta": float(delta),
            "delta_99": float(delta_99),
            "delta_haase": float(delta_haase),
            "edge_method": edge_method,
            "delta_star": float(delta_star),
            "theta": float(theta),
            "shape_factor": float(shape_factor),
            "surface_point": surface_point.tolist(),
            "surface_normal": surface_normal.tolist(),
            "x_location": x_location,
            "x_absolute": float(x_abs),
            "x_over_chord": float(x_abs / chord) if chord > 0 else float(x_abs),
            "span_location": float(span_location),
            "span_fraction": float(span_fraction),
            "geometry": {
                "chord": float(chord),
                "span_extent": float(span_extent),
                "thickness": float(thickness),
                "streamwise_axis": streamwise_axis,
                "span_axis": span_axis,
                "vertical_axis": vertical_axis
            },
            "probe_length": float(probe_length)
        }
