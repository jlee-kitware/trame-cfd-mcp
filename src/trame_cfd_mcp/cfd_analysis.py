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
from trame_llm.paraview import (
    safe_delete, ensure_flat_input,
    get_field_names, run_server_script, fetch_table,
    fetch_data,  # retained for Catalyst Live path only
)
import numpy as np
import json
from pathlib import Path

# Directory containing server-side analysis scripts
_SCRIPTS_DIR = Path(__file__).parent / "server_scripts"

def _script(name: str) -> str:
    """Return absolute path to a server analysis script."""
    return str(_SCRIPTS_DIR / name)


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
        self._analysis_log = []  # Track analysis decisions for provenance
    
    # =========================================================================
    # Provenance tracking
    # =========================================================================
    
    def _log_analysis(self, analysis_type: str, **details):
        """
        Log an analysis decision for provenance.
        
        Call this whenever CFDAnalysis makes a decision that ParaView doesn't
        track - threshold computations, wake detection, seed placement, etc.
        """
        self._analysis_log.append({"type": analysis_type, **details})
    
    def get_analysis_log(self) -> list:
        """Get the accumulated analysis log."""
        return self._analysis_log.copy()
    
    def clear_analysis_log(self):
        """Clear the analysis log. Call at start of each workflow."""
        self._analysis_log = []

    def extract_filter_chain(self, proxy) -> list:
        """
        Extract full filter chain by walking ParaView's input chain.
        
        Returns list of filters from root (reader) to the given proxy,
        with key parameters for each filter.
        """
        chain = []
        current = proxy
        
        while current is not None:
            name = self._get_source_name(current)
            xml_name = current.GetXMLName()
            params = self._get_filter_params(current)
            
            # Get input
            input_proxy = None
            input_name = None
            if hasattr(current, 'Input') and current.Input:
                input_proxy = current.Input
                input_name = self._get_source_name(input_proxy)
            
            entry = {'filter': xml_name, 'output': name}
            if input_name:
                entry['input'] = input_name
            if params:
                entry['params'] = params
            
            chain.append(entry)
            current = input_proxy
        
        chain.reverse()
        return chain
    
    def _get_filter_params(self, proxy) -> dict:
        """Extract key parameters based on filter type."""
        xml_name = proxy.GetXMLName()
        params = {}
        
        try:
            if xml_name == 'Gradient':
                if hasattr(proxy, 'ScalarArray') and proxy.ScalarArray:
                    params['ScalarArray'] = proxy.ScalarArray[1]
                params['ComputeQCriterion'] = int(proxy.ComputeQCriterion)
                params['ComputeVorticity'] = int(proxy.ComputeVorticity)
            elif xml_name == 'Contour':
                if hasattr(proxy, 'ContourBy') and proxy.ContourBy:
                    params['ContourBy'] = proxy.ContourBy[1]
                params['Isosurfaces'] = list(proxy.Isosurfaces)
            elif xml_name == 'Slice':
                st = proxy.SliceType
                params['SliceType'] = st.GetXMLName() if hasattr(st, 'GetXMLName') else 'Plane'
                if hasattr(st, 'Origin'):
                    params['Origin'] = [round(x, 6) for x in st.Origin]
                if hasattr(st, 'Normal'):
                    params['Normal'] = [round(x, 6) for x in st.Normal]
            elif xml_name == 'Calculator':
                params['Function'] = str(proxy.Function)
                params['ResultArrayName'] = str(proxy.ResultArrayName)
            elif xml_name == 'ProgrammableFilter':
                # Don't include full script, just note what it does
                params['operation'] = 'custom_computation'
            elif xml_name == 'StreamTracer':
                # IntegrationDirection is an EnumerationProperty - get the string value
                try:
                    params['IntegrationDirection'] = str(proxy.IntegrationDirection)
                except:
                    params['IntegrationDirection'] = 'BOTH'
                params['MaximumStreamlineLength'] = float(proxy.MaximumStreamlineLength)
            elif xml_name == 'Clip':
                if hasattr(proxy, 'ClipType'):
                    ct = proxy.ClipType
                    params['ClipType'] = ct.GetXMLName() if hasattr(ct, 'GetXMLName') else 'Plane'
            elif 'Reader' in xml_name:
                # Get filename for readers
                if hasattr(proxy, 'FileName'):
                    fn = proxy.FileName
                    if fn:
                        # Extract just the filename, not full path
                        if isinstance(fn, (list, tuple)):
                            fn = fn[0] if fn else None
                        if fn:
                            params['FileName'] = str(fn).split('/')[-1]
        except Exception:
            pass  # Skip params we can't extract
        
        return params if params else None
    
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

        # Use metadata only — no data movement
        info = get_field_names(proxy)
        all_fields = list(info["point"].keys()) + list(info["cell"].keys())

        # First pass: exact match (case-insensitive)
        for name in all_fields:
            for pattern in patterns:
                if pattern.lower() == name.lower():
                    return name

        # Second pass: substring match for patterns >= 3 chars
        for name in all_fields:
            for pattern in patterns:
                if len(pattern) >= 3 and pattern.lower() in name.lower():
                    return name

        return patterns[0]
    
    def _get_available_fields(self, proxy) -> dict:
        """Get available fields and their types from proxy using metadata only."""
        info = get_field_names(proxy)
        all_fields = list(info["point"].keys()) + list(info["cell"].keys())

        result = {"all_fields": all_fields, "resolved": {}}
        for semantic, patterns in FIELD_TYPE_PATTERNS.items():
            for name in all_fields:
                for pattern in patterns:
                    if pattern.lower() == name.lower():
                        result["resolved"][semantic] = name
                        break
                if semantic in result["resolved"]:
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

    # Common velocity field names across CFD solvers
    _VELOCITY_NAMES = [
        "Velocity", "velocity", "U", "u", "V", "vel", "Vel",
        "VELOCITY", "flow_velocity", "FlowVelocity",
    ]

    def _find_velocity_array(self, data):
        """Find velocity array in point data by searching common names and 3-component vectors."""
        pd = data.GetPointData()
        if pd is None:
            return None, None
        
        # Try common names first
        for name in self._VELOCITY_NAMES:
            arr = pd.GetArray(name)
            if arr is not None and arr.GetNumberOfComponents() == 3:
                return arr, name
        
        # Fall back: first 3-component array (likely velocity)
        for i in range(pd.GetNumberOfArrays()):
            arr = pd.GetArray(i)
            if arr is not None and arr.GetNumberOfComponents() == 3:
                name = pd.GetArrayName(i)
                print(f"[_find_velocity_array] No standard name found, using 3-component array '{name}'")
                return arr, name
        
        return None, None

    # Common pressure field names across CFD solvers
    _PRESSURE_NAMES = [
        "p", "P", "Pressure", "pressure", "PRESSURE",
        "StaticPressure", "static_pressure", "press",
        "Total Pressure", "total_pressure", "Pt",
    ]

    def _find_pressure_array(self, data):
        """Find pressure array in point or cell data by searching common names and scalars."""
        for getter in [data.GetPointData, data.GetCellData]:
            arrays = getter()
            if arrays is None:
                continue
            # Try common names first
            for name in self._PRESSURE_NAMES:
                arr = arrays.GetArray(name)
                if arr is not None and arr.GetNumberOfComponents() == 1:
                    association = "POINTS" if getter == data.GetPointData else "CELLS"
                    return arr, name, association
        return None, None, None

    def _find_field(self, data, field_name: str):
        """Find a named field in point or cell data, return (array, actual_name, association)."""
        for getter, assoc in [(data.GetPointData, "POINTS"), (data.GetCellData, "CELLS")]:
            arrays = getter()
            if arrays is None:
                continue
            arr = arrays.GetArray(field_name)
            if arr is not None:
                return arr, field_name, assoc
        return None, None, None
    
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
                    safe_delete(clip)
                except:
                    pass
            if surface is not None:
                try:
                    safe_delete(surface)
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

        skip_types = ['ProgrammableSource']  # internal chart proxies

        for name, proxy in simple.GetSources().items():
            proxy_name = name[0]
            proxy_type = proxy.GetXMLName()

            # Skip internal proxies (chart tables etc.)
            if proxy_name.startswith("Chart_") or proxy_name.startswith("_"):
                continue

            # Get point count from metadata — no data movement
            try:
                di = proxy.GetDataInformation()
                n_points = di.GetNumberOfPoints()
                n_cells  = di.GetNumberOfCells()
            except Exception:
                n_points = n_cells = 0

            entry = {
                "name": proxy_name,
                "type": proxy_type,
                "num_points": n_points,
                "num_cells": n_cells,
            }

            if ('Reader' in proxy_type or proxy_type in [
                'OpenDataFile', 'XMLMultiBlockDataReader', 'XMLUnstructuredGridReader',
                'XMLPolyDataReader', 'LegacyVTKReader', 'EnSightReader', 'PVDReader',
                'CGNSReader', 'ExodusIIReader',
            ]):
                readers.append(entry)
            else:
                filters.append(entry)

        return {
            "readers": readers,
            "filters": filters,
            "active_source": simple.GetActiveSource().GetXMLName() if simple.GetActiveSource() else None,
            "tip": "Any filter with num_points > 0 can be used as seed_source in show_streamlines().",
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
            
            # Use metadata only — no data movement
            info = get_field_names(proxy)
            point_arrays = {k: {"components": v} for k, v in info["point"].items()}
            cell_arrays  = {k: {"components": v} for k, v in info["cell"].items()}
            bounds = info["bounds"]

            # Resolve semantic fields
            all_names = list(point_arrays.keys()) + list(cell_arrays.keys())
            resolved = {}
            for field_type, patterns in FIELD_TYPE_PATTERNS.items():
                for name in all_names:
                    for pattern in patterns:
                        if pattern.lower() == name.lower():
                            resolved[field_type] = name
                            break
                        if len(pattern) >= 3 and pattern.lower() in name.lower():
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
            
            di = proxy.GetDataInformation()
            num_points = di.GetNumberOfPoints()
            num_cells  = di.GetNumberOfCells()
            
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
                # Verify it's 3-component using metadata only
                info = get_field_names(proxy)
                ncomp = info["point"].get(vel_name) or info["cell"].get(vel_name, 0)
                if ncomp == 3:
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
            flat_proxy, _, cleanup_input_merge = ensure_flat_input(proxy)

            # Check field type from metadata — no data movement
            info = get_field_names(flat_proxy)
            ncomp = info["point"].get(resolved_field) or info["cell"].get(resolved_field)
            if ncomp is None:
                if cleanup_input_merge:
                    safe_delete(cleanup_input_merge)
                return {"error": f"Field '{field}' not found"}

            is_vector = ncomp > 1
            
            if arr is None:
                if cleanup_input_merge:
                    safe_delete(cleanup_input_merge)
                return {"error": f"Field '{field}' not found"}
            
            is_vector = arr.GetNumberOfComponents() > 1
            
            # Use the merged data as input if we merged
            threshold_source = flat_proxy
            
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

            # Compute centroid server-side — no data movement
            centroid_pf = run_server_script(
                thresh, _script("centroid.py"),
                name="_threshold_centroid",
            )
            kpi = fetch_table(centroid_pf)
            safe_delete(centroid_pf)

            if kpi.get("error") or kpi.get("num_points", 0) == 0:
                safe_delete(thresh)
                if is_vector:
                    safe_delete(calc)
                if cleanup_input_merge:
                    safe_delete(cleanup_input_merge)
                return {
                    "error": f"No points found where {field} {'<' if below else '>'} {threshold}",
                    "field": field,
                    "threshold": threshold,
                    "below": below,
                }

            bounds   = [kpi["xmin"], kpi["xmax"], kpi["ymin"], kpi["ymax"], kpi["zmin"], kpi["zmax"]]
            centroid = [kpi["cx"], kpi["cy"], kpi["cz"]]

            # Cleanup
            safe_delete(thresh)
            if is_vector:
                safe_delete(calc)
            if cleanup_input_merge:
                safe_delete(cleanup_input_merge)

            return {
                "location":   centroid,
                "num_points": int(kpi["num_points"]),
                "bounds":     bounds,
                "field":      field,
                "threshold":  threshold,
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
            
            # Get count from metadata — no data movement
            di = extracted.GetDataInformation()
            num_selected = (di.GetNumberOfPoints() if field_type == "POINT"
                           else di.GetNumberOfCells())
            safe_delete(extracted)

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
            
            num_points = extracted.GetDataInformation().GetNumberOfPoints()

            if num_points == 0:
                safe_delete(extracted)
                return {"error": "No selection or empty selection"}

            # Compute centroid server-side
            c_pf = run_server_script(extracted, _script("centroid.py"), name="_sel_centroid")
            kpi = fetch_table(c_pf)
            safe_delete(c_pf)
            if cleanup_merge:
                safe_delete(cleanup_merge)
            safe_delete(extracted)

            centroid = [kpi["cx"], kpi["cy"], kpi["cz"]]
            bounds   = [kpi["xmin"], kpi["xmax"], kpi["ymin"], kpi["ymax"], kpi["zmin"], kpi["zmax"]]

            return {
                "num_points": int(kpi["num_points"]),
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
            
            num_points = extracted.GetDataInformation().GetNumberOfPoints()

            if num_points == 0:
                safe_delete(extracted)
                return {"error": "No points match query", "query": query}

            # Compute centroid server-side
            c_pf = run_server_script(extracted, _script("centroid.py"), name="_query_centroid")
            kpi = fetch_table(c_pf)
            safe_delete(c_pf)
            if cleanup_merge:
                safe_delete(cleanup_merge)
            safe_delete(extracted)

            centroid = [kpi["cx"], kpi["cy"], kpi["cz"]]
            bounds   = [kpi["xmin"], kpi["xmax"], kpi["ymin"], kpi["ymax"], kpi["zmin"], kpi["zmax"]]

            return {
                "location":   centroid,
                "num_points": int(kpi["num_points"]),
                "bounds":     bounds,
                "query":      query,
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

        field_name = self._resolve_field_type(field, proxy)
        info = get_field_names(proxy)
        location = "POINTS" if field_name in info["point"] else "CELLS"

        flat_proxy, _, cleanup = ensure_flat_input(proxy)
        pf = run_server_script(
            flat_proxy, _script("find_region.py"),
            params={
                "FIELD_NAME": field_name,
                "MODE": "min",
                "LOCATION": location,
                "EXCLUDE_BOUNDARY_FRACTION": 0.05 if exclude_boundaries else 0.0,
            },
            name="_find_min",
        )
        kpi = fetch_table(pf)
        safe_delete(pf)
        if cleanup:
            safe_delete(cleanup)

        if "error" in kpi:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}

        loc = [kpi["loc_x"], kpi["loc_y"], kpi["loc_z"]]
        return {
            "min_location": loc,
            "location": loc,
            "value": kpi["value"],
            "field": field_name,
            "type": "minimum",
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

        field_name = self._resolve_field_type(field, proxy)
        info = get_field_names(proxy)
        location = "POINTS" if field_name in info["point"] else "CELLS"

        flat_proxy, _, cleanup = ensure_flat_input(proxy)
        pf = run_server_script(
            flat_proxy, _script("find_region.py"),
            params={
                "FIELD_NAME": field_name,
                "MODE": "max",
                "LOCATION": location,
                "EXCLUDE_BOUNDARY_FRACTION": 0.0,
            },
            name="_find_max",
        )
        kpi = fetch_table(pf)
        safe_delete(pf)
        if cleanup:
            safe_delete(cleanup)

        if "error" in kpi:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found"}

        loc = [kpi["loc_x"], kpi["loc_y"], kpi["loc_z"]]
        return {
            "max_location": loc,
            "location": loc,
            "value": kpi["value"],
            "field": field_name,
            "type": "maximum",
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

        resolved_field = self._resolve_field_type(field, proxy)
        original_active = simple.GetActiveSource()

        try:
            flat_proxy, _, cleanup_merge = ensure_flat_input(proxy)

            gradient = simple.Gradient(Input=flat_proxy)
            gradient.ScalarArray = ['POINTS', resolved_field]
            gradient.ComputeGradient = 1
            gradient.ResultArrayName = "Gradient"
            simple.UpdatePipeline(proxy=gradient)

            pf = run_server_script(
                gradient, _script("find_region.py"),
                params={
                    "FIELD_NAME": "Gradient",
                    "MODE": "max",
                    "LOCATION": "POINTS",
                    "EXCLUDE_BOUNDARY_FRACTION": 0.0,
                },
                name="_find_high_gradient",
            )
            kpi = fetch_table(pf)
            safe_delete(pf)
            safe_delete(gradient)
            if cleanup_merge:
                safe_delete(cleanup_merge)
            simple.SetActiveSource(original_active)

            if "error" in kpi:
                return {"error": f"Could not compute gradient of '{resolved_field}'"}

            loc = [kpi["loc_x"], kpi["loc_y"], kpi["loc_z"]]
            return {
                "high_gradient_location": loc,
                "location": loc,
                "gradient_magnitude": kpi["value"],
                "field": resolved_field,
                "type": "high_gradient",
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

        field_name = self._resolve_field_type(field, proxy)

        # Determine location from metadata
        info = get_field_names(proxy)
        location = "POINTS" if field_name in info["point"] else "CELLS"

        pf = run_server_script(
            proxy, _script("field_statistics.py"),
            params={"FIELD_NAME": field_name, "LOCATION": location},
            name=f"_stats_{field_name}",
        )
        kpi = fetch_table(pf)
        safe_delete(pf)

        if "error" in kpi:
            return {"error": f"Field '{field}' (resolved: '{field_name}') not found on server"}

        result = {"field": field_name, "num_points": int(kpi.get("num_points", 0))}
        if kpi.get("is_vector", 0):
            result["magnitude"] = {
                "min":  kpi["mag_min"],
                "max":  kpi["mag_max"],
                "mean": kpi["mag_mean"],
                "std":  kpi["mag_std"],
            }
            result["components"] = sum(1 for k in kpi if k.startswith("min_"))
        else:
            result["min"]  = kpi["min"]
            result["max"]  = kpi["max"]
            result["mean"] = kpi["mean"]
            result["std"]  = kpi["std"]
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
        info = get_field_names(proxy)
        location = "POINTS" if field_name in info["point"] else "CELLS"

        pf = run_server_script(
            proxy, _script("field_histogram.py"),
            params={"FIELD_NAME": field_name, "LOCATION": location, "NUM_BINS": num_bins},
            name=f"_hist_{field_name}",
        )
        kpi = fetch_table(pf)
        safe_delete(pf)

        if "error" in kpi:
            return {"error": f"Field '{field}' not found on server"}

        bin_centers = kpi["bin_center"] if isinstance(kpi["bin_center"], list) else [kpi["bin_center"]]
        counts = kpi["count"] if isinstance(kpi["count"], list) else [kpi["count"]]

        return {
            "field": field_name,
            "num_points": int(kpi.get("num_points", 0)),
            "bin_edges": [b - (bin_centers[1] - bin_centers[0]) / 2 for b in bin_centers] + [bin_centers[-1] + (bin_centers[-1] - bin_centers[-2]) / 2] if len(bin_centers) > 1 else bin_centers,
            "counts": [int(c) for c in counts],
            "min":  kpi["min"],
            "max":  kpi["max"],
            "mean": kpi["mean"],
            "std":  kpi["std"],
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
        """
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}
        
        try:
            # Flatten if composite (reuses existing MergeBlocks if present)
            flat_proxy, _, _flat_cleanup = ensure_flat_input(proxy)

            # Find velocity field name from metadata — no data movement
            info = get_field_names(flat_proxy)
            vel_name = None
            for name in self._VELOCITY_NAMES:
                if name in info["point"]:
                    vel_name = name
                    break
            if vel_name is None:
                # Fall back to first 3-component point field
                for name, ncomp in info["point"].items():
                    if ncomp == 3:
                        vel_name = name
                        break
            if vel_name is None:
                if _flat_cleanup:
                    safe_delete(_flat_cleanup)
                return {"error": "No velocity field found for vortex detection"}
            
            # Compute gradient with appropriate fields
            gradient = simple.Gradient(Input=flat_proxy)
            gradient.ScalarArray = ['POINTS', vel_name]
            
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
                if _flat_cleanup:
                    safe_delete(_flat_cleanup)
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
            
            # Compute threshold server-side — only scalar KPIs come back
            thresh_pf = run_server_script(
                output_proxy, _script("vortex_threshold.py"),
                params={"FIELD_NAME": field_name, "METHOD": method, "PERCENTILE": percentile},
                name=f"_thresh_{field_name}",
            )
            kpi = fetch_table(thresh_pf)
            safe_delete(thresh_pf)

            if "error" in kpi:
                return {"error": f"Could not compute {field_name}"}

            threshold  = float(kpi["threshold"])
            field_min  = float(kpi["field_min"])
            field_max  = float(kpi["field_max"])

            self._log_analysis(
                "auto_threshold",
                method="server_side",
                input_field=field_name,
                field_range=[field_min, field_max],
                result=threshold,
            )
            
            # Get output proxy name
            output_name = self._get_source_name(output_proxy)
            
            # Hide intermediate filters
            view = simple.GetActiveView()
            if view:
                intermediates = [gradient]
                if flat_proxy is not proxy:
                    intermediates.append(flat_proxy)
                for p in intermediates:
                    if p and p != output_proxy:
                        rep = simple.GetRepresentation(p, view)
                        if rep:
                            rep.Visibility = 0
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
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}

        try:
            simple.UpdatePipeline(proxy=proxy)

            # Auto-detect streamwise/lift axes if needed
            axis_map = {"x": 0, "y": 1, "z": 2}
            drag_idx = axis_map.get(streamwise_axis.lower(), 0)
            lift_idx = axis_map.get(lift_axis.lower(), 1)

            # Auto-detect freestream velocity from metadata + server script
            if freestream_velocity is None:
                stats = self.field_statistics("velocity", proxy_name=proxy_name)
                if "error" not in stats:
                    freestream_velocity = float(stats["magnitude"]["max"])
                else:
                    freestream_velocity = 1.0

            # Auto-detect reference area via projected area
            if reference_area is None:
                flow_dir = [0, 0, 0]
                flow_dir[drag_idx] = 1.0
                area_result = self.compute_projected_area(
                    flow_direction=flow_dir,
                    resolution=1024,
                    proxy_name=proxy_name,
                )
                if "error" not in area_result:
                    reference_area = area_result["area"]
                else:
                    body_bounds, _ = self._get_body_bounds(proxy)
                    if drag_idx == 0:
                        reference_area = (body_bounds[3] - body_bounds[2]) * (body_bounds[5] - body_bounds[4])
                    elif drag_idx == 1:
                        reference_area = (body_bounds[1] - body_bounds[0]) * (body_bounds[5] - body_bounds[4])
                    else:
                        reference_area = (body_bounds[1] - body_bounds[0]) * (body_bounds[3] - body_bounds[2])

            # Find pressure field name from metadata
            info = get_field_names(proxy)
            pres_name = None
            for name in ["p", "P", "Pressure", "pressure", "StaticPressure", "static_pressure"]:
                if name in info["point"] or name in info["cell"]:
                    pres_name = name
                    break
            if pres_name is None:
                return {"error": f"No pressure field found. Available: {list(info['point'].keys()) + list(info['cell'].keys())}"}

            # Build surface pipeline server-side
            flat_proxy, _, cleanup = ensure_flat_input(proxy)
            surface = simple.ExtractSurface(Input=flat_proxy)
            simple.UpdatePipeline(proxy=surface)
            normals_filter = simple.SurfaceNormals(Input=surface)
            normals_filter.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals_filter)

            # Run integration entirely server-side
            pf = run_server_script(
                normals_filter, _script("force_integration.py"),
                params={
                    "PRESSURE_FIELD":       pres_name,
                    "STREAMWISE_IDX":       drag_idx,
                    "LIFT_IDX":             lift_idx,
                    "FREESTREAM_VELOCITY":  freestream_velocity,
                    "REFERENCE_AREA":       reference_area,
                    "DENSITY":              density,
                },
                name="_force_integration",
            )
            kpi = fetch_table(pf)

            # Clean up temporary server-side filters
            safe_delete(pf)
            safe_delete(normals_filter)
            safe_delete(surface)
            if cleanup:
                safe_delete(cleanup)

            if "error" in kpi:
                return {"error": f"Force integration failed on server. Pressure field: {pres_name}"}

            result = {
                "drag_force":        kpi["drag"],
                "lift_force":        kpi["lift"],
                "force_x":           kpi["Fx"],
                "force_y":           kpi["Fy"],
                "force_z":           kpi["Fz"],
                "Cd":                kpi["Cd"],
                "Cl":                kpi["Cl"],
                "freestream_velocity": kpi["freestream_velocity"],
                "reference_area":    kpi["reference_area"],
                "density":           density,
                "total_surface_area": kpi["total_surface_area"],
                "streamwise_axis":   streamwise_axis,
                "lift_axis":         lift_axis,
            }

            self._log_analysis(
                "force_computation",
                Cd=kpi["Cd"],
                Cl=kpi["Cl"],
                drag_force=kpi["drag"],
                lift_force=kpi["lift"],
            )

            return result

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
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}

        try:
            simple.UpdatePipeline(proxy=proxy)
            axis_map = {"x": 0, "y": 1, "z": 2}

            # Resolve semantic axes using server-side streamwise detection
            if force_axis in ("auto", "streamwise", "drag", "lift") or \
               distribution_axis in ("auto", "streamwise", "span"):
                sw = self.detect_streamwise_direction(proxy_name=proxy_name)
                if "error" in sw:
                    return sw
                sw_axis = sw["streamwise"][-1].lower()
                bounds = proxy.GetDataInformation().GetBounds()
                extents = {"x": bounds[1]-bounds[0], "y": bounds[3]-bounds[2], "z": bounds[5]-bounds[4]}
                perp = [a for a in "xyz" if a != sw_axis]
                span_ax = max(perp, key=lambda a: extents[a])

                if force_axis in ("auto", "streamwise", "drag"):
                    force_axis = sw_axis
                elif force_axis == "lift":
                    force_axis = "y" if "y" in perp else perp[0]
                if distribution_axis in ("auto", "streamwise"):
                    distribution_axis = sw_axis
                elif distribution_axis == "span":
                    distribution_axis = span_ax

            force_idx = axis_map.get(force_axis.lower(), 0)
            dist_idx  = axis_map.get(distribution_axis.lower(), 0)

            # Find pressure field from metadata
            info = get_field_names(proxy)
            pres_name = None
            for name in ["p", "P", "Pressure", "pressure", "StaticPressure"]:
                if name in info["point"] or name in info["cell"]:
                    pres_name = name
                    break
            if pres_name is None:
                return {"error": "No pressure field found"}

            # Build surface pipeline server-side
            flat_proxy, _, cleanup = ensure_flat_input(proxy)
            surface = simple.ExtractSurface(Input=flat_proxy)
            simple.UpdatePipeline(proxy=surface)
            normals_filter = simple.SurfaceNormals(Input=surface)
            normals_filter.ComputeCellNormals = 1
            simple.UpdatePipeline(proxy=normals_filter)

            pf = run_server_script(
                normals_filter, _script("force_distribution.py"),
                params={
                    "PRESSURE_FIELD": pres_name,
                    "FORCE_IDX":      force_idx,
                    "DIST_IDX":       dist_idx,
                    "NUM_BINS":       num_bins,
                },
                name="_force_dist",
            )
            kpi = fetch_table(pf)
            safe_delete(pf)
            safe_delete(normals_filter)
            safe_delete(surface)
            if cleanup:
                safe_delete(cleanup)

            if "error" in kpi:
                return {"error": "Force distribution failed on server"}

            stations   = kpi["station"] if isinstance(kpi["station"], list) else [kpi["station"]]
            sectional  = kpi["sectional_force"] if isinstance(kpi["sectional_force"], list) else [kpi["sectional_force"]]
            accumulated = kpi["accumulated_force"] if isinstance(kpi["accumulated_force"], list) else [kpi["accumulated_force"]]

            return {
                "force_axis":        force_axis,
                "distribution_axis": distribution_axis,
                "stations":          stations,
                "sectional_force":   sectional,
                "accumulated_force": accumulated,
                "total_force":       float(kpi["total_force"]),
                "position_range":    [float(stations[0]), float(stations[-1])],
                "num_bins":          num_bins,
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
        from trame_llm.paraview import is_remote
        
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
            merge, _, cleanup_merge = ensure_flat_input(proxy)
            
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
            
            # Capture image — dual mode for in-process vs pvserver
            if is_remote():
                # pvserver: SaveScreenshot renders server-side, writes file
                import tempfile, os
                tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                tmp.close()
                simple.SaveScreenshot(tmp.name, view, ImageResolution=[resolution, resolution])
                from vtk import vtkPNGReader
                reader = vtkPNGReader()
                reader.SetFileName(tmp.name)
                reader.Update()
                image = reader.GetOutput()
                os.unlink(tmp.name)
            else:
                # In-process: direct framebuffer capture (faster, no disk I/O)
                from vtk import vtkWindowToImageFilter
                w2i = vtkWindowToImageFilter()
                w2i.SetInput(view.GetRenderWindow())
                w2i.Update()
                image = w2i.GetOutput()
            
            from vtk.util.numpy_support import vtk_to_numpy
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
            
            # Cleanup — children before parents
            safe_delete(view)
            safe_delete(clip)   # child of surf
            safe_delete(surf)   # child of merge
            if cleanup_merge:
                safe_delete(cleanup_merge)
            
            result = {
                "area": float(area),
                "pixel_count": covered_pixels,
                "pixel_size": float(pixel_size),
                "resolution": resolution,
                "flow_direction": flow.tolist(),
                "body_bounds": body_bounds
            }
            
            self._log_analysis(
                "projected_area",
                area=float(area),
                flow_direction=flow.tolist(),
                resolution=resolution
            )
            
            return result
            
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
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}

        try:
            # Flatten composite data if needed
            merge, _, cleanup_merge = ensure_flat_input(proxy)
            
            # Check for velocity field using metadata — no data movement
            info = get_field_names(merge)
            vel_name = None
            for name in self._VELOCITY_NAMES:
                if name in info["point"]:
                    vel_name = name
                    break
            if vel_name is None:
                for name, ncomp in info["point"].items():
                    if ncomp == 3:
                        vel_name = name
                        break
            if vel_name is None:
                if cleanup_merge:
                    safe_delete(cleanup_merge)
                return {"error": "No velocity field found"}

            # Run VortexCores filter
            vortex = simple.VortexCores(Input=merge)
            vortex.VectorField = ['POINTS', vel_name]
            simple.UpdatePipeline(proxy=vortex)

            # Get output info from metadata — no data movement
            vortex_info = vortex.GetDataInformation()
            n_points = vortex_info.GetNumberOfPoints()
            n_cores  = vortex_info.GetNumberOfCells()
            if n_points > 0:
                b = vortex_info.GetBounds()
                bounds = {
                    "x": [float(b[0]), float(b[1])],
                    "y": [float(b[2]), float(b[3])],
                    "z": [float(b[4]), float(b[5])],
                }

            if cleanup_merge:
                safe_delete(cleanup_merge)

            return {
                "vortex_filter": vortex,
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
        Compute field histogram and return Plotly-compatible data.
        
        Args:
            field: Field name or semantic type (e.g., "velocity", "pressure")
            num_bins: Number of histogram bins (default: 20)
            proxy_name: Source proxy name
            
        Returns:
            Dict with chart data for Plotly visualization
        """
        # Get histogram data from analysis function
        hist_data = self.field_histogram(
            field=field,
            num_bins=num_bins,
            proxy_name=proxy_name
        )
        
        if "error" in hist_data:
            return hist_data
        
        try:
            field_name = hist_data["field"]
            bin_edges = hist_data["bin_edges"]
            counts = hist_data["counts"]
            
            # Compute bin centers for plotting
            bin_centers = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(len(counts))]
            
            return {
                "status": "created",
                "chart_type": "histogram",
                "title": f"Distribution of {field_name}",
                "x_label": field_name,
                "y_label": "Count",
                "data": {
                    "x": bin_centers,
                    "y": counts if isinstance(counts, list) else counts.tolist(),
                    "bin_edges": bin_edges if isinstance(bin_edges, list) else bin_edges.tolist(),
                },
                "field": hist_data["field"],
                "num_points": hist_data["num_points"],
                "num_bins": len(counts),
                "min": hist_data["min"],
                "max": hist_data["max"],
                "mean": hist_data["mean"],
                "std": hist_data["std"],
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
        Compute force distribution along an axis and return Plotly-compatible data.
        
        Args:
            force_axis: "auto"/"drag", "lift", or "x"/"y"/"z"
            distribution_axis: "auto"/"streamwise", "span", or "x"/"y"/"z"
            num_bins: Number of stations (default: 40)
            proxy_name: Source proxy name
            
        Returns:
            Dict with chart data for Plotly visualization
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
            stations = dist_data["stations"]
            sectional = dist_data["sectional_force"]
            accumulated = dist_data["accumulated_force"]
            
            force_names = {"x": "Drag", "y": "Lift", "z": "Side Force"}
            force_name = force_names.get(dist_data["force_axis"].lower(), "Force")
            
            # Return Plotly-compatible chart data
            return {
                "status": "created",
                "chart_type": "force_distribution",
                "title": f"Accumulated {force_name} Distribution",
                "x_label": f'{dist_data["distribution_axis"].upper()} Position',
                "y_label": force_name,
                "data": {
                    "x": stations if isinstance(stations, list) else stations.tolist(),
                    "series": {
                        "Accumulated Force": accumulated if isinstance(accumulated, list) else accumulated.tolist(),
                        "Sectional Force": sectional if isinstance(sectional, list) else sectional.tolist(),
                    }
                },
                "force_axis": dist_data["force_axis"],
                "distribution_axis": dist_data["distribution_axis"],
                "total_force": dist_data["total_force"],
                "position_range": dist_data["position_range"],
                "num_bins": dist_data["num_bins"],
                "num_body_cells": dist_data["num_body_cells"],
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
        proxy = self._get_proxy(proxy_name)
        if proxy is None:
            return {"error": "No proxy found"}

        try:
            simple.UpdatePipeline(proxy=proxy)

            # Find velocity field name from metadata
            flat_proxy, _, cleanup = ensure_flat_input(proxy)
            info = get_field_names(flat_proxy)
            vel_name = None
            for name in self._VELOCITY_NAMES:
                if name in info["point"]:
                    vel_name = name
                    break
            if vel_name is None:
                for name, ncomp in info["point"].items():
                    if ncomp == 3:
                        vel_name = name
                        break
            if cleanup:
                safe_delete(cleanup)
            if vel_name is None:
                return {"error": f"No velocity field found. Available: {list(info['point'].keys())}"}

            # Run detection server-side
            pf = run_server_script(
                proxy, _script("detect_streamwise.py"),
                params={"VELOCITY_FIELD": vel_name},
                name="_detect_streamwise",
            )
            kpi = fetch_table(pf)
            safe_delete(pf)

            if "error" in kpi:
                return {"error": "Streamwise detection failed on server"}

            streamwise    = kpi["streamwise"]
            axis_name     = kpi["axis_name"]
            freestream    = float(kpi["freestream_velocity"])
            axis_idx      = int(kpi["streamwise_axis"])
            direction_sign = int(kpi["direction_sign"])

            # Derive span and vertical axes
            all_axes = ["x", "y", "z"]
            remaining = [a for a in all_axes if a != axis_name]
            body_bounds, body_diag = self._get_body_bounds(proxy)
            spans = {a: body_bounds[2 * all_axes.index(a) + 1] - body_bounds[2 * all_axes.index(a)]
                     for a in remaining}
            span_axis = max(spans, key=spans.get)
            vertical_axis = [a for a in remaining if a != span_axis][0]
            body_center = [
                0.5 * (body_bounds[0] + body_bounds[1]),
                0.5 * (body_bounds[2] + body_bounds[3]),
                0.5 * (body_bounds[4] + body_bounds[5]),
            ]

            self._log_analysis(
                "streamwise_detection",
                method="server_side_mean_velocity",
                velocity_field=vel_name,
                result=streamwise,
            )

            return {
                "streamwise": streamwise,
                "span_axis": span_axis,
                "vertical_axis": vertical_axis,
                "velocity_field": vel_name,
                "freestream_velocity": freestream,
                "body_center": body_center,
                "body_bounds": list(body_bounds),
                "confidence": float(kpi.get("direction_sign", 1)),
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
            
            result = {
                "span_axis": span_axis,
                "streamwise_axis": streamwise_axis,
                "vertical_axis": vertical_axis,
                "extents": extents,
                "body_bounds": list(body_bounds),
                "body_center": body_center,
                "span_extent": extents[span_axis],
                "velocity_field": streamwise_result.get("velocity_field", "Velocity"),
            }
            
            self._log_analysis(
                "span_direction",
                span_axis=span_axis,
                streamwise_axis=streamwise_axis,
                span_extent=extents[span_axis]
            )
            
            return result
            
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
            
            result = {
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
            
            self._log_analysis(
                "spanwise_slice_params",
                offset=offset,
                span_axis=span_axis,
                origin=origin
            )
            
            return result
            
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

        try:
            # All heavy lifting runs server-side — only scalar KPIs come back

            # Get streamwise direction (server-side)
            streamwise_result = self.detect_streamwise_direction(proxy_name=proxy_name)
            if "error" in streamwise_result:
                return streamwise_result
            streamwise    = streamwise_result["streamwise"]
            vel_name      = streamwise_result["velocity_field"]
            v_freestream  = streamwise_result["freestream_velocity"]

            axis_map = {"x": 0, "+x": 0, "-x": 0,
                        "y": 1, "+y": 1, "-y": 1,
                        "z": 2, "+z": 2, "-z": 2}
            stream_idx    = axis_map.get(streamwise.lower(), 0)
            stream_sign   = -1 if streamwise.startswith("-") else 1

            # Body bounds from metadata
            body_bounds, _ = self._get_body_bounds(proxy)
            if stream_sign > 0:
                trailing_edge = float(body_bounds[stream_idx * 2 + 1])
            else:
                trailing_edge = float(body_bounds[stream_idx * 2])

            pf = run_server_script(
                proxy, _script("detect_wake.py"),
                params={
                    "VELOCITY_FIELD":    vel_name,
                    "VELOCITY_DEFICIT":  velocity_deficit,
                    "STREAMWISE_IDX":    stream_idx,
                    "STREAMWISE_SIGN":   stream_sign,
                    "TRAILING_EDGE_COORD": trailing_edge,
                },
                name="_detect_wake",
            )
            kpi = fetch_table(pf)
            safe_delete(pf)

            if "error" in kpi:
                return {
                    "error": f"No wake found with velocity < {velocity_deficit*100:.0f}% of freestream",
                    "freestream_velocity": v_freestream,
                }

            centroid = [kpi["wake_x"], kpi["wake_y"], kpi["wake_z"]]
            bounds   = [kpi["wake_xmin"], kpi["wake_xmax"],
                        kpi["wake_ymin"], kpi["wake_ymax"],
                        kpi["wake_zmin"], kpi["wake_zmax"]]

            result = {
                "wake_centroid":          centroid,
                "wake_bounds":            bounds,
                "num_points":             int(kpi["num_wake_points"]),
                "freestream_velocity":    float(kpi["freestream_velocity"]),
                "velocity_threshold":     velocity_deficit * float(kpi["freestream_velocity"]),
                "velocity_deficit_fraction": velocity_deficit,
                "streamwise":             streamwise,
                "trailing_edge_coord":    trailing_edge,
            }

            self._log_analysis(
                "wake_detection",
                velocity_deficit_fraction=velocity_deficit,
                freestream_velocity=result["freestream_velocity"],
                streamwise_direction=streamwise,
                wake_centroid=centroid,
                num_points=result["num_points"],
            )

            return result

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
            
            # Log the seed computation
            self._log_analysis(
                "streamline_seed_computation",
                center=center,
                radius=float(radius),
                num_points=100,
                source="wake_detection" if (wake_result and "wake_centroid" in wake_result) else "body_geometry_fallback"
            )
            
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
            
            result = {
                "origin": origin,
                "normal_vector": normal_vector,
                "normal_axis": normal,
                "body_center": center,
                "body_bounds": list(body_bounds),
            }
            
            self._log_analysis(
                "slice_params",
                normal=normal,
                offset=offset,
                origin=origin
            )
            
            return result
            
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
                        safe_delete(proxy)
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

    def save_all_charts(
        self,
        prefix: str = "output/chart",
        width: int = 800,
        height: int = 600
    ) -> dict:
        """
        Save all pending chart views to files.
        
        Charts are created by workflows like show_boundary_layer, show_histogram,
        show_forces, etc. This saves all of them at once with sequential numbering.
        
        Args:
            prefix: Output filename prefix (e.g., "output/bl" -> bl_0.png, bl_1.png, ...)
            width: Image width in pixels (default: 800)
            height: Image height in pixels (default: 600)
            
        Returns:
            Dict with list of saved filenames and count
        """
        import os
        
        chart_views = getattr(self, '_chart_view_queue', [])
        if not chart_views:
            return {"status": "no_charts", "count": 0, "files": []}
        
        # Ensure directory exists
        dirname = os.path.dirname(prefix)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        saved_files = []
        errors = []
        
        for i, view in enumerate(chart_views):
            filename = f"{prefix}_{i}.png"
            try:
                simple.Render(view)
                simple.SaveScreenshot(filename, view, ImageResolution=[width, height])
                
                # Get chart title if available
                title = getattr(view, 'ChartTitle', f'Chart {i}')
                saved_files.append({"filename": filename, "title": title})
            except Exception as e:
                errors.append({"filename": filename, "error": str(e)})
        
        # Clear the queue after saving
        self._chart_view_queue = []
        
        result = {
            "status": "saved",
            "count": len(saved_files),
            "files": saved_files
        }
        
        if errors:
            result["errors"] = errors
        
        return result
    
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
    
    def _get_source_name(self, proxy) -> str:
        """Get the registered name of a proxy."""
        if proxy is None:
            return None
        for name, p in simple.GetSources().items():
            if p == proxy:
                return name[0]  # name is tuple (name, id)
        return None
    
    def compute_boundary_layer_profile(self, proxy=None, x_over_chord: float = 0.5,
                                        span_fraction: float = 0.5,
                                        probe_length: float = None, proxy_name: str = None,
                                        _shared_surface=None) -> dict:
        """
        Compute boundary layer profile data at a given chordwise and spanwise location.

        Cuts a spanwise plane to get the airfoil section (client-side geometry, small),
        then runs the velocity probe and BL integral computation server-side via
        ProgrammableFilter (boundary_layer.py). No field data moves to the client.

        Args:
            proxy: Data proxy (default: active source)
            x_over_chord: Chordwise location as fraction of chord (0=LE, 1=TE)
            span_fraction: Spanwise location as fraction of span (0=root, 1=tip)
            probe_length: Probe distance into flow (default: 30% of chord)
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
        
        # Save the original active source to restore later
        original_active_source = simple.GetActiveSource()
        
        if proxy_name is None:
            proxy_name = proxy.GetGlobalIDAsString()
        
        # Flatten composite data (reuses existing MergeBlocks if present)
        merge, _, cleanup_merge = ensure_flat_input(proxy)
        
        # Get body bounds (excludes farfield)
        body_bounds, _ = self._get_body_bounds(proxy)
        
        # Detect geometry orientation - set active source first since detect_span_direction uses it
        simple.SetActiveSource(proxy)
        span_info = self.detect_span_direction(proxy_name=None)
        if "error" in span_info:
            simple.SetActiveSource(original_active_source)
            return {"error": f"Could not detect span direction: {span_info['error']}"}
        span_axis = span_info.get("span_axis", "y")
        vertical_axis = span_info.get("vertical_axis", "z")
        streamwise_axis = span_info.get("streamwise_axis", "x")
        velocity_field = span_info.get("velocity_field", "Velocity")
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
        
        # Compute absolute positions
        x_abs = stream_min + x_over_chord * chord
        span_abs = span_min + span_fraction * span_extent
        
        # Step 1: Extract body surface and clip to body region
        if _shared_surface is not None:
            clip = _shared_surface
            surface = None
            owns_surface = False
        else:
            # Check cache: reuse existing surface+clip for same proxy
            cache = getattr(self, '_bl_surface_cache', None)
            if cache and cache.get('proxy_id') == proxy.GetGlobalIDAsString():
                clip = cache['clip']
                surface = cache['surface']
                owns_surface = False
                print(f"[BL] Reusing cached ExtractSurface+Clip")
            else:
                print(f"[BL] Creating new ExtractSurface+Clip")
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
                owns_surface = False  # cache owns it now
                self._bl_surface_cache = {
                    'proxy_id': proxy.GetGlobalIDAsString(),
                    'clip': clip,
                    'surface': surface,
                    'merge_cleanup': cleanup_merge,
                }
        simple.UpdatePipeline(proxy=clip)
        
        # Step 2: Cut with a plane at the span station to get airfoil section
        plane_cut = simple.Slice(Input=clip)
        plane_cut.SliceType = 'Plane'
        
        # Set plane origin and normal based on span axis
        origin = [0, 0, 0]
        origin[span_idx] = span_abs
        normal = [0, 0, 0]
        normal[span_idx] = 1.0
        
        plane_cut.SliceType.Origin = origin
        plane_cut.SliceType.Normal = normal
        simple.UpdatePipeline(proxy=plane_cut)
        
        cut_data = fetch_data(plane_cut)
        
        def cleanup():
            safe_delete(plane_cut)
            if owns_surface:
                safe_delete(clip)
                if surface is not None:
                    safe_delete(surface)
                if cleanup_merge:
                    safe_delete(cleanup_merge)
            simple.SetActiveSource(original_active_source)
        
        if cut_data.GetNumberOfPoints() == 0:
            cleanup()
            return {"error": f"Plane cut at span_fraction={span_fraction} returned no points"}
        
        cut_points = vtk_to_numpy(cut_data.GetPoints().GetData())
        
        # Step 3: Compute actual section chord from LE to TE
        le_idx = np.argmin(cut_points[:, stream_idx])
        te_idx = np.argmax(cut_points[:, stream_idx])
        le_point = cut_points[le_idx]
        te_point = cut_points[te_idx]
        section_chord = np.linalg.norm(te_point - le_point)
        section_le = le_point[stream_idx]
        section_te = te_point[stream_idx]
        
        # Use section chord for x/c calculation
        x_abs = section_le + x_over_chord * section_chord
        
        # Step 4: Select suction side (upper surface for typical wing orientation)
        suction_mask = cut_points[:, vert_idx] > vert_center
        suction_points = cut_points[suction_mask]
        pressure_points = cut_points[~suction_mask]
        
        if len(suction_points) == 0:
            cleanup()
            return {"error": "No suction side points found in cut section"}
        
        # Sort points by streamwise coordinate for proper contour ordering
        suction_sorted_idx = np.argsort(suction_points[:, stream_idx])
        suction_points_sorted = suction_points[suction_sorted_idx]
        
        pressure_sorted_idx = np.argsort(pressure_points[:, stream_idx])[::-1]  # TE to LE
        pressure_points_sorted = pressure_points[pressure_sorted_idx] if len(pressure_points) > 0 else np.array([])
        
        # Find point closest to requested x/c
        x_distances = np.abs(suction_points[:, stream_idx] - x_abs)
        best_local_idx = np.argmin(x_distances)
        
        surface_point = suction_points[best_local_idx].copy()
        
        # Actual x/c at the probed point (using section chord)
        actual_x_over_chord = (surface_point[stream_idx] - section_le) / section_chord
        
        # Step 5: Compute surface normal from the 2D section
        # Sort suction side points by streamwise coordinate
        sort_idx = np.argsort(suction_points[:, stream_idx])
        sorted_suction = suction_points[sort_idx]
        
        # Find index in sorted array
        sorted_local_idx = np.searchsorted(sorted_suction[:, stream_idx], surface_point[stream_idx])
        sorted_local_idx = np.clip(sorted_local_idx, 1, len(sorted_suction) - 2)
        
        # Compute tangent from neighboring points
        pt_before = sorted_suction[sorted_local_idx - 1]
        pt_after = sorted_suction[min(sorted_local_idx + 1, len(sorted_suction) - 1)]
        
        tangent = pt_after - pt_before
        tangent = tangent / (np.linalg.norm(tangent) + 1e-10)
        
        # Normal is perpendicular to tangent in the streamwise-vertical plane
        # For 2D section: rotate tangent 90 degrees in the (stream, vert) plane
        surface_normal = np.zeros(3)
        surface_normal[stream_idx] = -tangent[vert_idx]
        surface_normal[vert_idx] = tangent[stream_idx]
        surface_normal[span_idx] = 0.0  # No span component
        
        # Ensure normal points outward (away from body center)
        from_center = surface_point - body_center
        if np.dot(surface_normal, from_center) < 0:
            surface_normal = -surface_normal
        
        # Normalize
        surface_normal = surface_normal / (np.linalg.norm(surface_normal) + 1e-10)
        
        # Step 6: Run BL probe and computation server-side
        # surface_point and surface_normal are small scalars — safe to inject
        pf = run_server_script(
            merge, _script("boundary_layer.py"),
            params={
                "VELOCITY_FIELD":   velocity_field,
                "SURFACE_POINT":    surface_point.tolist(),
                "SURFACE_NORMAL":   surface_normal.tolist(),
                "PROBE_LENGTH":     float(probe_length),
                "NUM_PROBE_POINTS": 200,
            },
            name="_bl_probe",
        )
        kpi = fetch_table(pf)
        safe_delete(pf)
        cleanup()

        if "error" in kpi:
            return {"error": "Boundary layer probe failed on server"}

        y           = kpi["y"] if isinstance(kpi["y"], list) else [kpi["y"]]
        u           = kpi["u"] if isinstance(kpi["u"], list) else [kpi["u"]]
        u_normalized = kpi["u_normalized"] if isinstance(kpi["u_normalized"], list) else [kpi["u_normalized"]]

        delta        = float(kpi["delta"])
        delta_star   = float(kpi["delta_star"])
        theta        = float(kpi["theta"])
        shape_factor = float(kpi["shape_factor"])
        u_edge       = float(kpi["u_edge"])
        u_edge_idx   = int(kpi["u_edge_idx"])

        result = {
            "y": y,
            "u": u,
            "u_normalized": u_normalized,
            "u_edge": u_edge,
            "u_edge_idx": u_edge_idx,
            "delta": float(delta),
            "delta_star": float(delta_star),
            "theta": float(theta),
            "shape_factor": float(shape_factor),
            "surface": "suction",
            "surface_point": surface_point.tolist(),
            "surface_normal": surface_normal.tolist(),
            "x_over_chord": float(actual_x_over_chord),
            "x_over_chord_requested": float(x_over_chord),
            "x_absolute": float(surface_point[stream_idx]),
            "span_fraction": float(span_fraction),
            "span_absolute": float(span_abs),
            "section": {
                "chord": float(section_chord),
                "le": le_point.tolist(),
                "te": te_point.tolist(),
                "suction_contour": suction_points_sorted[:, [stream_idx, vert_idx]].tolist(),
                "pressure_contour": pressure_points_sorted[:, [stream_idx, vert_idx]].tolist() if len(pressure_points_sorted) > 0 else [],
                "stream_idx": stream_idx,
                "vert_idx": vert_idx
            },
            "geometry": {
                "body_chord": float(chord),
                "span_extent": float(span_extent),
                "thickness": float(thickness),
                "streamwise_axis": streamwise_axis,
                "span_axis": span_axis,
                "vertical_axis": vertical_axis
            },
            "probe_length": float(probe_length)
        }
        
        self._log_analysis(
            "boundary_layer_profile",
            x_over_chord=float(actual_x_over_chord),
            span_fraction=span_fraction,
            delta=float(delta),
            delta_star=float(delta_star),
            theta=float(theta),
            shape_factor=float(shape_factor),
            u_edge=float(u_edge)
        )
        
        return result
