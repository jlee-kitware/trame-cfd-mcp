"""
CFD Ontology - Triple-based knowledge representation for CFD post-processing.

This module represents CFD domain knowledge as semantic triples (subject, predicate, object)
enabling reasoning and inference for workflow planning.

Key capabilities:
- Infer prerequisites for any goal (walk backward through requires/computed_from)
- Plan workflows by reasoning about available data vs required data
- Extend knowledge by adding triples (no hardcoded workflows)
"""

from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


@dataclass
class Triple:
    """A semantic triple: (subject, predicate, object)."""
    subject: str
    predicate: str
    object: str
    
    def __iter__(self):
        return iter((self.subject, self.predicate, self.object))
    
    def __repr__(self):
        return f"({self.subject}, {self.predicate}, {self.object})"


class CFDOntology:
    """
    Triple-based CFD domain ontology.
    
    Supports inference and workflow planning through graph traversal.
    """
    
    # Core predicates
    DETECTED_BY = "detected_by"          # flow_feature → detection_method
    REQUIRES = "requires"                 # computation → input_field
    COMPUTED_FROM = "computed_from"       # derived_field → source_field
    VISUALIZED_BY = "visualized_by"       # feature/field → visualization_type
    IS_A = "is_a"                         # instance → type
    COMPONENT_OF = "component_of"         # scalar → vector
    ACTS_ALONG = "acts_along"             # force → direction
    TOOL_FOR = "tool_for"                 # mcp_tool → action
    PRODUCES = "produces"                 # tool → output_type
    
    def __init__(self):
        self.triples: list[Triple] = []
        
        # Indexes for fast lookup
        self._by_subject: dict[str, list[Triple]] = defaultdict(list)
        self._by_predicate: dict[str, list[Triple]] = defaultdict(list)
        self._by_object: dict[str, list[Triple]] = defaultdict(list)
        
        # Load core CFD knowledge
        self._load_core_ontology()
    
    def add(self, subject: str, predicate: str, obj: str):
        """Add a triple to the ontology."""
        t = Triple(subject, predicate, obj)
        self.triples.append(t)
        self._by_subject[subject].append(t)
        self._by_predicate[predicate].append(t)
        self._by_object[obj].append(t)
    
    def query(self, 
              subject: Optional[str] = None,
              predicate: Optional[str] = None, 
              obj: Optional[str] = None) -> list[Triple]:
        """
        Query triples by pattern matching.
        
        None means "any value" (wildcard).
        
        Examples:
            query(subject="vortex")  # All triples about vortex
            query(predicate="requires")  # All requirement relationships
            query(obj="velocity")  # All things that relate to velocity
        """
        if subject and not predicate and not obj:
            return self._by_subject.get(subject, [])
        if predicate and not subject and not obj:
            return self._by_predicate.get(predicate, [])
        if obj and not subject and not predicate:
            return self._by_object.get(obj, [])
        
        # General case: filter all triples
        results = []
        for t in self.triples:
            if subject and t.subject != subject:
                continue
            if predicate and t.predicate != predicate:
                continue
            if obj and t.object != obj:
                continue
            results.append(t)
        return results
    
    def get_objects(self, subject: str, predicate: str) -> list[str]:
        """Get all objects where (subject, predicate, ?)."""
        return [t.object for t in self.query(subject=subject, predicate=predicate)]
    
    def get_subjects(self, predicate: str, obj: str) -> list[str]:
        """Get all subjects where (?, predicate, object)."""
        return [t.subject for t in self.query(predicate=predicate, obj=obj)]
    
    def infer_requirements(self, goal: str, visited: set = None) -> set[str]:
        """
        Recursively find all requirements for a goal.
        
        Walks backward through 'requires' and 'computed_from' relationships.
        
        Example:
            infer_requirements("q_criterion")
            → {"velocity_gradient", "velocity"}
        """
        if visited is None:
            visited = set()
        
        if goal in visited:
            return set()
        visited.add(goal)
        
        requirements = set()
        
        # Direct requirements
        for req in self.get_objects(goal, self.REQUIRES):
            requirements.add(req)
            requirements.update(self.infer_requirements(req, visited))
        
        # Computed from (also a dependency)
        for source in self.get_objects(goal, self.COMPUTED_FROM):
            requirements.add(source)
            requirements.update(self.infer_requirements(source, visited))
        
        return requirements
    
    def infer_detection_chain(self, feature: str) -> list[str]:
        """
        Find the chain of methods/fields needed to detect a flow feature.
        
        Example:
            infer_detection_chain("vortex")
            → ["q_criterion", "velocity_gradient", "velocity"]
        """
        chain = []
        
        # What detects this feature?
        detectors = self.get_objects(feature, self.DETECTED_BY)
        for detector in detectors:
            chain.append(detector)
            # What does the detector require?
            reqs = self.infer_requirements(detector)
            chain.extend(reqs)
        
        return chain
    
    def find_visualization(self, target: str) -> list[str]:
        """Find appropriate visualization types for a target."""
        # Direct visualization
        viz = self.get_objects(target, self.VISUALIZED_BY)
        if viz:
            return viz
        
        # Check if it's a type, find visualizations for that type
        types = self.get_objects(target, self.IS_A)
        for t in types:
            viz = self.get_objects(t, self.VISUALIZED_BY)
            if viz:
                return viz
        
        return []
    
    def find_tool(self, action: str) -> list[str]:
        """Find tools that perform an action."""
        return self.get_subjects(self.TOOL_FOR, action)
    
    def get_components(self, vector: str) -> list[str]:
        """Get scalar components of a vector field."""
        return self.get_subjects(self.COMPONENT_OF, vector)
    
    def plan_workflow(self, goal: str, available_fields: set[str]) -> dict:
        """
        Plan a workflow to achieve a goal given available data.
        
        Returns a plan with:
        - steps: Ordered list of actions
        - missing: Fields that need to be computed
        - tools: Suggested tools for each step
        
        Example:
            plan_workflow("visualize_vortex", {"u", "v", "w", "p"})
            → {
                "steps": [
                    {"action": "assemble_vector", "inputs": ["u","v","w"], "output": "velocity"},
                    {"action": "compute_gradient", "inputs": ["velocity"], "output": "velocity_gradient"},
                    {"action": "compute_q_criterion", "inputs": ["velocity_gradient"], "output": "q_criterion"},
                    {"action": "create_isosurface", "inputs": ["q_criterion"], "output": "vortex_visualization"}
                ],
                "tools": ["ensure_velocity_vector", "Gradient", "create_vortex_isosurface"]
            }
        """
        plan = {"goal": goal, "steps": [], "tools": [], "reasoning": []}
        
        # What does the goal require?
        if goal.startswith("visualize_"):
            feature = goal.replace("visualize_", "")
            detection_chain = self.infer_detection_chain(feature)
            plan["reasoning"].append(f"{feature} detected_by {detection_chain}")
        else:
            detection_chain = [goal]
        
        # Work backward: what do we need that we don't have?
        needed = set(detection_chain)
        computed = set()
        
        # Check what's available (including aliases)
        have = set(available_fields)
        
        # Check if velocity can be assembled from components
        velocity_components = self.get_components("velocity")
        if velocity_components and all(c in have for c in velocity_components):
            if "velocity" not in have:
                plan["steps"].append({
                    "action": "assemble_vector",
                    "inputs": list(velocity_components),
                    "output": "velocity",
                    "reason": f"velocity component_of [{', '.join(velocity_components)}]"
                })
                plan["tools"].append("ensure_velocity_vector")
                have.add("velocity")
                computed.add("velocity")
        
        # For each needed field, check if we can compute it
        for field in detection_chain:
            if field in have:
                plan["reasoning"].append(f"{field}: already available")
                continue
            
            # What is it computed from?
            sources = self.get_objects(field, self.COMPUTED_FROM)
            if sources:
                source = sources[0]  # Take first option
                if source in have or source in computed:
                    plan["steps"].append({
                        "action": f"compute_{field}",
                        "inputs": [source],
                        "output": field,
                        "reason": f"{field} computed_from {source}"
                    })
                    # Find tool
                    tools = self.find_tool(f"compute_{field}")
                    if tools:
                        plan["tools"].append(tools[0])
                    computed.add(field)
                else:
                    plan["reasoning"].append(f"{field}: need {source} first")
        
        # Final visualization step
        viz_types = self.find_visualization(goal.replace("visualize_", ""))
        if viz_types:
            viz_type = viz_types[0]
            plan["steps"].append({
                "action": f"create_{viz_type}",
                "inputs": [detection_chain[0]] if detection_chain else [],
                "output": f"{goal}_result",
                "reason": f"{goal.replace('visualize_', '')} visualized_by {viz_type}"
            })
            tools = self.find_tool(f"create_{viz_type}")
            if tools:
                plan["tools"].append(tools[0])
        
        return plan
    
    def explain(self, subject: str) -> str:
        """Generate a human-readable explanation of an entity."""
        lines = [f"## {subject}"]
        
        for t in self.query(subject=subject):
            lines.append(f"  - {t.predicate} → {t.object}")
        
        # Also show what references this subject
        for t in self.query(obj=subject):
            lines.append(f"  - (referenced by {t.subject} via {t.predicate})")
        
        return "\n".join(lines)
    
    def generate_llm_context(self, goal: str, available_fields: set[str]) -> str:
        """
        Generate context for LLM including relevant triples and reasoning hints.
        
        This allows the LLM to reason about the domain rather than
        following hardcoded workflows.
        """
        lines = ["# CFD Domain Knowledge (Semantic Triples)"]
        lines.append("")
        lines.append("Use these relationships to reason about the user's request:")
        lines.append("")
        
        # Extract the entity from goal
        entity = goal.replace("visualize_", "").replace("compute_", "").replace("analyze_", "")
        
        # Relevant triples about the entity
        lines.append(f"## About '{entity}':")
        for t in self.query(subject=entity):
            lines.append(f"  ({t.subject}, {t.predicate}, {t.object})")
        
        # Detection/computation chain
        chain = self.infer_detection_chain(entity) if entity else []
        if chain:
            lines.append(f"\n## Detection/computation chain for {entity}:")
            for item in chain:
                for t in self.query(subject=item):
                    if t.predicate in ["computed_from", "requires", "detected_by"]:
                        lines.append(f"  ({t.subject}, {t.predicate}, {t.object})")
        
        # What we have
        lines.append(f"\n## Available data: {available_fields}")
        
        # Check velocity assembly
        components = self.get_components("velocity")
        if components:
            have_all = all(c in available_fields for c in components)
            lines.append(f"## Velocity components: {components}")
            lines.append(f"   Can assemble velocity: {have_all}")
        
        # Visualization options
        viz = self.find_visualization(entity)
        if viz:
            lines.append(f"\n## Visualization options for {entity}: {viz}")
        
        # Tool mappings
        lines.append("\n## Relevant tools:")
        for tool in ["ensure_velocity_vector", "Gradient", "create_vortex_isosurface", 
                     "compute_forces", "create_force_distribution_chart", "find_minimum"]:
            produces = self.get_objects(tool, "produces")
            actions = self.get_objects(tool, "tool_for")
            if produces or actions:
                lines.append(f"  {tool}: produces={produces}, actions={actions}")
        
        lines.append("\n## Reasoning instructions:")
        lines.append("1. Walk backward from goal through 'computed_from' and 'requires'")
        lines.append("2. Check if each requirement is in available_fields")
        lines.append("3. If not, find how to compute it")
        lines.append("4. Build plan from data → derived fields → goal")
        
        return "\n".join(lines)
    
    def _load_core_ontology(self):
        """Load fundamental CFD domain knowledge."""
        
        # ===================
        # TYPE HIERARCHY
        # ===================
        self.add("velocity", "is_a", "vector_field")
        self.add("vorticity", "is_a", "vector_field")
        self.add("pressure", "is_a", "scalar_field")
        self.add("density", "is_a", "scalar_field")
        self.add("temperature", "is_a", "scalar_field")
        self.add("q_criterion", "is_a", "scalar_field")
        self.add("velocity_magnitude", "is_a", "scalar_field")
        
        self.add("vortex", "is_a", "flow_feature")
        self.add("wake", "is_a", "flow_feature")
        self.add("stagnation_point", "is_a", "flow_feature")
        self.add("separation", "is_a", "flow_feature")
        self.add("shear_layer", "is_a", "flow_feature")
        
        self.add("drag", "is_a", "force")
        self.add("lift", "is_a", "force")
        self.add("side_force", "is_a", "force")
        
        # ===================
        # VECTOR COMPONENTS
        # ===================
        self.add("u", "component_of", "velocity")
        self.add("v", "component_of", "velocity")
        self.add("w", "component_of", "velocity")
        
        # ===================
        # FIELD DERIVATIONS
        # ===================
        self.add("velocity_gradient", "computed_from", "velocity")
        self.add("q_criterion", "computed_from", "velocity_gradient")
        self.add("vorticity", "computed_from", "velocity_gradient")
        self.add("velocity_magnitude", "computed_from", "velocity")
        self.add("pressure_gradient", "computed_from", "pressure")
        
        # ===================
        # FLOW FEATURE DETECTION
        # ===================
        self.add("vortex", "detected_by", "q_criterion")
        self.add("vortex", "detected_by", "vorticity_magnitude")
        self.add("vortex", "detected_by", "lambda2")
        self.add("vortex", "detected_by", "helicity")
        self.add("vortex", "detected_by", "swirling_strength")
        
        # Helicity relationships
        self.add("helicity", "is_a", "scalar_field")
        self.add("helicity", "computed_from", "velocity")
        self.add("helicity", "computed_from", "vorticity")
        self.add("helicity", "measures", "vortex_alignment")
        self.add("normalized_helicity", "alias_of", "helicity")
        
        # Swirling strength relationships
        self.add("swirling_strength", "is_a", "scalar_field")
        self.add("swirling_strength", "computed_from", "velocity_gradient")
        self.add("swirling_strength", "measures", "local_rotation")
        
        # Lambda2 relationships  
        self.add("lambda2", "is_a", "scalar_field")
        self.add("lambda2", "computed_from", "velocity_gradient")
        self.add("lambda2", "measures", "pressure_minimum")
        
        self.add("wake", "detected_by", "velocity_deficit")
        self.add("velocity_deficit", "computed_from", "velocity_magnitude")
        
        self.add("stagnation_point", "detected_by", "velocity_minimum")
        self.add("velocity_minimum", "computed_from", "velocity_magnitude")
        
        self.add("shear_layer", "detected_by", "velocity_gradient_magnitude")
        self.add("velocity_gradient_magnitude", "computed_from", "velocity_gradient")
        
        self.add("separation", "detected_by", "wall_shear_stress")
        self.add("wall_shear_stress", "requires", "velocity_gradient")
        self.add("wall_shear_stress", "requires", "surface_normals")
        
        # ===================
        # FORCE COMPUTATION
        # ===================
        self.add("drag", "computed_from", "surface_pressure")
        self.add("drag", "acts_along", "streamwise")
        self.add("lift", "computed_from", "surface_pressure")
        self.add("lift", "acts_along", "vertical")
        
        self.add("surface_pressure", "requires", "pressure")
        self.add("surface_pressure", "requires", "surface_normals")
        
        # ===================
        # VISUALIZATION MAPPINGS
        # ===================
        self.add("scalar_field", "visualized_by", "isosurface")
        self.add("scalar_field", "visualized_by", "slice")
        self.add("scalar_field", "visualized_by", "volume_render")
        
        self.add("vector_field", "visualized_by", "streamlines")
        self.add("vector_field", "visualized_by", "glyphs")
        self.add("vector_field", "visualized_by", "slice")
        
        self.add("vortex", "visualized_by", "isosurface")
        self.add("wake", "visualized_by", "streamlines")
        self.add("wake", "visualized_by", "slice")
        self.add("stagnation_point", "visualized_by", "point_marker")
        self.add("stagnation_point", "visualized_by", "slice")
        
        self.add("force", "visualized_by", "distribution_chart")
        self.add("force", "visualized_by", "bar_chart")
        
        # ===================
        # TOOL MAPPINGS
        # ===================
        self.add("ensure_velocity_vector", "tool_for", "assemble_vector")
        self.add("ensure_velocity_vector", "produces", "velocity")
        
        self.add("Gradient", "tool_for", "compute_velocity_gradient")
        self.add("Gradient", "produces", "velocity_gradient")
        
        self.add("create_vortex_isosurface", "tool_for", "compute_q_criterion")
        self.add("create_vortex_isosurface", "tool_for", "create_isosurface")
        self.add("create_vortex_isosurface", "produces", "q_criterion")
        
        self.add("compute_forces", "tool_for", "compute_drag")
        self.add("compute_forces", "tool_for", "compute_lift")
        self.add("compute_forces", "produces", "force")
        
        self.add("create_force_distribution_chart", "tool_for", "create_distribution_chart")
        self.add("create_force_distribution_chart", "produces", "distribution_chart")
        
        self.add("detect_wake_region", "tool_for", "detect_wake")
        self.add("detect_wake_region", "produces", "wake_centroid")
        self.add("detect_wake_region", "requires", "velocity")
        
        self.add("create_streamlines", "tool_for", "visualize_wake")
        self.add("create_streamlines", "tool_for", "visualize_flow_pattern")
        self.add("create_streamlines", "produces", "streamlines")
        self.add("create_streamlines", "requires", "velocity")
        self.add("streamlines", "seeded_from", "wake_centroid")
        
        self.add("find_minimum", "tool_for", "detect_stagnation_point")
        self.add("find_maximum", "tool_for", "detect_peak")
        
        # ===================
        # GEOMETRY AND POSITIONING
        # ===================
        # Tools for getting geometric information
        self.add("get_geometry_info", "provides", "bounds")
        self.add("get_geometry_info", "provides", "center")
        self.add("get_geometry_info", "provides", "extents")
        self.add("get_geometry_info", "provides", "longest_axis")
        
        # Positioning strategies for slices
        self.add("slice", "positioned_at", "center")
        self.add("slice", "positioned_at", "stagnation_point")
        self.add("slice", "positioned_at", "wake_centroid")
        self.add("slice", "positioned_at", "maximum_location")
        self.add("slice", "positioned_at", "minimum_location")
        
        # How to get positions
        self.add("center", "computed_by", "get_geometry_info")
        self.add("bounds", "computed_by", "get_geometry_info")
        self.add("stagnation_point", "computed_by", "find_minimum")
        self.add("wake_centroid", "computed_by", "detect_wake_region")
        self.add("maximum_location", "computed_by", "find_maximum")
        self.add("minimum_location", "computed_by", "find_minimum")
        
        # Slice normal directions
        self.add("slice", "has_parameter", "normal")
        self.add("slice", "has_parameter", "origin")
        self.add("normal", "can_be", "streamwise")
        self.add("normal", "can_be", "spanwise")
        self.add("normal", "can_be", "vertical")
        self.add("streamwise", "typically", "x_axis")
        self.add("spanwise", "typically", "z_axis")
        self.add("vertical", "typically", "y_axis")
        
        # Slice use cases
        self.add("visualize_cross_section", "uses", "slice")
        self.add("visualize_wake", "uses", "slice")
        self.add("visualize_wake", "positions_slice_at", "wake_centroid")
        self.add("visualize_cross_section", "positions_slice_at", "center")
        
        # ===================
        # BASE TOOL USAGE PATTERNS
        # ===================
        # How to use base ParaView tools correctly
        
        # Slice filter setup
        self.add("Slice", "is_a", "paraview_filter")
        self.add("Slice", "created_by", "base__create")
        self.add("Slice", "has_property", "SliceType")
        self.add("SliceType", "has_sub_property", "Origin")
        self.add("SliceType", "has_sub_property", "Normal")
        
        # update_sub_property parameters (important for LLM)
        self.add("base__update_sub_property", "has_parameter", "property_name")
        self.add("base__update_sub_property", "has_parameter", "sub_property_name")
        self.add("base__update_sub_property", "has_parameter", "sub_property_value")
        self.add("base__update_sub_property", "has_parameter", "proxy_name")
        
        # Example usage for slice
        self.add("slice_origin", "set_by", "base__update_sub_property")
        self.add("slice_origin", "property_name", "SliceType")
        self.add("slice_origin", "sub_property_name", "Origin")
        self.add("slice_normal", "set_by", "base__update_sub_property")
        self.add("slice_normal", "property_name", "SliceType")
        self.add("slice_normal", "sub_property_name", "Normal")
        
        # Normal vectors for common directions
        self.add("x_normal", "value", "[1, 0, 0]")
        self.add("y_normal", "value", "[0, 1, 0]")
        self.add("z_normal", "value", "[0, 0, 1]")
        
        self.add("StreamTracer", "tool_for", "create_streamlines")
        self.add("Contour", "tool_for", "create_isosurface")
        
        # ===================
        # FIELD ALIASES
        # ===================
        self.add("p", "alias_of", "pressure")
        self.add("P", "alias_of", "pressure")
        self.add("U", "alias_of", "velocity")
        self.add("rho", "alias_of", "density")
        self.add("T", "alias_of", "temperature")
        self.add("Q", "alias_of", "q_criterion")
        
        # ===================
        # BOUNDARY LAYER ANALYSIS
        # ===================
        self.add("boundary_layer", "is_a", "flow_feature")
        self.add("boundary_layer_thickness", "is_a", "scalar_field")
        self.add("displacement_thickness", "is_a", "scalar_field")
        self.add("momentum_thickness", "is_a", "scalar_field")
        self.add("skin_friction", "is_a", "scalar_field")
        
        self.add("boundary_layer", "detected_by", "velocity_profile")
        self.add("boundary_layer_thickness", "computed_from", "velocity_profile")
        self.add("velocity_profile", "computed_from", "velocity")
        self.add("velocity_profile", "requires", "wall_distance")
        
        self.add("skin_friction", "computed_from", "wall_shear_stress")
        self.add("skin_friction", "computed_from", "dynamic_pressure")
        self.add("dynamic_pressure", "computed_from", "velocity")
        self.add("dynamic_pressure", "computed_from", "density")
        
        # ===================
        # TURBULENCE QUANTITIES
        # ===================
        self.add("turbulent_kinetic_energy", "is_a", "scalar_field")
        self.add("turbulent_dissipation", "is_a", "scalar_field")
        self.add("turbulent_viscosity", "is_a", "scalar_field")
        self.add("reynolds_stress", "is_a", "tensor_field")
        
        self.add("k", "alias_of", "turbulent_kinetic_energy")
        self.add("epsilon", "alias_of", "turbulent_dissipation")
        self.add("omega", "alias_of", "specific_dissipation")
        self.add("nut", "alias_of", "turbulent_viscosity")
        self.add("nuTilda", "alias_of", "turbulent_viscosity")
        
        self.add("turbulent_kinetic_energy", "computed_from", "reynolds_stress")
        self.add("turbulent_intensity", "computed_from", "turbulent_kinetic_energy")
        self.add("turbulent_intensity", "computed_from", "velocity_magnitude")
        
        # ===================
        # COMPRESSIBILITY EFFECTS
        # ===================
        self.add("mach_number", "is_a", "scalar_field")
        self.add("total_pressure", "is_a", "scalar_field")
        self.add("total_temperature", "is_a", "scalar_field")
        self.add("entropy", "is_a", "scalar_field")
        
        self.add("mach_number", "computed_from", "velocity_magnitude")
        self.add("mach_number", "computed_from", "speed_of_sound")
        self.add("speed_of_sound", "computed_from", "temperature")
        self.add("speed_of_sound", "computed_from", "gas_constant")
        
        self.add("shock", "is_a", "flow_feature")
        self.add("shock", "detected_by", "pressure_gradient_magnitude")
        self.add("shock", "detected_by", "mach_number_gradient")
        self.add("pressure_gradient_magnitude", "computed_from", "pressure_gradient")
        
        # ===================
        # HEAT TRANSFER
        # ===================
        self.add("heat_flux", "is_a", "scalar_field")
        self.add("nusselt_number", "is_a", "scalar_field")
        self.add("heat_transfer_coefficient", "is_a", "scalar_field")
        
        self.add("heat_flux", "computed_from", "temperature_gradient")
        self.add("heat_flux", "computed_from", "thermal_conductivity")
        self.add("temperature_gradient", "computed_from", "temperature")
        
        # ===================
        # STATISTICAL ANALYSIS
        # ===================
        self.add("mean", "is_a", "statistical_operation")
        self.add("rms", "is_a", "statistical_operation")
        self.add("standard_deviation", "is_a", "statistical_operation")
        self.add("correlation", "is_a", "statistical_operation")
        
        self.add("time_average", "computed_by", "mean")
        self.add("fluctuation", "computed_from", "instantaneous")
        self.add("fluctuation", "computed_from", "time_average")
        
        # ===================
        # ANALYSIS PATTERNS
        # ===================
        self.add("profile_extraction", "requires", "line_probe")
        self.add("surface_integration", "requires", "surface_selection")
        self.add("volume_integration", "requires", "volume_selection")
        
        self.add("convergence_check", "uses", "residuals")
        self.add("convergence_check", "uses", "monitor_points")
        
        # Additional tool mappings
        self.add("Calculator", "tool_for", "field_computation")
        self.add("PlotOverLine", "tool_for", "profile_extraction")
        self.add("IntegrateVariables", "tool_for", "volume_integration")
        self.add("ExtractSurface", "tool_for", "surface_extraction")


