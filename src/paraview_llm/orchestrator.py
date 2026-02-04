"""
CFD Orchestrator

Builds enriched prompts with domain knowledge from the ontology.
Maps user queries to relevant CFD concepts and visualization tools.
"""

import json
from pathlib import Path


class Orchestrator:
    """
    Orchestrates CFD visualization using ontology-guided prompts.
    
    Enriches user queries with:
    - Relevant CFD concepts and their detection methods
    - Visualization suggestions based on query keywords
    - Workflow patterns for consistent results
    """
    
    def __init__(self, ontology_path: str = None):
        """
        Initialize orchestrator.
        
        Args:
            ontology_path: Path to ontology JSON. If None, uses built-in cfd.json
        """
        if ontology_path is None:
            ontology_dir = Path(__file__).parent / "ontology"
            ontology_path = ontology_dir / "cfd.json"
        
        with open(ontology_path) as f:
            self.ontology = json.load(f)
    
    def build_prompt(self, user_query: str, data_source: str) -> str:
        """
        Build an enriched prompt with CFD context.
        
        Args:
            user_query: Natural language query from user
            data_source: Name of the data source proxy
            
        Returns:
            Enriched prompt with domain knowledge
        """
        # Get relevant concepts
        concepts = self.ontology.get("concepts", {})
        concept_hints = []
        
        # Match query keywords to concepts
        query_lower = user_query.lower()
        for name, info in concepts.items():
            # Build list of matchable terms
            match_terms = info.get("keywords", [])
            match_terms.append(name.replace("_", " "))
            physical = info.get("physical_meaning", "")
            match_terms.extend(physical.lower().replace(",", "").split())
            
            if any(term.lower() in query_lower for term in match_terms):
                detection = info.get("detection", {})
                tool = detection.get("tool", "")
                
                # Build args string from detection fields (excluding 'tool')
                args = []
                if detection.get("field_type"):
                    args.append(f'field="{detection["field_type"]}"')
                if detection.get("method"):
                    args.append(f'method="{detection["method"]}"')
                if detection.get("exclude_boundaries"):
                    args.append("exclude_boundaries=True")
                args.append(f'proxy_name="{data_source}"')
                
                concept_hints.append(
                    f"- {name}: {info.get('definition', '')} "
                    f"→ {tool}({', '.join(args)})"
                )
        
        # Get visualization suggestions
        vis = self.ontology.get("visualizations", {})
        vis_hints = []
        for name, info in vis.items():
            match_terms = info.get("keywords", [])
            match_terms.append(name.replace("_", " "))
            match_terms.extend(info.get("reveals", []))
            match_terms.extend(info.get("best_for", []))
            
            if any(term.lower() in query_lower for term in match_terms):
                hint = f"- {name}: {info.get('description', '')} → use {info.get('tool', 'create')}"
                vis_hints.append(hint)
        
        # Build the prompt
        prompt = f"""You are a CFD post-processing assistant with access to analysis and visualization tools.

DATA SOURCE: {data_source}
IMPORTANT: Always pass proxy_name="{data_source}" to analysis tools for explicit input.

USER REQUEST: {user_query}

"""
        
        if concept_hints:
            prompt += f"""RELEVANT CFD CONCEPTS:
{chr(10).join(concept_hints)}

"""
        
        if vis_hints:
            prompt += f"""VISUALIZATION OPTIONS:
{chr(10).join(vis_hints)}

"""
        
        prompt += f"""WORKFLOW:
1. First, call hide_all() to start with a clean view
2. Call show_data_context(proxy_name="{data_source}", opacity=0.15) for spatial reference
3. Use analysis tools to find the relevant location/feature if needed
4. Create appropriate visualization using the analysis results
5. Call focus_on(proxy_name) to focus camera on the visualization result

Execute the appropriate tools to fulfill the user's request."""
        
        return prompt
