"""
Planning-enabled CFD Ontology

Extends the triple-based ontology with STRIPS-style planning semantics:
- Preconditions: What must be true before an action
- Effects: What becomes true after an action
- Goals: What we want to achieve

This allows a simple backward-chaining planner to derive workflows
from the ontology rather than hardcoding them.
"""

from dataclasses import dataclass
from typing import Optional
from paraview_llm.ontology_triples import Triple, CFDOntology


@dataclass
class Action:
    """An action that can be taken to transform state."""
    name: str
    tool: str  # MCP tool name
    preconditions: set[str]  # Required state predicates
    effects_add: set[str]  # State predicates added
    effects_remove: set[str] = None  # State predicates removed (optional)
    
    def __post_init__(self):
        if self.effects_remove is None:
            self.effects_remove = set()


class PlanningOntology(CFDOntology):
    """
    CFD Ontology with planning capabilities.
    
    Adds:
    - Actions with preconditions and effects
    - State predicates derived from available data
    - Goal definitions
    - Backward-chaining planner
    """
    
    def __init__(self):
        super().__init__()
        self.actions: dict[str, Action] = {}
        self.goal_definitions: dict[str, set[str]] = {}
        self._load_planning_knowledge()
    
    def _load_planning_knowledge(self):
        """Load action definitions and goal mappings."""
        
        # ===================
        # STATE PREDICATES
        # ===================
        # These describe what's true about the current state
        # Format: (field, satisfies, predicate)
        
        # Velocity components satisfy has_velocity_components
        self.add("u", "satisfies", "has_velocity_components")
        self.add("v", "satisfies", "has_velocity_components")
        self.add("w", "satisfies", "has_velocity_components")
        
        # Assembled velocity satisfies has_velocity
        self.add("velocity", "satisfies", "has_velocity")
        self.add("Velocity", "satisfies", "has_velocity")
        
        # Pressure satisfies has_pressure
        self.add("p", "satisfies", "has_pressure")
        self.add("pressure", "satisfies", "has_pressure")
        self.add("Pressure", "satisfies", "has_pressure")
        
        # Surface data
        self.add("surface_normals", "satisfies", "has_surface")
        
        # ===================
        # ACTIONS
        # ===================
        
        self.register_action(Action(
            name="assemble_velocity",
            tool="ensure_velocity_vector",
            preconditions={"has_velocity_components"},
            effects_add={"has_velocity"}
        ))
        
        self.register_action(Action(
            name="compute_q_criterion",
            tool="create_vortex_isosurface",
            preconditions={"has_velocity"},
            effects_add={"has_vortex_visualization", "has_q_criterion"}
        ))
        
        self.register_action(Action(
            name="compute_helicity",
            tool="create_vortex_isosurface",  # with method=helicity
            preconditions={"has_velocity"},
            effects_add={"has_vortex_visualization", "has_helicity"}
        ))
        
        self.register_action(Action(
            name="compute_forces",
            tool="compute_forces",
            preconditions={"has_pressure", "has_surface"},
            effects_add={"has_force_data", "has_drag", "has_lift"}
        ))
        
        self.register_action(Action(
            name="create_force_chart",
            tool="create_force_distribution_chart",
            preconditions={"has_force_data"},
            effects_add={"has_force_distribution"}
        ))
        
        self.register_action(Action(
            name="detect_wake",
            tool="detect_wake_region",
            preconditions={"has_velocity"},
            effects_add={"has_wake_location"}
        ))
        
        self.register_action(Action(
            name="create_streamlines",
            tool="create_streamlines",
            preconditions={"has_velocity"},
            effects_add={"has_streamline_visualization"}
        ))
        
        # NOTE: create_slice removed - use base tools instead
        # The ontology has concepts for slice positioning (see ontology_triples.py)
        # Workflow: get_geometry_info → base:create("Slice") → update_sub_property for origin/normal
        
        # ===================
        # GOALS
        # ===================
        # Goals are achieved when certain predicates are true
        
        self.define_goal("visualize_vortex", {"has_vortex_visualization"})
        self.define_goal("visualize_wake", {"has_streamline_visualization"})
        self.define_goal("analyze_drag", {"has_force_distribution"})
        self.define_goal("compute_drag", {"has_drag"})
        self.define_goal("show_flow_field", {"has_streamline_visualization"})
    
    def register_action(self, action: Action):
        """Register an action in the ontology."""
        self.actions[action.name] = action
        
        # Also add triples for discoverability
        self.add(action.name, "is_a", "action")
        self.add(action.name, "implemented_by", action.tool)
        for pre in action.preconditions:
            self.add(action.name, "precondition", pre)
        for eff in action.effects_add:
            self.add(action.name, "effect", eff)
    
    def define_goal(self, goal_name: str, required_predicates: set[str]):
        """Define what predicates must be true to achieve a goal."""
        self.goal_definitions[goal_name] = required_predicates
        self.add(goal_name, "is_a", "goal")
        for pred in required_predicates:
            self.add(goal_name, "achieved_by", pred)
    
    def get_current_state(self, available_fields: set[str]) -> set[str]:
        """
        Derive current state predicates from available fields.
        
        Looks up what predicates each field satisfies.
        """
        state = set()
        
        for field in available_fields:
            # Check what this field satisfies
            for triple in self.query(subject=field, predicate="satisfies"):
                state.add(triple.object)
            
            # Also check aliases
            for alias_triple in self.query(subject=field, predicate="alias_of"):
                canonical = alias_triple.object
                for triple in self.query(subject=canonical, predicate="satisfies"):
                    state.add(triple.object)
        
        # Check if we have all velocity components
        has_u = any(f in available_fields for f in ['u', 'U'])
        has_v = any(f in available_fields for f in ['v', 'V'])
        has_w = any(f in available_fields for f in ['w', 'W'])
        if has_u and has_v and has_w:
            state.add("has_velocity_components")
        
        # Check for velocity vector
        if any(f.lower() == 'velocity' for f in available_fields):
            state.add("has_velocity")
        
        # Check for pressure
        if any(f.lower() in ['p', 'pressure'] for f in available_fields):
            state.add("has_pressure")
        
        # Assume surface data exists for body meshes
        # (Could be refined with actual surface detection)
        state.add("has_surface")
        
        return state
    
    def find_applicable_actions(self, state: set[str]) -> list[Action]:
        """Find all actions whose preconditions are satisfied."""
        applicable = []
        for action in self.actions.values():
            if action.preconditions.issubset(state):
                applicable.append(action)
        return applicable
    
    def find_achieving_actions(self, predicate: str) -> list[Action]:
        """Find all actions that can achieve a predicate."""
        achieving = []
        for action in self.actions.values():
            if predicate in action.effects_add:
                achieving.append(action)
        return achieving
    
    def plan(self, goal: str, available_fields: set[str]) -> dict:
        """
        Generate a plan to achieve a goal using backward chaining.
        
        Algorithm:
        1. Get goal predicates
        2. Get current state from available fields
        3. Find unsatisfied goal predicates
        4. For each unsatisfied predicate, find actions that achieve it
        5. Recursively satisfy action preconditions
        6. Return ordered list of actions
        
        Args:
            goal: Goal name (e.g., "visualize_vortex")
            available_fields: Set of available field names
            
        Returns:
            Dict with plan steps, reasoning trace, and feasibility
        """
        # Get goal definition
        if goal not in self.goal_definitions:
            # Try to find goal in triples
            goal_preds = set()
            for t in self.query(subject=goal, predicate="achieved_by"):
                goal_preds.add(t.object)
            if not goal_preds:
                return {
                    "feasible": False,
                    "error": f"Unknown goal: {goal}",
                    "known_goals": list(self.goal_definitions.keys())
                }
        else:
            goal_preds = self.goal_definitions[goal]
        
        # Get current state
        current_state = self.get_current_state(available_fields)
        
        # Track reasoning
        reasoning = []
        reasoning.append(f"Goal: {goal}")
        reasoning.append(f"Required predicates: {goal_preds}")
        reasoning.append(f"Current state: {current_state}")
        
        # Find unsatisfied predicates
        unsatisfied = goal_preds - current_state
        reasoning.append(f"Unsatisfied: {unsatisfied}")
        
        if not unsatisfied:
            return {
                "feasible": True,
                "plan": [],
                "reasoning": reasoning,
                "message": "Goal already satisfied - no actions needed"
            }
        
        # Backward chain to find plan
        plan = []
        state = current_state.copy()
        visited = set()
        
        def satisfy(predicate: str, depth: int = 0) -> bool:
            """Recursively find actions to satisfy a predicate."""
            indent = "  " * depth
            
            if predicate in state:
                reasoning.append(f"{indent}✓ {predicate} already satisfied")
                return True
            
            if predicate in visited:
                reasoning.append(f"{indent}✗ {predicate} - circular dependency")
                return False
            visited.add(predicate)
            
            # Find actions that achieve this predicate
            achieving = self.find_achieving_actions(predicate)
            if not achieving:
                reasoning.append(f"{indent}✗ {predicate} - no action can achieve this")
                return False
            
            reasoning.append(f"{indent}? {predicate} can be achieved by: {[a.name for a in achieving]}")
            
            # Try each achieving action
            for action in achieving:
                reasoning.append(f"{indent}  Trying: {action.name}")
                
                # Check/satisfy preconditions
                all_preconditions_met = True
                for pre in action.preconditions:
                    if not satisfy(pre, depth + 2):
                        all_preconditions_met = False
                        break
                
                if all_preconditions_met:
                    # Add action to plan and update state
                    if action not in plan:
                        plan.append(action)
                        reasoning.append(f"{indent}  → Added {action.name} to plan")
                    state.update(action.effects_add)
                    return True
            
            return False
        
        # Satisfy all goal predicates
        success = True
        for pred in unsatisfied:
            if not satisfy(pred):
                success = False
        
        if not success:
            return {
                "feasible": False,
                "partial_plan": [{"action": a.name, "tool": a.tool} for a in plan],
                "reasoning": reasoning,
                "error": "Could not find complete plan"
            }
        
        return {
            "feasible": True,
            "plan": [{"action": a.name, "tool": a.tool} for a in plan],
            "tools": [a.tool for a in plan],
            "reasoning": reasoning,
            "final_state": list(state)  # Convert to list for JSON serialization
        }
    
    def explain_plan(self, goal: str, available_fields: set[str]) -> str:
        """Generate human-readable explanation of the plan."""
        result = self.plan(goal, available_fields)
        
        lines = [f"## Plan for: {goal}", ""]
        
        if not result["feasible"]:
            lines.append(f"❌ Cannot achieve goal: {result.get('error', 'Unknown reason')}")
            lines.append("")
            lines.append("### Reasoning trace:")
            for r in result.get("reasoning", []):
                lines.append(f"  {r}")
            return "\n".join(lines)
        
        if not result["plan"]:
            lines.append("✓ Goal already satisfied - no actions needed")
            return "\n".join(lines)
        
        lines.append("### Steps:")
        for i, step in enumerate(result["plan"], 1):
            lines.append(f"  {i}. {step['action']} → tool: {step['tool']}")
        
        lines.append("")
        lines.append("### Reasoning trace:")
        for r in result["reasoning"]:
            lines.append(f"  {r}")
        
        return "\n".join(lines)


