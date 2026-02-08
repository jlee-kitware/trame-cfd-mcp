"""
Example: Basic usage of the ParaView LLM intent-based architecture

Shows how the intent-based architecture works:
1. User query → LLM classifies intent
2. Workflow lookup from predefined WORKFLOWS
3. Deterministic tool execution

Run this example:
    python examples/basic_usage.py
"""

from paraview_llm import WORKFLOWS, IntentType


def main():
    print("=" * 60)
    print("ParaView LLM - Safe Tiered Architecture")
    print("=" * 60)
    
    # Show available workflows
    print(f"\nAvailable workflows ({len(WORKFLOWS)}):")
    for intent_type, info in WORKFLOWS.items():
        print(f"  - {intent_type.value}: {info['description']}")
    
    print("\n" + "=" * 60)
    print("Example workflow: visualize_vortices")
    print("=" * 60)
    
    # Show a workflow's tool sequence
    workflow = WORKFLOWS[IntentType.VISUALIZE_VORTICES]
    print(f"\nName: {workflow['name']}")
    print(f"Description: {workflow['description']}")
    print(f"\nSteps:")
    for i, (tool, args) in enumerate(workflow["steps"], 1):
        args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
        print(f"  {i}. {tool}({args_str})")
    
    print("\n" + "=" * 60)
    print("How it works")
    print("=" * 60)
    print("""
1. User: "show me the vortices using Q-criterion"
   
2. LLM classifies intent (single call, ~150 tokens):
   {"type": "visualize_vortices"}
   
3. Lookup WORKFLOWS[IntentType.VISUALIZE_VORTICES] → predefined steps
   
4. Execute steps deterministically (no LLM):
   - ensure_velocity_vector()
   - hide_all()
   - show_data_context(proxy_name="...", opacity=0.15)
   - create_vortex_isosurface(method="q_criterion", ...)
   - focus_on(proxy_name="{last_created}")
   - set_streamwise_view(proxy_name="{last_created}")

5. (Optional) LLM summarizes results (~250 tokens)

KEY PRINCIPLE: LLM only classifies intent - never makes execution decisions.
  - ~400 tokens per query (vs 1M tokens with tool-loop)
  - Deterministic, reproducible results
  - No retry loops or state confusion
""")


if __name__ == "__main__":
    main()
