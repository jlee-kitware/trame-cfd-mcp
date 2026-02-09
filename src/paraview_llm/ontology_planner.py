"""
Ontology-constrained workflow planner.

The LLM doesn't plan freely - it picks from options the ontology says are valid.
This prevents hallucination while allowing flexible reasoning.
"""

from typing import Optional
from .ontology_triples import CFDOntology


class OntologyPlanner:
    """
    Plans workflows by constraining LLM choices to ontology-valid options.
    
    Flow:
    1. User goal → query ontology for valid approaches
    2. LLM picks from constrained options
    3. Ontology provides steps for chosen approach
    4. Execute steps
    """
    
    def __init__(self, ontology: CFDOntology = None):
        self.ontology = ontology or CFDOntology()
        
        # Map goals to ontology queries
        self.goal_patterns = {
            "vortex": self._plan_vortex,
            "vortices": self._plan_vortex,
            "helical": self._plan_vortex,
            "swirl": self._plan_vortex,
            "rotation": self._plan_vortex,
            "wake": self._plan_wake,
            "separation": self._plan_separation,
        }
    
    def get_valid_approaches(self, goal: str) -> dict:
        """
        Query ontology for valid approaches to achieve a goal.
        
        Returns dict with:
        - approaches: list of valid methods
        - descriptions: what each method does
        - requirements: what each method needs
        """
        goal_lower = goal.lower()
        
        # Find matching goal pattern
        for pattern, planner in self.goal_patterns.items():
            if pattern in goal_lower:
                return planner()
        
        return {"error": f"Unknown goal: {goal}", "approaches": []}
    
    def _plan_vortex(self) -> dict:
        """Get valid approaches for vortex visualization."""
        # Query ontology: what detects vortex?
        detectors = self.ontology.get_objects("vortex", self.ontology.DETECTED_BY)
        
        approaches = []
        for detector in detectors:
            # Get requirements for this detector
            reqs = self.ontology.infer_requirements(detector)
            
            # Get what tool implements this
            tools = self.ontology.query(subject=detector, predicate="enables")
            tool_name = tools[0].object if tools else None
            
            approaches.append({
                "method": detector,
                "description": self._get_description(detector),
                "requires": list(reqs),
                "tool": tool_name,
            })
        
        return {
            "goal": "visualize_vortex",
            "approaches": approaches,
            "prompt_for_llm": self._format_choices_prompt(approaches),
        }
    
    def _plan_wake(self) -> dict:
        """Get valid approaches for wake visualization."""
        return {
            "goal": "visualize_wake",
            "approaches": [
                {
                    "method": "velocity_deficit",
                    "description": "Show regions where velocity is lower than freestream",
                    "requires": ["velocity"],
                    "steps": ["detect_wake_region", "create_slice", "create_streamlines"],
                },
                {
                    "method": "streamlines",
                    "description": "Show flow paths in wake region",
                    "requires": ["velocity"],
                    "steps": ["detect_wake_region", "create_streamlines"],
                },
            ],
            "prompt_for_llm": "Choose wake visualization method:\n1. velocity_deficit\n2. streamlines",
        }
    
    def _plan_separation(self) -> dict:
        """Get valid approaches for flow separation detection."""
        return {
            "goal": "detect_separation",
            "approaches": [
                {
                    "method": "wall_shear_stress",
                    "description": "Find where wall shear stress changes sign",
                    "requires": ["velocity_gradient", "surface_normals"],
                },
                {
                    "method": "reversed_flow",
                    "description": "Find regions where streamwise velocity < 0",
                    "requires": ["velocity"],
                },
            ],
            "prompt_for_llm": "Choose separation detection method:\n1. wall_shear_stress\n2. reversed_flow",
        }
    
    def _get_description(self, method: str) -> str:
        """Get human-readable description of a method."""
        descriptions = {
            "q_criterion": "Identify vortices using second invariant of velocity gradient (rotation vs strain)",
            "lambda2": "Identify vortex cores using pressure minimum criterion",
            "vorticity_magnitude": "Show regions of high rotation (includes shear layers)",
            "helicity": "Show helical/corkscrew vortex structures",
            "swirling_strength": "Identify local swirling motion",
        }
        return descriptions.get(method, f"Detect using {method}")
    
    def _format_choices_prompt(self, approaches: list) -> str:
        """Format approaches as a prompt for LLM to choose from."""
        lines = ["Choose the best method for this visualization:\n"]
        for i, a in enumerate(approaches, 1):
            lines.append(f"{i}. {a['method']}: {a['description']}")
            lines.append(f"   Requires: {', '.join(a['requires'])}")
        lines.append("\nRespond with just the method name.")
        return "\n".join(lines)
    
    def get_steps_for_approach(self, goal: str, method: str) -> list[dict]:
        """
        Get execution steps for a chosen approach.
        
        Returns list of steps with tool calls and parameters.
        """
        if "vortex" in goal.lower():
            return self._get_vortex_steps(method)
        elif "wake" in goal.lower():
            return self._get_wake_steps(method)
        
        return []
    
    def _get_vortex_steps(self, method: str) -> list[dict]:
        """Get steps to visualize vortices with chosen method."""
        # All vortex methods need velocity
        steps = [
            {"tool": "hide_all", "params": {}},
            {"tool": "show_data_context", "params": {"opacity": 0.15}},
            {"tool": "ensure_velocity_vector", "params": {}},
        ]
        
        # Method-specific isosurface
        method_map = {
            "q_criterion": "q_criterion",
            "lambda2": "lambda2",
            "vorticity_magnitude": "vorticity",
            "helicity": "helicity",
            "swirling_strength": "swirling_strength",
        }
        
        iso_method = method_map.get(method, "q_criterion")
        steps.append({
            "tool": "create_vortex_isosurface",
            "params": {"method": iso_method}
        })
        
        steps.append({"tool": "focus_on_last", "params": {}})
        
        return steps
    
    def _get_wake_steps(self, method: str) -> list[dict]:
        """Get steps to visualize wake with chosen method."""
        steps = [
            {"tool": "hide_all", "params": {}},
            {"tool": "show_data_context", "params": {"opacity": 0.15}},
            {"tool": "ensure_velocity_vector", "params": {}},
        ]
        
        if method == "velocity_deficit":
            # Add slice showing velocity
            steps.extend([
                {"tool": "get_slice_parameters", "params": {"normal": [0, 0, 1], "position": "center"}},
                {"tool": "base_create", "params": {"filter_type": "Slice"}},
                # ... configure slice with step references
            ])
        
        steps.extend([
            {"tool": "detect_wake_region", "params": {}},
            {"tool": "create_streamlines", "params": {}},
            {"tool": "focus_on_context", "params": {}},
        ])
        
        return steps


