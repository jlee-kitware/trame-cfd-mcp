"""
Test: LLM reasoning vs semantic planner

Compare two approaches:
1. LLM reasons from raw triples to build a plan
2. Semantic planner builds plan, LLM reviews/executes

This helps us understand which approach works better.
"""

import os
import sys
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

from openai import OpenAI
from paraview_llm.ontology_planning import PlanningOntology

# Initialize
client = OpenAI()
ont = PlanningOntology()

def get_ontology_context_for_llm(goal: str, available_fields: set[str]) -> str:
    """Generate rich context for LLM to reason about planning."""
    
    lines = [
        "# CFD Ontology for Planning",
        "",
        "## Available Data",
        f"Fields: {sorted(available_fields)}",
        "",
        "## Actions (tools you can call)",
        "Each action has preconditions (what must be true) and effects (what becomes true):",
        ""
    ]
    
    for name, action in ont.actions.items():
        lines.append(f"### {action.tool}")
        lines.append(f"  - Preconditions: {action.preconditions or 'none'}")
        lines.append(f"  - Effects: {action.effects_add}")
        lines.append("")
    
    lines.extend([
        "## State Inference Rules (IMPORTANT)",
        "Determine current state predicates from available fields:",
        "",
        "- If fields contain ALL of (u, v, w) → has_velocity_components = TRUE",
        "- If fields contain 'Velocity' → has_velocity = TRUE (already assembled!)",
        "- If fields contain 'p' or 'pressure' → has_pressure = TRUE", 
        "- Assume has_surface = TRUE (body mesh present)",
        "",
        "CRITICAL: 'Velocity' means velocity is ALREADY assembled.",
        "         You do NOT need ensure_velocity_vector if Velocity exists.",
        "         Only use ensure_velocity_vector when you have u,v,w but NOT Velocity.",
        "",
        "## Goal Definitions",
    ])
    
    for goal_name, predicates in ont.goal_definitions.items():
        lines.append(f"- {goal_name}: requires {predicates}")
    
    lines.extend([
        "",
        "## Planning Instructions",
        "1. Determine current state from available fields",
        "2. Identify what predicates the goal requires",
        "3. Find actions that achieve missing predicates",
        "4. Check action preconditions, add earlier actions if needed",
        "5. Return ordered list of tools to call",
    ])
    
    return "\n".join(lines)


def test_llm_planning(goal: str, available_fields: set[str]) -> dict:
    """Test LLM's ability to generate a plan from ontology context."""
    
    context = get_ontology_context_for_llm(goal, available_fields)
    
    prompt = f"""Given this ontology and available data, create a plan to achieve the goal.

{context}

## Your Task
Goal: {goal}
Available fields: {sorted(available_fields)}

Think step by step:
1. What is the current state based on available fields?
2. What predicates does the goal require?
3. What actions achieve those predicates?
4. What are each action's preconditions?
5. What is the final ordered plan?

Return your answer as a JSON object:
{{
  "current_state": ["predicate1", "predicate2"],
  "goal_requires": ["predicate"],
  "reasoning": "step by step explanation",
  "plan": [
    {{"tool": "tool_name", "why": "reason"}}
  ]
}}
"""
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    import json
    return json.loads(response.choices[0].message.content)


def test_semantic_planner(goal: str, available_fields: set[str]) -> dict:
    """Test semantic planner's plan generation."""
    return ont.plan(goal, available_fields)


def compare_approaches(goal: str, available_fields: set[str]):
    """Compare LLM vs semantic planner."""
    
    print(f"\n{'='*60}")
    print(f"GOAL: {goal}")
    print(f"FIELDS: {sorted(available_fields)}")
    print("="*60)
    
    # Semantic planner
    print("\n## Semantic Planner Result:")
    planner_result = test_semantic_planner(goal, available_fields)
    if planner_result["feasible"]:
        print(f"  Plan: {[s['tool'] for s in planner_result['plan']]}")
    else:
        print(f"  Failed: {planner_result.get('error')}")
    
    # LLM reasoning
    print("\n## LLM Reasoning Result:")
    llm_result = test_llm_planning(goal, available_fields)
    print(f"  Current state: {llm_result.get('current_state', [])}")
    print(f"  Goal requires: {llm_result.get('goal_requires', [])}")
    print(f"  Plan: {[s['tool'] for s in llm_result.get('plan', [])]}")
    print(f"  Reasoning: {llm_result.get('reasoning', '')[:200]}...")
    
    # Compare
    planner_tools = [s['tool'] for s in planner_result.get('plan', [])] if planner_result["feasible"] else []
    llm_tools = [s['tool'] for s in llm_result.get('plan', [])]
    
    print("\n## Comparison:")
    print(f"  Planner: {planner_tools}")
    print(f"  LLM:     {llm_tools}")
    print(f"  Match:   {planner_tools == llm_tools}")
    
    return {
        "goal": goal,
        "planner": planner_tools,
        "llm": llm_tools,
        "match": planner_tools == llm_tools
    }


if __name__ == "__main__":
    results = []
    
    # Test cases
    test_cases = [
        ("visualize_vortex", {"u", "v", "w", "p"}),
        ("visualize_vortex", {"Velocity", "p"}),
        ("analyze_drag", {"u", "v", "w", "p"}),
        ("visualize_wake", {"u", "v", "w", "p"}),
        ("compute_drag", {"p", "Velocity"}),
    ]
    
    for goal, fields in test_cases:
        result = compare_approaches(goal, fields)
        results.append(result)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    matches = sum(1 for r in results if r["match"])
    print(f"Matches: {matches}/{len(results)}")
    for r in results:
        status = "✓" if r["match"] else "✗"
        print(f"  {status} {r['goal']}: planner={r['planner']} llm={r['llm']}")