def demo():
    """Demonstrate planning capabilities."""
    ont = PlanningOntology()
    
    print("=" * 60)
    print("PLANNING ONTOLOGY DEMO")
    print("=" * 60)
    
    # Test 1: Plan for vortex visualization with only u,v,w,p
    print("\n## Test 1: Visualize vortex with u,v,w,p")
    available = {"u", "v", "w", "p"}
    result = ont.plan("visualize_vortex", available)
    print(f"Feasible: {result['feasible']}")
    print(f"Plan: {result.get('plan', [])}")
    print(f"Tools: {result.get('tools', [])}")
    
    # Test 2: With velocity already assembled
    print("\n## Test 2: Visualize vortex with Velocity already present")
    available = {"Velocity", "p"}
    result = ont.plan("visualize_vortex", available)
    print(f"Feasible: {result['feasible']}")
    print(f"Plan: {result.get('plan', [])}")
    
    # Test 3: Analyze drag
    print("\n## Test 3: Analyze drag with u,v,w,p")
    available = {"u", "v", "w", "p"}
    result = ont.plan("analyze_drag", available)
    print(f"Feasible: {result['feasible']}")
    print(f"Plan: {result.get('plan', [])}")
    print(f"Tools: {result.get('tools', [])}")
    
    # Test 4: Full explanation
    print("\n## Test 4: Full explanation")
    print(ont.explain_plan("visualize_vortex", {"u", "v", "w", "p"}))
    
    # Test 5: Unknown goal
    print("\n## Test 5: Unknown goal")
    result = ont.plan("fly_to_moon", {"u", "v", "w"})
    print(f"Feasible: {result['feasible']}")
    print(f"Error: {result.get('error', 'none')}")
    
    # Show registered actions
    print("\n## Registered Actions:")
    for name, action in ont.actions.items():
        print(f"  {name}:")
        print(f"    tool: {action.tool}")
        print(f"    preconditions: {action.preconditions}")
        print(f"    effects: {action.effects_add}")


if __name__ == "__main__":
    demo()
