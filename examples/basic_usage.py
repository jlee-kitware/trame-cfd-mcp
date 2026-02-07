"""
Example: Basic usage of the ParaView LLM intent-based architecture

Shows how the intent-based executor works:
1. User query → LLM classifies intent
2. Workflow lookup from predefined WORKFLOWS
3. Deterministic tool execution

Run this example:
    python examples/basic_usage.py
"""

from paraview_llm import WORKFLOWS


def main():
    print("=" * 60)
    print("ParaView LLM - Intent-Based Architecture")
    print("=" * 60)
    
    # Show available workflows (the ontology)
    print(f"\nAvailable workflows ({len(WORKFLOWS)}):")
    for name, info in WORKFLOWS.items():
        print(f"  - {name}: {info['description']}")
    
    print("\n" + "=" * 60)
    print("Example workflow: vortices_q")
    print("=" * 60)
    
    # Show a workflow's tool sequence
    workflow = WORKFLOWS["vortices_q"]
    print(f"\nDescription: {workflow['description']}")
    print(f"\nTool sequence:")
    for i, (tool, args) in enumerate(workflow["sequence"], 1):
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        print(f"  {i}. {tool}({args_str})")
    
    print("\n" + "=" * 60)
    print("How it works")
    print("=" * 60)
    print("""
1. User: "show me the vortices using Q-criterion"
   
2. LLM classifies intent:
   {"workflow": "vortices_q"}
   
3. Lookup WORKFLOWS["vortices_q"] → predefined tool sequence
   
4. Execute tools deterministically:
   - hide_all()
   - show_data_context(proxy_name="...", opacity=0.15)
   - create_vortex_isosurface(method="q_criterion", proxy_name="...")
   - focus_on(proxy_name="{last_created}")
   - set_streamwise_view(proxy_name="{last_created}")

The LLM's only job is to classify intent into one of the
predefined workflows. All tool sequencing is deterministic.
""")


if __name__ == "__main__":
    main()