def demo():
    """Demonstrate ontology reasoning capabilities."""
    ont = CFDOntology()
    
    print("=" * 60)
    print("CFD ONTOLOGY DEMO")
    print("=" * 60)
    
    # 1. Query examples
    print("\n## Query: What detects a vortex?")
    for t in ont.query(subject="vortex", predicate="detected_by"):
        print(f"  {t}")
    
    print("\n## Query: What is q_criterion computed from?")
    for t in ont.query(subject="q_criterion", predicate="computed_from"):
        print(f"  {t}")
    
    # 2. Inference
    print("\n## Infer: Requirements for q_criterion")
    reqs = ont.infer_requirements("q_criterion")
    print(f"  {reqs}")
    
    print("\n## Infer: Detection chain for vortex")
    chain = ont.infer_detection_chain("vortex")
    print(f"  {chain}")
    
    # 3. Workflow planning
    print("\n## Plan: visualize_vortex with fields {u, v, w, p}")
    plan = ont.plan_workflow("visualize_vortex", {"u", "v", "w", "p"})
    print(f"  Goal: {plan['goal']}")
    print(f"  Reasoning:")
    for r in plan['reasoning']:
        print(f"    - {r}")
    print(f"  Steps:")
    for step in plan['steps']:
        print(f"    - {step['action']}: {step.get('reason', '')}")
    print(f"  Tools: {plan['tools']}")
    
    # 4. Explain
    print("\n## Explain: vortex")
    print(ont.explain("vortex"))
    
    print("\n## Explain: drag")
    print(ont.explain("drag"))
    
    # 5. Generate LLM context
    print("\n" + "=" * 60)
    print("LLM CONTEXT GENERATION")
    print("=" * 60)
    
    context = ont.generate_llm_context("vortex", {"u", "v", "w", "p"})
    print(context)


