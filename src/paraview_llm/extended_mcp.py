"""
Extended ParaViewMCP

Extends trame-llm's ParaViewMCP with query and analysis tools.
These additions could be contributed upstream to trame-llm.
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


class ExtendedParaViewMCP:
    """
    Wraps ParaViewMCP and adds analysis/query tools.
    
    Usage:
        from trame_llm.paraview import ParaViewMCP
        from paraview_llm.extended_mcp import ExtendedParaViewMCP
        
        base_mcp = ParaViewMCP(app)
        extended = ExtendedParaViewMCP(base_mcp)
        
        llm_client.register_mcp(extended)
    """
    
    def __init__(self, paraview_mcp):
        self._base = paraview_mcp
        self.base_mcp = paraview_mcp  # Also expose as base_mcp for convenience
    
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
        data = proxy.GetClientSideObject().GetOutput()
        
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
        data = proxy.GetClientSideObject().GetOutput()
        
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
    
    @property
    def mcp(self):
        """Return combined MCP definition with base + extended tools."""
        base_mcp = self._base.mcp
        
        # Add our tools to the base tools
        extended_tools = [
            # Data validation and characterization (call first!)
            self.characterize_dataset,
            self.ensure_velocity_vector,
            self.validate_for_analysis,
            # Query and selection
            self.query_select,
            self.find_by_query,
            self.get_selection_info,
            # Field analysis
            self.find_minimum,
            self.find_maximum,
            self.find_high_gradient,
            self.field_statistics,
            self.field_histogram,
            # Force computation
            self.compute_forces,
            # Charts
            self.create_histogram_chart,
            self.create_force_distribution_chart,
            # Visualization
            self.create_vortex_isosurface,
            # Flow detection
            self.detect_streamwise_direction,
            self.detect_wake_region,
            # Camera/view control
            self.set_view,
            self.set_streamwise_view,
            self.hide_all,
            self.show_data_context,
        ]
        
        return {
            "name": base_mcp["name"],
            "instructions": base_mcp["instructions"] + """
                
                Additional CFD tools (always specify proxy_name for explicit input):
                
                DATA VALIDATION (call first with new datasets!):
                - characterize_dataset: Analyze CFD data to determine simulation type, available fields,
                  and applicable analysis tools. Returns incompressible/compressible, turbulent/laminar,
                  resolved field mappings, and recommendations.
                - ensure_velocity_vector: Create 3-component velocity vector from u,v,w components.
                  Required before vortex detection or streamlines if velocity is stored as components.
                - validate_for_analysis: Check if dataset has required fields for specific analysis
                  (vortex, forces, wake, streamlines). Returns missing fields and suggestions.
                
                ANALYSIS (return data, no visualization):
                - find_minimum: Find location of minimum field value (stagnation points)
                - find_maximum: Find location of maximum field value (freestream)
                - find_high_gradient: Find max gradient location (shear layers, wakes)
                - find_by_query: Find centroid of points matching a query expression
                - field_statistics: Get min/max/mean/std of a field
                - query_select: Count points/cells matching expression (analysis only)
                - get_selection_info: Get info about current selection
                - detect_wake_region: Find wake using velocity deficit criterion
                - detect_streamwise_direction: Detect principal flow direction from velocity
                - compute_forces: Integrate pressure for drag/lift coefficients
                
                VISUALIZATION:
                - create_vortex_isosurface: Visualize vortical structures. Methods:
                    method="q_criterion" (default): Q = 0.5*(||Ω||² - ||S||²), positive Q = vortex
                    method="vorticity": Vorticity magnitude, includes shear layers
                    method="lambda2": Second eigenvalue of S²+Ω², negative λ2 = vortex core
                    method="swirling_strength": Imaginary eigenvalues of ∇u
                    method="helicity": Normalized helicity |Hn|, identifies helical vortices
                
                For Slice and StreamTracer, use base tools (see ontology recipes):
                - base__create("Slice") then configure with update_sub_property
                - base__create("StreamTracer") then configure seed with update_sub_property
                
                VISIBILITY CONTROL:
                - hide_all: Hide all proxies - call first for clean slate
                - show_data_context: Extract and show body surface as semi-transparent gray context.
                  For volumetric CFD data, extracts the external surface and clips away farfield 
                  domain boundaries, leaving just the body shape visible as context geometry.
                  Always call after hide_all() and before creating visualizations.
                  Workflow: hide_all() → show_data_context() → create filter → focus_on(filter_name)
                
                CAMERA CONTROL:
                - set_view: Set camera to standard view (front/back/top/side/iso)
                - set_streamwise_view: Auto-detect flow direction and set optimal view
            """,
            "tools": base_mcp["tools"] + extended_tools,
            "resources": base_mcp.get("resources", {}),
        }
    
    # =========================================================================
    # DATA VALIDATION AND CHARACTERIZATION
    # =========================================================================
    
    # Cache for body bounds to avoid repeated ExtractSurface + Clip creation
    _body_bounds_cache = {}
    
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
    
    def _invalidate_body_bounds(self):
        """Clear cached body bounds (call if data changes)."""
        self._body_bounds_cache.clear()
    
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
            raw_data = proxy.GetClientSideObject().GetOutput()
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
                    "create_vortex_isosurface",
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
                raw_data = proxy.GetClientSideObject().GetOutput()
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
            data = proxy.GetClientSideObject().GetOutput()
            
            if data is None:
                return {"error": "No data available from proxy"}
            
            # Check if multiblock and merge if needed
            if data.IsA("vtkMultiBlockDataSet"):
                merge_input = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge_input)
                data = merge_input.GetClientSideObject().GetOutput()
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
            result_data = thresh.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if result_data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=thresh)
                simple.UpdatePipeline(proxy=merge)
                result_data = merge.GetClientSideObject().GetOutput()
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
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                merged_data = merge.GetClientSideObject().GetOutput()
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
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutput()
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
            
            data = extracted.GetClientSideObject().GetOutput()
            
            # Handle multiblock
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=extracted)
                simple.UpdatePipeline(proxy=merge)
                data = merge.GetClientSideObject().GetOutput()
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
            data = proxy.GetClientSideObject().GetOutput()
            
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
            data = proxy.GetClientSideObject().GetOutput()
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
            
            surf_data = normals.GetClientSideObject().GetOutput()
            
            # Handle multiblock by merging
            if surf_data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=normals)
                simple.UpdatePipeline(proxy=merge)
                surf_data = merge.GetClientSideObject().GetOutput()
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
                    orig_data = proxy.GetClientSideObject().GetOutput()
                    if orig_data.IsA("vtkMultiBlockDataSet"):
                        orig_data = orig_data.GetBlock(0)
                    vel_array = orig_data.GetPointData().GetArray("Velocity")
                
                if vel_array is not None:
                    vel = vtk_to_numpy(vel_array)
                    freestream_velocity = float(np.max(np.linalg.norm(vel, axis=1)))
                else:
                    freestream_velocity = 1.0
            
            if reference_area is None:
                # Use frontal area (projected area perpendicular to streamwise)
                bounds = surf_data.GetBounds()
                if drag_idx == 0:  # streamwise = x
                    reference_area = (bounds[3] - bounds[2]) * (bounds[5] - bounds[4])
                elif drag_idx == 1:  # streamwise = y
                    reference_area = (bounds[1] - bounds[0]) * (bounds[5] - bounds[4])
                else:  # streamwise = z
                    reference_area = (bounds[1] - bounds[0]) * (bounds[3] - bounds[2])
            
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
    
    def create_histogram_chart(
        self,
        field: str,
        num_bins: int = 20,
        proxy_name: str = None
    ) -> dict:
        """
        Create a histogram chart showing field value distribution.
        
        Uses ParaView's Histogram filter and BarChartView.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with chart info and statistics
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            field_name = self._resolve_field_type(field, proxy)
            
            # Merge if multiblock
            simple.UpdatePipeline(proxy=proxy)
            data = proxy.GetClientSideObject().GetOutput()
            if data.IsA("vtkMultiBlockDataSet"):
                merge = simple.MergeBlocks(Input=proxy)
                simple.UpdatePipeline(proxy=merge)
                hist_input = merge
            else:
                merge = None
                hist_input = proxy
            
            # Create histogram
            hist = simple.Histogram(Input=hist_input)
            hist.SelectInputArray = ['POINTS', field_name]
            hist.BinCount = num_bins
            
            # Check if vector - use magnitude
            arr, _ = self._get_array(proxy, field_name)
            if arr is not None and arr.ndim > 1 and arr.shape[1] > 1:
                hist.Component = 'Magnitude'
                display_name = f"{field_name} Magnitude"
            else:
                display_name = field_name
            
            simple.UpdatePipeline(proxy=hist)
            
            # Create bar chart view
            chart_view = simple.CreateBarChartView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Distribution of {display_name}'
            
            display = simple.Show(hist, chart_view)
            simple.Render(chart_view)
            
            # Store chart view for screenshot capture
            self._last_chart_view = chart_view
            
            # Get statistics
            if arr is not None:
                if arr.ndim > 1 and arr.shape[1] > 1:
                    arr = np.linalg.norm(arr, axis=1)
                stats = {
                    "min": float(arr.min()),
                    "max": float(arr.max()),
                    "mean": float(arr.mean()),
                    "std": float(arr.std()),
                }
            else:
                stats = {}
            
            # Cleanup merge if created
            if merge:
                simple.Delete(merge)
            
            return {
                "status": "created",
                "chart_type": "histogram",
                "field": display_name,
                "num_bins": num_bins,
                **stats
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
        Create a chart showing accumulated force distribution along an axis.
        
        Integrates pressure forces on body surfaces and shows:
        - Sectional force: Local force contribution per station
        - Accumulated force: Cumulative sum along the distribution axis
        
        Useful for spanwise loading, chordwise pressure distribution, etc.
        
        Args:
            force_axis: Force component direction:
                - "auto" or "streamwise" or "drag": Auto-detect streamwise (drag direction)
                - "lift": Perpendicular to streamwise (typically y)
                - "x", "y", "z": Explicit axis
            distribution_axis: Axis to distribute along:
                - "auto" or "streamwise": Along flow direction (chordwise)
                - "span": Perpendicular to flow, largest extent (spanwise)
                - "x", "y", "z": Explicit axis
            num_bins: Number of stations along distribution axis (default: 40)
            proxy_name: Name of proxy, or None for active source
            
        Returns:
            Dict with chart info and force data
            
        Examples:
            # Chordwise drag distribution (auto-detect flow direction)
            create_force_distribution_chart(force_axis="drag", distribution_axis="streamwise")
            
            # Spanwise lift distribution
            create_force_distribution_chart(force_axis="lift", distribution_axis="span")
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            
            # Auto-detect streamwise and span directions if needed
            streamwise_axis = None
            span_axis = None
            
            if force_axis in ("auto", "streamwise", "drag") or distribution_axis in ("auto", "streamwise", "span"):
                streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
                if "error" in streamwise_result:
                    return {"error": f"Could not detect streamwise direction: {streamwise_result['error']}"}
                
                streamwise = streamwise_result["streamwise"]  # e.g., "+x", "-y"
                streamwise_axis = streamwise[-1].lower()  # "x", "y", or "z"
                
                # Detect span: perpendicular axis with largest domain extent
                bounds = proxy.GetDataInformation().GetBounds()
                extents = {
                    "x": bounds[1] - bounds[0],
                    "y": bounds[3] - bounds[2],
                    "z": bounds[5] - bounds[4],
                }
                # Find largest extent among non-streamwise axes
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                span_axis = max(perp_axes, key=lambda a: extents[a])
            
            # Resolve force_axis
            if force_axis in ("auto", "streamwise", "drag"):
                force_axis = streamwise_axis
            elif force_axis == "lift":
                # Lift is perpendicular to streamwise, typically vertical (y) or the non-span perp axis
                perp_axes = [a for a in ["x", "y", "z"] if a != streamwise_axis]
                # Prefer y for lift if available, otherwise use the non-span axis
                if "y" in perp_axes:
                    force_axis = "y"
                else:
                    force_axis = [a for a in perp_axes if a != span_axis][0] if span_axis else perp_axes[0]
            
            # Resolve distribution_axis
            if distribution_axis in ("auto", "streamwise"):
                distribution_axis = streamwise_axis
            elif distribution_axis == "span":
                distribution_axis = span_axis
            
            # Merge if multiblock
            data = proxy.GetClientSideObject().GetOutput()
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
            
            surf_data = normals_filter.GetClientSideObject().GetOutput()
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
                
                # Area
                if cell.GetCellType() == 5:  # Triangle
                    v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                elif cell.GetCellType() == 9:  # Quad
                    v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
                    areas[i] = 0.5 * np.linalg.norm(np.cross(v1, v2))
                
                # Cell pressure
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
            
            if body_mask.sum() == 0:
                simple.Delete(normals_filter)
                simple.Delete(surface)
                if merge_input != proxy:
                    simple.Delete(merge_input)
                return {"error": "No body cells found (all cells at boundaries)"}
            
            # Axis mapping
            axis_map = {"x": 0, "y": 1, "z": 2}
            force_idx = axis_map.get(force_axis.lower(), 0)
            dist_idx = axis_map.get(distribution_axis.lower(), 0)
            
            # Local force = -p * n_i * dA
            force_per_cell = -cell_pressure * surf_normals[:, force_idx] * areas
            
            pos_body = centers[body_mask, dist_idx]
            force_body = force_per_cell[body_mask]
            
            # Bin by position
            pos_min, pos_max = pos_body.min(), pos_body.max()
            bin_edges = np.linspace(pos_min, pos_max, num_bins + 1)
            bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
            
            binned_force = np.zeros(num_bins)
            for i in range(num_bins):
                mask = (pos_body >= bin_edges[i]) & (pos_body < bin_edges[i+1])
                binned_force[i] = force_body[mask].sum()
            
            accumulated = np.cumsum(binned_force)
            
            # Write CSV for plotting
            import tempfile
            import os
            csv_path = os.path.join(tempfile.gettempdir(), 'force_distribution.csv')
            with open(csv_path, 'w') as f:
                f.write('Position,Sectional_Force,Accumulated_Force\n')
                for i in range(num_bins):
                    f.write(f'{bin_centers[i]:.6f},{binned_force[i]:.8f},{accumulated[i]:.8f}\n')
            
            # Create XY plot
            table = simple.CSVReader(FileName=[csv_path])
            simple.UpdatePipeline(proxy=table)
            
            force_names = {"x": "Drag", "y": "Lift", "z": "Side Force"}
            force_name = force_names.get(force_axis.lower(), "Force")
            
            chart_view = simple.CreateXYPlotView()
            chart_view.ViewSize = [800, 400]
            chart_view.ChartTitle = f'Accumulated {force_name} Distribution'
            chart_view.BottomAxisTitle = f'{distribution_axis.upper()} Position'
            chart_view.LeftAxisTitle = f'{force_name}'
            
            display = simple.Show(table, chart_view)
            display.XArrayName = 'Position'
            display.UseIndexForXAxis = 0
            display.SeriesVisibility = ['Accumulated_Force', 'Sectional_Force']
            display.SeriesColor = ['Accumulated_Force', '0', '0', '0.8', 'Sectional_Force', '0.8', '0', '0']
            display.SeriesLineThickness = ['Accumulated_Force', '2', 'Sectional_Force', '2']
            
            simple.Render(chart_view)
            
            # Store chart view for screenshot capture
            self._last_chart_view = chart_view
            
            # Cleanup
            simple.Delete(normals_filter)
            simple.Delete(surface)
            if merge_input != proxy:
                simple.Delete(merge_input)
            
            # Find key statistics from the distribution
            peak_bin = int(np.argmax(np.abs(binned_force)))
            peak_position = float(bin_centers[peak_bin])
            peak_force = float(binned_force[peak_bin])
            
            # Find where 50% of total force is reached
            total = accumulated[-1]
            half_idx = int(np.searchsorted(np.abs(accumulated), np.abs(total) * 0.5))
            half_position = float(bin_centers[min(half_idx, num_bins-1)])
            
            # Find steepest gradient (biggest change between bins)
            gradients = np.diff(accumulated)
            steepest_bin = int(np.argmax(np.abs(gradients)))
            steepest_position = float(bin_centers[steepest_bin])
            steepest_rate = float(gradients[steepest_bin])
            
            return {
                "status": "created",
                "chart_type": "force_distribution",
                "force_axis": force_axis,
                "distribution_axis": distribution_axis,
                "position_range": [float(pos_min), float(pos_max)],
                "total_force": float(accumulated[-1]),
                "num_body_cells": int(body_mask.sum()),
                "num_bins": num_bins,
                # Distribution analysis
                "peak_section": {
                    "position": peak_position,
                    "force": peak_force,
                    "description": f"Highest sectional force at position {peak_position:.3f}"
                },
                "half_force_position": half_position,
                "steepest_buildup": {
                    "position": steepest_position,
                    "rate": steepest_rate,
                    "description": f"Fastest force buildup at position {steepest_position:.3f}"
                },
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def create_vortex_isosurface(
        self,
        method: str = "q_criterion",
        threshold: float = None,
        percentile: float = 50.0,
        normalize: bool = True,
        color_field: str = "Velocity",
        proxy_name: str = None
    ) -> dict:
        """
        Create isosurface to visualize vortical structures using various methods.
        
        Methods:
        - "q_criterion": Q = 0.5*(||Ω||² - ||S||²). Positive Q = vortex. (default, fast)
        - "vorticity": Vorticity magnitude ||ω||. High = rotation. (simple but includes shear)
        - "lambda2": Second eigenvalue of S² + Ω². Negative λ2 = vortex core. (accurate)
        - "swirling_strength": Max imaginary eigenvalue of ∇u. Positive = rotation.
        - "helicity": Normalized helicity Hn = (u·ω)/(|u||ω|). |Hn|≈1 = helical vortex.
        
        Threshold selection:
        - Q-criterion, vorticity, swirl: percentile of positive values
        - Lambda2: Uses 1% of min(λ2) by default (small negative, close to 0)
        - Helicity: |Hn| > 0.7 by default (strongly aligned)
        
        Normalization (when normalize=True):
        - Scales by (U_ref)² where U_ref = max|velocity|
        - Makes thresholds more transferable across flow conditions
        
        After creation, use focus_on(name) to focus camera on the isosurface.
        
        Args:
            method: "q_criterion", "vorticity", "lambda2", "swirling_strength", or "helicity"
            threshold: Explicit value for isosurface. If None, auto-computed.
            percentile: Percentile for auto-threshold (default: 50). Not used for lambda2/helicity.
            normalize: If True, normalize by characteristic velocity (default: True)
            color_field: Field to color the isosurface by (default: Velocity)
            proxy_name: Source proxy name (required for explicit input)
            
        Returns:
            Dict with field range, threshold, method, and isosurface name
        """
        from vtk.util.numpy_support import vtk_to_numpy
        
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Need to merge blocks first for gradient computation
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            
            # Compute gradient with appropriate fields
            gradient = simple.Gradient(Input=merge)
            gradient.ScalarArray = ['POINTS', 'Velocity']
            
            if method == "q_criterion":
                gradient.ComputeQCriterion = 1
                gradient.QCriterionArrayName = "Q"
                field_name = "Q"
                positive_is_vortex = True
            elif method == "vorticity":
                gradient.ComputeVorticity = 1
                gradient.VorticityArrayName = "Vorticity"
                field_name = "Vorticity"  # Will use magnitude
                positive_is_vortex = True
            elif method == "helicity":
                # Need both vorticity and velocity for helicity
                gradient.ComputeVorticity = 1
                gradient.VorticityArrayName = "Vorticity"
                field_name = "NormalizedHelicity"
                positive_is_vortex = True  # We'll use |Hn|
            elif method in ("lambda2", "swirling_strength"):
                # Both require velocity gradient tensor
                gradient.ComputeGradient = 1
                gradient.ResultArrayName = "VelocityGradient"
                field_name = "Lambda2" if method == "lambda2" else "SwirlingStrength"
                positive_is_vortex = (method == "swirling_strength")  # lambda2 uses negative
            else:
                simple.Delete(merge)
                return {"error": f"Unknown method: {method}. Use 'q_criterion', 'vorticity', 'lambda2', 'swirling_strength', or 'helicity'"}
            
            simple.UpdatePipeline(proxy=gradient)
            grad_data = gradient.GetClientSideObject().GetOutput()
            
            # For methods needing custom computation, use ProgrammableFilter
            # This ensures arrays are properly in the pipeline (not just client-side)
            programmable = None
            
            if method == "vorticity":
                # Use Calculator for vorticity magnitude (simpler than ProgrammableFilter)
                calc = simple.Calculator(Input=gradient)
                calc.ResultArrayName = "VorticityMagnitude"
                calc.Function = "mag(Vorticity)"
                simple.UpdatePipeline(proxy=calc)
                
                # Get the data for threshold calculation
                calc_data = calc.GetClientSideObject().GetOutput()
                field_vtk = calc_data.GetPointData().GetArray("VorticityMagnitude")
                field_array = vtk_to_numpy(field_vtk)
                field_name = "VorticityMagnitude"
                contour_input = calc
            
            elif method == "helicity":
                # Normalized helicity needs ProgrammableFilter for dot product
                # Mask low |u| and |ω| regions to avoid noise
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output

# Copy input to output
out.ShallowCopy(inp.VTKObject)

vort = np.ascontiguousarray(vtk_to_numpy(inp.PointData["Vorticity"]))
vel = np.ascontiguousarray(vtk_to_numpy(inp.PointData["Velocity"]))

vel_mag = np.linalg.norm(vel, axis=1)
vort_mag = np.linalg.norm(vort, axis=1)

# Compute thresholds - 10th percentile to filter noise
vel_thresh = np.percentile(vel_mag[vel_mag > 0], 10) if np.any(vel_mag > 0) else 0.01
vort_thresh = np.percentile(vort_mag[vort_mag > 0], 10) if np.any(vort_mag > 0) else 0.01

# Mask low magnitude regions
valid_mask = (vel_mag > vel_thresh) & (vort_mag > vort_thresh)

denom = np.maximum(vel_mag * vort_mag, 1e-10)
helicity = np.abs(np.sum(vel * vort, axis=1) / denom)

# Set invalid regions to 0
helicity = np.where(valid_mask, helicity, 0.0)
helicity = np.ascontiguousarray(helicity)

arr = numpy_to_vtk(helicity)
arr.SetName("NormalizedHelicity")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("NormalizedHelicity")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            elif method == "lambda2":
                # Lambda2 needs eigenvalue computation
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output
out.ShallowCopy(inp.VTKObject)

# Get velocity gradient - handle non-contiguous VTK arrays
grad_vtk = inp.PointData.GetArray("VelocityGradient")
n = grad_vtk.GetNumberOfTuples()
G = np.array([grad_vtk.GetTuple(i) for i in range(n)]).reshape(-1, 3, 3)

# Initialize output array
lambda2 = np.zeros(n, dtype=np.float64)

# Find valid cells (no NaN/Inf in gradient)
valid_mask = np.all(np.isfinite(G), axis=(1, 2))
valid_indices = np.where(valid_mask)[0]

if len(valid_indices) > 0:
    G_valid = G[valid_indices]
    
    # Compute lambda2: second eigenvalue of S^2 + Omega^2 (vectorized)
    S = 0.5 * (G_valid + np.transpose(G_valid, (0, 2, 1)))
    Omega = 0.5 * (G_valid - np.transpose(G_valid, (0, 2, 1)))
    M = np.matmul(S, S) + np.matmul(Omega, Omega)
    
    # Compute eigenvalues with error handling
    try:
        eigvals = np.linalg.eigvalsh(M)
        lambda2[valid_indices] = eigvals[:, 1]
    except np.linalg.LinAlgError:
        # Fall back to per-cell computation
        for i, idx in enumerate(valid_indices):
            try:
                eig = np.linalg.eigvalsh(M[i])
                lambda2[idx] = eig[1]
            except:
                lambda2[idx] = 0.0

lambda2 = np.ascontiguousarray(lambda2)
arr = numpy_to_vtk(lambda2)
arr.SetName("Lambda2")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("Lambda2")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            elif method == "swirling_strength":
                # Swirling strength needs complex eigenvalues
                programmable = simple.ProgrammableFilter(Input=gradient)
                programmable.Script = '''
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0]
out = output
out.ShallowCopy(inp.VTKObject)

# Get velocity gradient - handle non-contiguous VTK arrays
grad_vtk = inp.PointData.GetArray("VelocityGradient")
n = grad_vtk.GetNumberOfTuples()
G = np.array([grad_vtk.GetTuple(i) for i in range(n)]).reshape(-1, 3, 3)

# Initialize output array
swirl = np.zeros(n, dtype=np.float64)

# Find valid cells (no NaN/Inf in gradient)
valid_mask = np.all(np.isfinite(G), axis=(1, 2))
valid_indices = np.where(valid_mask)[0]

if len(valid_indices) > 0:
    G_valid = G[valid_indices]
    
    # Compute swirling strength: max imaginary eigenvalue of grad(u) (vectorized)
    try:
        eigvals = np.linalg.eigvals(G_valid)
        swirl[valid_indices] = np.max(np.abs(eigvals.imag), axis=1)
    except np.linalg.LinAlgError:
        # Fall back to per-cell computation
        for i, idx in enumerate(valid_indices):
            try:
                eig = np.linalg.eigvals(G_valid[i])
                swirl[idx] = np.max(np.abs(eig.imag))
            except:
                swirl[idx] = 0.0

swirl = np.ascontiguousarray(swirl)
arr = numpy_to_vtk(swirl)
arr.SetName("SwirlingStrength")
out.GetPointData().AddArray(arr)
'''
                simple.UpdatePipeline(proxy=programmable)
                
                prog_data = programmable.GetClientSideObject().GetOutput()
                field_vtk = prog_data.GetPointData().GetArray("SwirlingStrength")
                field_array = vtk_to_numpy(field_vtk)
                contour_input = programmable
                
            else:  # q_criterion
                field_vtk = grad_data.GetPointData().GetArray(field_name)
                if field_vtk is None:
                    simple.Delete(gradient)
                    simple.Delete(merge)
                    return {"error": f"Could not compute {field_name}"}
                field_array = vtk_to_numpy(field_vtk)
                contour_input = gradient
            
            field_min, field_max = float(field_array.min()), float(field_array.max())
            
            # Get characteristic velocity and length for normalization
            vel_array = grad_data.GetPointData().GetArray("Velocity")
            if vel_array is not None:
                vel = vtk_to_numpy(vel_array)
                U_ref = float(np.max(np.linalg.norm(vel, axis=1)))
            else:
                U_ref = 1.0
                normalize = False
            
            # Get characteristic length from bounding box
            bounds = grad_data.GetBounds()  # (xmin, xmax, ymin, ymax, zmin, zmax)
            L_ref = float(np.sqrt((bounds[1]-bounds[0])**2 + 
                                  (bounds[3]-bounds[2])**2 + 
                                  (bounds[5]-bounds[4])**2))  # diagonal
            if L_ref < 1e-10:
                L_ref = 1.0
            
            # Compute threshold if not provided
            auto_threshold = threshold is None
            if auto_threshold:
                if method == "lambda2":
                    # Lambda2: use 1% of min (small negative, captures vortex boundary)
                    threshold = 0.01 * field_min
                elif method == "helicity":
                    # Normalized helicity: |Hn| > 0.7 means strongly aligned
                    threshold = 0.7
                elif positive_is_vortex:
                    # Q-criterion, vorticity, swirling strength: use percentile
                    positive_vals = field_array[field_array > 0]
                    if len(positive_vals) > 0:
                        threshold = float(np.percentile(positive_vals, percentile))
                    else:
                        threshold = max(0.0, field_max * 0.01)
                else:
                    # Fallback for negative-indicates-vortex
                    negative_vals = field_array[field_array < 0]
                    if len(negative_vals) > 0:
                        threshold = float(np.percentile(negative_vals, 100 - percentile))
                    else:
                        threshold = min(0.0, field_min * 0.01)
            
            # Create isosurface
            contour = simple.Contour(Input=contour_input)
            contour.ContourBy = ['POINTS', field_name]
            contour.Isosurfaces = [threshold]
            simple.UpdatePipeline(proxy=contour)
            
            # Show and color - ensure we have a RenderView
            view = simple.GetActiveView()
            if view is None or not hasattr(view, 'ResetCamera'):
                for v in simple.GetViews():
                    if hasattr(v, 'ResetCamera'):
                        view = v
                        break
                else:
                    view = simple.CreateRenderView()
                simple.SetActiveView(view)
            
            # Hide intermediate filters
            simple.Hide(merge, view)
            simple.Hide(gradient, view)
            if contour_input != gradient:
                simple.Hide(contour_input, view)
            
            display = simple.Show(contour, view)
            display.SetRepresentationType('Surface')
            
            # Color by field
            resolved_field = self._resolve_field_name(color_field, contour)
            try:
                simple.ColorBy(display, ('POINTS', resolved_field))
                display.SetScalarBarVisibility(view, True)
            except:
                pass
            
            # Get contour name
            contour_name = None
            for name, p in simple.GetSources().items():
                if p == contour:
                    contour_name = name[0]
                    break
            
            # Focus camera on the isosurface
            if contour_name:
                self.base_mcp.focus_on(contour_name)
            
            simple.Render(view)
            
            return {
                "status": "created",
                "name": contour_name,
                "method": method,
                "field_name": field_name,
                "field_range": [field_min, field_max],
                "threshold": float(threshold),
                "U_ref": U_ref,
                "L_ref": L_ref,
                "auto_threshold": auto_threshold
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
                data = merge.GetClientSideObject().GetOutput()
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
            create_streamlines(center=wake["wake_centroid"], ...)
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
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
                return {
                    "error": f"No wake region found with velocity < {velocity_deficit*100:.0f}% of freestream",
                    "freestream_velocity": v_freestream,
                    "threshold": v_threshold
                }
            
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

    def create_streamlines(
        self,
        center: list = None,
        radius: float = None,
        num_points: int = 100,
        direction: str = "both",
        max_length: float = None,
        color_field: str = "Velocity",
        proxy_name: str = None
    ) -> dict:
        """
        Create streamlines to visualize flow patterns like wakes and jets.
        
        Seeds streamlines from a spherical point cloud and integrates along
        the velocity field. Great for visualizing wake flow, recirculation,
        and overall flow structure.
        
        Auto-sizing: When radius is not specified, the seed cloud is sized from
        the wake's cross-stream extent (via detect_wake_region). This ensures
        seeds cover the velocity deficit region rather than the full domain.
        Falls back to body geometry bounds if no wake is detected.
        
        Args:
            center: Seed center [x, y, z]. If None, uses wake centroid or body center.
            radius: Seed sphere radius. If None, auto-computed from wake cross-section
                   (half the max cross-stream extent of the velocity deficit region).
            num_points: Number of seed points (default 100)
            direction: Integration direction - "forward", "backward", or "both" (default)
            max_length: Maximum streamline length. If None, uses 10x domain diagonal.
            color_field: Field to color streamlines by (default "Velocity")
            proxy_name: Source data
            
        Returns:
            Dict with streamline info: name, num_seeds, direction, length
            
        Examples:
            # Auto-detect wake and seed streamlines there
            create_streamlines()
            
            # Custom seed location
            create_streamlines(center=[5, 0.5, 0], radius=0.2)
            
            # Forward only (for wake visualization)
            create_streamlines(direction="forward")
            
        Workflow for wake visualization:
            1. wake = detect_wake_region()
            2. create_streamlines(center=wake["wake_centroid"])
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Ensure velocity exists
            velocity_result = self.ensure_velocity_vector(proxy_name=proxy_name)
            if "error" in velocity_result and "already" not in velocity_result.get("error", ""):
                return velocity_result
            
            # Get data bounds for auto-parameters
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = di.GetBounds()
            
            domain_diag = np.sqrt(
                (bounds[1] - bounds[0])**2 +
                (bounds[3] - bounds[2])**2 +
                (bounds[5] - bounds[4])**2
            )
            
            # Get body bounds (farfield clipped) for fallback sizing
            body_bounds, body_diag = self._get_body_bounds(proxy)
            
            # Auto-compute center and radius from wake detection
            wake_result = None
            if center is None or radius is None:
                wake_result = self.detect_wake_region(proxy_name=proxy_name)
            
            if center is None:
                if wake_result and "wake_centroid" in wake_result:
                    center = wake_result["wake_centroid"]
                else:
                    # Fall back to body center (not domain center)
                    center = [
                        (body_bounds[0] + body_bounds[1]) / 2,
                        (body_bounds[2] + body_bounds[3]) / 2,
                        (body_bounds[4] + body_bounds[5]) / 2
                    ]
            
            # Auto-compute radius from wake cross-stream extent
            if radius is None:
                if wake_result and "wake_bounds" in wake_result and wake_result["wake_bounds"]:
                    wb = wake_result["wake_bounds"]
                    # Identify streamwise axis and use the cross-stream extents
                    streamwise = wake_result.get("streamwise", "x")
                    wake_extents = [wb[1] - wb[0], wb[3] - wb[2], wb[5] - wb[4]]
                    axis_map = {"x": 0, "+x": 0, "-x": 0,
                                "y": 1, "+y": 1, "-y": 1,
                                "z": 2, "+z": 2, "-z": 2}
                    stream_idx = axis_map.get(streamwise.lower(), 0)
                    
                    # Cross-stream extents (the two non-streamwise dimensions)
                    cross_extents = [e for i, e in enumerate(wake_extents) if i != stream_idx and e > 1e-10]
                    if cross_extents:
                        # Radius covers the wake cross-section
                        radius = max(cross_extents) * 0.5
                    else:
                        radius = body_diag * 0.1
                else:
                    # No wake detected — use smallest body dimension
                    body_extents = [
                        body_bounds[1] - body_bounds[0],
                        body_bounds[3] - body_bounds[2],
                        body_bounds[5] - body_bounds[4],
                    ]
                    min_extent = min(e for e in body_extents if e > 1e-10)
                    radius = min_extent * 0.3
            
            # Auto-compute max length relative to domain (streamlines can travel far)
            if max_length is None:
                max_length = domain_diag * 10
            
            # Create StreamTracer
            stream = simple.StreamTracer(Input=proxy)
            stream.Vectors = ['POINTS', 'Velocity']
            
            # Configure seed type as Point Cloud
            stream.SeedType = 'Point Cloud'
            stream.SeedType.Center = center
            stream.SeedType.Radius = radius
            stream.SeedType.NumberOfPoints = num_points
            
            # Set integration direction
            direction_map = {
                "forward": "FORWARD",
                "backward": "BACKWARD",
                "both": "BOTH"
            }
            stream.IntegrationDirection = direction_map.get(direction.lower(), "BOTH")
            
            # Set maximum streamline length
            stream.MaximumStreamlineLength = max_length
            
            # Update
            simple.UpdatePipeline(proxy=stream)
            
            # Show and color - ensure we have a RenderView
            view = simple.GetActiveView()
            if view is None or not hasattr(view, 'ResetCamera'):
                for v in simple.GetViews():
                    if hasattr(v, 'ResetCamera'):
                        view = v
                        break
                else:
                    view = simple.CreateRenderView()
                simple.SetActiveView(view)
            
            display = simple.Show(stream, view)
            
            # Color by field
            color_array = self._resolve_field_type(color_field, stream)
            if color_array:
                simple.ColorBy(display, ('POINTS', color_array))
                display.RescaleTransferFunctionToDataRange(True, False)
                display.SetScalarBarVisibility(view, True)
            
            # Apply tube filter for better visibility
            tube = simple.Tube(Input=stream)
            tube.Radius = radius * 0.02  # 2% of seed radius — scales with local feature
            simple.UpdatePipeline(proxy=tube)
            
            tube_display = simple.Show(tube, view)
            if color_array:
                simple.ColorBy(tube_display, ('POINTS', color_array))
                tube_display.RescaleTransferFunctionToDataRange(True, False)
            
            # Hide raw streamlines, show tubes
            simple.Hide(stream, view)
            
            simple.Render()
            
            # Get streamline name
            stream_name = None
            for name, p in simple.GetSources().items():
                if p == stream:
                    stream_name = name[0]
                    break
            
            tube_name = None
            for name, p in simple.GetSources().items():
                if p == tube:
                    tube_name = name[0]
                    break
            
            return {
                "status": "created",
                "streamlines_name": stream_name,
                "tube_name": tube_name,
                "seed_center": center,
                "seed_radius": radius,
                "seed_sized_from": "wake_cross_section" if (wake_result and "wake_bounds" in wake_result) else "body_bounds",
                "num_seeds": num_points,
                "direction": direction,
                "max_length": max_length,
                "color_field": color_array or color_field,
                "domain_diagonal": float(domain_diag),
                "body_diagonal": float(body_diag),
            }
            
        except Exception as e:
            return {"error": str(e)}

    def create_point_marker(
        self,
        location: list[float],
        radius: float = None,
        color: list[float] = None,
        label: str = None,
        proxy_name: str = None
    ) -> dict:
        """
        Create a visible sphere marker at a specific point location.
        
        Useful for highlighting found locations like stagnation points,
        maximum/minimum values, or query results.
        
        Args:
            location: [x, y, z] coordinates for the marker
            radius: Sphere radius. If None, auto-sized to ~2% of data diagonal.
            color: [r, g, b] color (0-1). Default is red [1, 0, 0].
            label: Optional label for the marker (stored in result).
            proxy_name: Reference proxy for auto-sizing radius.
            
        Returns:
            Dict with marker name, location, and visual properties.
        """
        try:
            # Auto-size radius based on data extent
            if radius is None:
                proxy = self._get_proxy(proxy_name)
                if proxy:
                    simple.UpdatePipeline(proxy=proxy)
                    di = proxy.GetDataInformation()
                    bounds = di.GetBounds()
                    diag = ((bounds[1]-bounds[0])**2 + (bounds[3]-bounds[2])**2 + (bounds[5]-bounds[4])**2)**0.5
                    radius = diag * 0.02
                else:
                    radius = 0.05  # fallback
            
            # Create sphere at location
            sphere = simple.Sphere()
            sphere.Center = location
            sphere.Radius = radius
            sphere.ThetaResolution = 16
            sphere.PhiResolution = 16
            simple.UpdatePipeline(proxy=sphere)
            
            # Show with solid color
            view = simple.GetActiveView()
            display = simple.Show(sphere, view)
            
            if color is None:
                color = [1.0, 0.0, 0.0]  # Red
            
            display.DiffuseColor = color
            display.AmbientColor = color
            simple.ColorBy(display, None)  # Solid color
            
            simple.Render(view)
            
            # Get marker name
            marker_name = None
            for name, p in simple.GetSources().items():
                if p == sphere:
                    marker_name = name[0]
                    break
            
            return {
                "status": "created",
                "marker_name": marker_name,
                "location": location,
                "radius": radius,
                "color": color,
                "label": label
            }
            
        except Exception as e:
            return {"error": str(e)}

    def get_slice_parameters(
        self,
        normal: list[float] = None,
        position: str = "center",
        proxy_name: str = None
    ) -> dict:
        """
        Get recommended parameters for creating a slice through the data.
        
        This is a QUERY tool - it computes slice positioning parameters
        but does NOT create any filters. Use the returned values with
        base.create("Slice") to actually create the slice.
        
        Args:
            normal: Slice normal [nx, ny, nz]. Default [0, 1, 0] (XZ plane/side view).
                Common choices:
                - [1, 0, 0]: YZ plane (front view, perpendicular to flow)
                - [0, 1, 0]: XZ plane (side view, spanwise cut)
                - [0, 0, 1]: XY plane (top view)
            position: Where to position the slice:
                - "center": Center of bounding box (default)
                - "quarter": 1/4 into domain along normal direction
                - "body": Positioned to intersect body (uses clipped bounds)
            proxy_name: Data source name.
            
        Returns:
            Dict with:
            - origin: [x, y, z] recommended slice origin
            - normal: [nx, ny, nz] slice normal (normalized)
            - bounds: [xmin, xmax, ymin, ymax, zmin, zmax] data bounds
            
        Example workflow:
            params = get_slice_parameters(normal=[1,0,0], position="center")
            base.create("Slice", Input=reader_name)
            base.update_sub_property("Slice1", "SliceType", "Origin", params["origin"])
            base.update_sub_property("Slice1", "SliceType", "Normal", params["normal"])
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = list(di.GetBounds())
            
            if normal is None:
                normal = [0, 1, 0]  # XZ plane (side view)
            
            # Normalize
            import math
            mag = math.sqrt(sum(n*n for n in normal))
            if mag > 0:
                normal = [n/mag for n in normal]
            
            # Compute center
            center = [
                (bounds[0] + bounds[1]) / 2,
                (bounds[2] + bounds[3]) / 2,
                (bounds[4] + bounds[5]) / 2
            ]
            
            # Compute origin based on position strategy
            origin = center.copy()
            
            if position == "quarter":
                # Position at 1/4 along normal direction
                extents = [bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4]]
                for i in range(3):
                    if abs(normal[i]) > 0.5:
                        origin[i] = bounds[2*i] + extents[i] * 0.25
                        
            elif position == "body":
                # Position to intersect body (shrink bounds to exclude farfield)
                margin = 0.2
                body_bounds = [
                    bounds[0] + (bounds[1]-bounds[0]) * margin,
                    bounds[1] - (bounds[1]-bounds[0]) * margin,
                    bounds[2] + (bounds[3]-bounds[2]) * margin,
                    bounds[3] - (bounds[3]-bounds[2]) * margin,
                    bounds[4] + (bounds[5]-bounds[4]) * margin,
                    bounds[5] - (bounds[5]-bounds[4]) * margin,
                ]
                origin = [
                    (body_bounds[0] + body_bounds[1]) / 2,
                    (body_bounds[2] + body_bounds[3]) / 2,
                    (body_bounds[4] + body_bounds[5]) / 2
                ]
                # Adjust for normal direction
                for i in range(3):
                    if abs(normal[i]) > 0.5:
                        origin[i] = body_bounds[2*i] + (body_bounds[2*i+1] - body_bounds[2*i]) * 0.25
            
            # For Z-normal slices (top view), default to z=0
            if position == "center" and abs(normal[2]) > 0.5:
                origin[2] = 0.0
            
            return {
                "origin": origin,
                "normal": normal,
                "bounds": bounds,
                "position_strategy": position,
            }
            
        except Exception as e:
            return {"error": str(e)}

    def create_clipped_slice(
        self,
        normal: list[float] = None,
        origin: list[float] = None,
        color_field: str = "pressure",
        clip_to_body: bool = False,
        clip_margin: float = 0.2,
        proxy_name: str = None
    ) -> dict:
        """
        Create a slice colored by a field.
        
        Args:
            normal: Slice normal [nx, ny, nz]. Default is [0, 1, 0] (XZ plane).
            origin: Slice origin [x, y, z]. Default is positioned to intersect body.
            color_field: Field to color by. Default "pressure".
            clip_to_body: If True, clip farfield (may cause issues with thin slices).
            clip_margin: Fraction of domain to clip from each edge if clipping.
            proxy_name: Data source name.
            
        Returns:
            Dict with slice info.
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            simple.UpdatePipeline(proxy=proxy)
            di = proxy.GetDataInformation()
            bounds = list(di.GetBounds())
            
            if normal is None:
                normal = [0, 1, 0]  # XZ plane (side view)
            
            # Position slice intelligently based on normal direction
            if origin is None:
                origin = [
                    (bounds[0] + bounds[1]) / 2,
                    (bounds[2] + bounds[3]) / 2,
                    (bounds[4] + bounds[5]) / 2
                ]
                # For Y-normal slices, position at 1/4 height to catch wing flow
                if abs(normal[1]) > 0.5:
                    origin[1] = bounds[2] + (bounds[3] - bounds[2]) * 0.25
                # For Z-normal slices (top view), keep at center (Z=0)
                elif abs(normal[2]) > 0.5:
                    origin[2] = 0.0
            
            # Create slice
            slice_filter = simple.Slice(Input=proxy)
            slice_filter.SliceType = 'Plane'
            slice_filter.SliceType.Origin = origin
            slice_filter.SliceType.Normal = normal
            simple.UpdatePipeline(proxy=slice_filter)
            
            final_filter = slice_filter
            clip = None
            
            # Optional clipping (disabled by default - can cause empty results)
            if clip_to_body:
                dx = (bounds[1] - bounds[0]) * clip_margin
                dy = (bounds[3] - bounds[2]) * clip_margin
                dz = (bounds[5] - bounds[4]) * clip_margin
                
                clip_bounds = [
                    bounds[0] + dx, bounds[1] - dx,
                    bounds[2] + dy, bounds[3] - dy,
                    bounds[4] + dz, bounds[5] - dz
                ]
                
                clip = simple.Clip(Input=slice_filter)
                clip.ClipType = 'Box'
                clip.ClipType.Bounds = clip_bounds
                clip.Invert = 1  # Keep inside
                simple.UpdatePipeline(proxy=clip)
                
                # Hide intermediate slice
                view = simple.GetActiveView()
                simple.Hide(slice_filter, view)
                final_filter = clip
            
            # Show final filter
            view = simple.GetActiveView()
            display = simple.Show(final_filter, view)
            
            # Color by field
            field_name = self._resolve_field_type(color_field, proxy)
            simple.ColorBy(display, ('POINTS', field_name))
            display.RescaleTransferFunctionToDataRange(True)
            display.SetScalarBarVisibility(view, True)
            
            simple.Render(view)
            
            # Get names
            slice_name = None
            clip_name = None
            for name, p in simple.GetSources().items():
                if p == slice_filter:
                    slice_name = name[0]
                if clip and p == clip:
                    clip_name = name[0]
            
            return {
                "status": "created",
                "slice_name": slice_name,
                "clip_name": clip_name,
                "origin": origin,
                "normal": normal,
                "color_field": field_name,
            }
            
        except Exception as e:
            return {"error": str(e)}

    # NOTE: No create_slice wrapper - use base tools with positioning from:
    #   - get_geometry_info() for center/bounds
    #   - find_by_query() for feature-based positioning (stagnation, wake)
    #   - detect_wake_region() for wake centroid
    # Then: base__create("Slice") + base__update_sub_property for origin/normal
    # The ontology encodes slice positioning strategies for LLM reasoning.

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
    
    def extract_body_surface(
        self,
        proxy_name: str = None,
        feature_angle: float = 30.0,
        color: list[float] = None,
        line_width: float = 2.0
    ) -> dict:
        """
        Extract and display body surface as feature edges for context.
        
        For CFD data, this extracts the external surface and shows only the
        sharp feature edges (silhouette). This provides body shape context
        without blocking visibility of internal flow features like slices,
        streamlines, and isosurfaces.
        
        Args:
            proxy_name: Data source. If None, uses first data reader.
            feature_angle: Angle (degrees) to detect feature edges. Default 30.
            color: RGB color [r,g,b] each 0-1. Default dark gray [0.3, 0.3, 0.3].
            line_width: Width of feature edge lines. Default 2.0.
            
        Returns:
            Dict with feature edges proxy name and settings.
            
        Example:
            # Show body outline before visualizing flow
            hide_all()
            extract_body_surface()
            create_streamlines(...)
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            # Auto-find data reader
            for name, p in simple.GetSources().items():
                if any(x in name[0] for x in ['Reader', 'OpenFOAM', 'EnSight', 'CGNS', 'XMLMultiBlock']):
                    proxy = p
                    proxy_name = name[0]
                    break
        
        if proxy is None:
            return {"error": "No data source found"}
        
        try:
            # Get/create render view
            view = simple.GetActiveView()
            if view is None or not hasattr(view, 'ResetCamera'):
                for v in simple.GetViews():
                    if hasattr(v, 'ResetCamera'):
                        view = v
                        break
                else:
                    view = simple.CreateRenderView()
                simple.SetActiveView(view)
            
            # Extract external surface first (don't show it)
            surface = simple.ExtractSurface(Input=proxy)
            simple.UpdatePipeline(proxy=surface)
            simple.Hide(surface, view)  # Ensure hidden
            
            # Apply Feature Edges filter
            edges = simple.FeatureEdges(Input=surface)
            edges.FeatureEdges = 1
            edges.BoundaryEdges = 1
            edges.NonManifoldEdges = 0
            edges.ManifoldEdges = 0
            edges.FeatureAngle = feature_angle
            simple.UpdatePipeline(proxy=edges)
            
            # Show feature edges
            display = simple.Show(edges, view)
            
            # Ensure surface is hidden (in case Show triggered anything)
            simple.Hide(surface, view)
            
            # Style as thin lines
            if color is None:
                color = [0.3, 0.3, 0.3]  # Dark gray
            try:
                display.AmbientColor = color
                display.DiffuseColor = color
                display.LineWidth = line_width
            except AttributeError:
                pass
            simple.ColorBy(display, None)  # Solid color
            
            simple.Render(view)
            
            # Get names
            edges_name = None
            surface_name = None
            for name, p in simple.GetSources().items():
                if p == edges:
                    edges_name = name[0]
                elif p == surface:
                    surface_name = name[0]
            
            return {
                "status": "extracted",
                "feature_edges_name": edges_name,
                "surface_name": surface_name,
                "feature_angle": feature_angle,
                "color": color
            }
            
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
            create_vortex_isosurface()    # Flow feature on top
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
        data = proxy.GetClientSideObject().GetOutput()
        
        # Handle multiblock
        if data.IsA("vtkMultiBlockDataSet"):
            merge = simple.MergeBlocks(Input=proxy)
            simple.UpdatePipeline(proxy=merge)
            data = merge.GetClientSideObject().GetOutput()
        
        arr = data.GetPointData().GetArray(field_name)
        if arr is None:
            arr = data.GetCellData().GetArray(field_name)
        
        if arr is None:
            return None, None
        
        return vtk_to_numpy(arr), data