def test_planner():
    """Test the ontology planner."""
    planner = OntologyPlanner()
    
    print("=" * 60)
    print("Vortex visualization options:")
    print("=" * 60)
    result = planner.get_valid_approaches("show vortices")
    for a in result["approaches"]:
        print(f"\n{a['method']}:")
        print(f"  {a['description']}")
        print(f"  Requires: {a['requires']}")
    
    print("\n" + "=" * 60)
    print("LLM prompt would be:")
    print("=" * 60)
    print(result["prompt_for_llm"])
    
    print("\n" + "=" * 60)
    print("Steps for q_criterion:")
    print("=" * 60)
    steps = planner.get_steps_for_approach("vortex", "q_criterion")
    for s in steps:
        print(f"  {s['tool']}: {s['params']}")


def constrained_query(user_query: str, llm_client, model: str = "gpt-4o-mini") -> dict:
    """
    Execute a query using ontology-constrained planning.
    
    1. Extract goal from user query
    2. Get valid approaches from ontology
    3. Ask LLM to pick from constrained options
    4. Return steps for chosen approach
    """
    planner = OntologyPlanner()
    
    # Get constrained options
    options = planner.get_valid_approaches(user_query)
    
    if "error" in options:
        return {"error": options["error"]}
    
    if not options["approaches"]:
        return {"error": "No valid approaches found"}
    
    # Ask LLM to choose (constrained choice)
    system_prompt = """You are helping choose a visualization method.
Pick the best method from the options given. Respond with ONLY the method name, nothing else."""
    
    user_prompt = f"""User wants: {user_query}

{options['prompt_for_llm']}"""
    
    response = llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=50,
    )
    
    chosen_method = response.choices[0].message.content.strip().lower()
    
    # Validate choice against ontology
    valid_methods = [a["method"] for a in options["approaches"]]
    if chosen_method not in valid_methods:
        # Try to fuzzy match
        for vm in valid_methods:
            if vm in chosen_method or chosen_method in vm:
                chosen_method = vm
                break
        else:
            return {
                "error": f"LLM chose invalid method: {chosen_method}",
                "valid_options": valid_methods,
            }
    
    # Get steps for chosen method
    steps = planner.get_steps_for_approach(options["goal"], chosen_method)
    
    return {
        "goal": options["goal"],
        "chosen_method": chosen_method,
        "steps": steps,
        "reasoning": f"Ontology provided {len(options['approaches'])} valid methods, LLM chose {chosen_method}",
    }


if __name__ == "__main__":
    test_planner()