def demo_reasoning():
    """Show how ontology enables reasoning vs lookup."""
    ont = CFDOntology()
    
    print("=" * 60)
    print("REASONING vs LOOKUP COMPARISON")
    print("=" * 60)
    
    print("\n## OLD WAY (Lookup Table):")
    print("  User: 'show vortices'")
    print("  → Match 'vortex' trigger")
    print("  → Execute hardcoded workflow: [hide_all, create_vortex_isosurface]")
    print("  → No understanding of WHY these steps")
    
    print("\n## NEW WAY (Ontology Reasoning):")
    print("  User: 'show vortices'")
    print("  → Query: (vortex, detected_by, ?)")
    triples = ont.query(subject="vortex", predicate="detected_by")
    for t in triples:
        print(f"     Found: {t}")
    
    print("  → Choose q_criterion (most common)")
    print("  → Query: (q_criterion, computed_from, ?)")
    triples = ont.query(subject="q_criterion", predicate="computed_from")
    for t in triples:
        print(f"     Found: {t}")
    
    print("  → Query: (velocity_gradient, computed_from, ?)")
    triples = ont.query(subject="velocity_gradient", predicate="computed_from")
    for t in triples:
        print(f"     Found: {t}")
    
    print("  → Check: do we have velocity?")
    print("  → Query: (?, component_of, velocity)")
    components = ont.get_components("velocity")
    print(f"     Components: {components}")
    print("  → We have {u, v, w}, can assemble velocity ✓")
    
    print("\n  → REASONED PLAN:")
    print("     1. assemble_vector(u,v,w) → velocity")
    print("     2. compute_gradient(velocity) → velocity_gradient") 
    print("     3. compute_q_criterion(velocity_gradient) → q_criterion")
    print("     4. create_isosurface(q_criterion) → vortex visualization")
    
    print("\n## ADVANTAGE: Can handle novel situations")
    print("  User: 'I only have vorticity, can I see vortices?'")
    print("  → Query: (vortex, detected_by, ?)")
    print("     Found: vorticity_magnitude is an option!")
    print("  → Query: (vorticity_magnitude, computed_from, ?)")
    triples = ont.query(subject="vorticity_magnitude")
    print(f"     {triples}")
    print("  → Can compute from vorticity directly!")
    print("  → ALTERNATE PLAN: compute_magnitude(vorticity) → create_isosurface")


if __name__ == "__main__":
    demo()
    print("\n\n")
    demo_reasoning()
