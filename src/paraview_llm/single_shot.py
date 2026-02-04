"""
Single-shot LLM executor.

Sends one request to LLM to generate a complete tool plan, then executes locally.
No round-trips for intermediate results.

Uses Orchestrator to build enriched prompts with domain knowledge.
"""

import json
import os
from openai import OpenAI
from paraview_llm.orchestrator import Orchestrator


class SingleShotExecutor:
    """
    Execute CFD queries with a single LLM call.
    
    1. Orchestrator enriches query with domain knowledge
    2. Send enriched prompt + tool schemas → LLM returns tool sequence
    3. Execute tools locally without further LLM calls
    
    This is faster and cheaper than in-loop execution while being
    equivalent for deterministic queries.
    """
    
    def __init__(self, extended_mcp, data_source: str, model: str = "gpt-4o"):
        """
        Args:
            extended_mcp: ExtendedParaViewMCP instance
            data_source: Name of the data source proxy
            model: OpenAI model to use
        """
        self.mcp = extended_mcp
        self.data_source = data_source
        self.model = model
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.orchestrator = Orchestrator()  # Domain knowledge
        
        # Build tool schemas from MCP
        self.tools = self._build_tool_schemas()
        
    def _build_tool_schemas(self) -> list:
        """Convert MCP tools to OpenAI function calling format."""
        tools = []
        
        # Get tool functions from MCP
        mcp_def = self.mcp.mcp
        for tool_func in mcp_def.get("tools", []):
            # Get function signature info
            import inspect
            sig = inspect.signature(tool_func)
            
            # Build parameter schema
            properties = {}
            required = []
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                    
                # Infer type from annotation or default
                param_type = "string"
                if param.annotation != inspect.Parameter.empty:
                    if param.annotation == float:
                        param_type = "number"
                    elif param.annotation == int:
                        param_type = "integer"
                    elif param.annotation == bool:
                        param_type = "boolean"
                
                properties[name] = {"type": param_type}
                
                # Add description from docstring if available
                if tool_func.__doc__:
                    properties[name]["description"] = f"Parameter for {tool_func.__name__}"
                
                if param.default == inspect.Parameter.empty:
                    required.append(name)
            
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_func.__name__,
                    "description": tool_func.__doc__ or f"Execute {tool_func.__name__}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    }
                }
            })
        
        return tools
    
    def _get_system_prompt(self) -> str:
        """System prompt for single-shot plan generation."""
        return f"""You are a CFD post-processing assistant. Generate a sequence of tool calls to fulfill the user's request.

DATA SOURCE: {self.data_source}
IMPORTANT: Always pass proxy_name="{self.data_source}" to tools that need a data source.

WORKFLOW PATTERN:
1. hide_all() - Start with clean view
2. show_data_context(proxy_name="{self.data_source}", opacity=0.15) - Add spatial reference
3. [Analysis tools] - Find locations/features as needed
4. [Visualization tools] - Create the requested visualization
5. focus_on(proxy_name=<result>) - Focus on the result
6. set_streamwise_view(proxy_name=<result>) - Orient camera (if 3D visualization)

Call ALL necessary tools in sequence. The tools will be executed in order without further input from you."""

    def generate_plan(self, query: str) -> list:
        """
        Generate tool execution plan with single LLM call.
        
        Args:
            query: Natural language query
            
        Returns:
            List of (tool_name, kwargs) tuples
        """
        # Use orchestrator to build enriched prompt with domain knowledge
        enriched_prompt = self.orchestrator.build_prompt(query, self.data_source)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": enriched_prompt}
            ],
            tools=self.tools,
            tool_choice="required",  # Force tool use
        )
        
        # Extract tool calls
        plan = []
        message = response.choices[0].message
        
        if message.tool_calls:
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                plan.append((name, args))
        
        return plan
    
    def execute(self, query: str) -> list:
        """
        Generate plan and execute tools.
        
        Args:
            query: Natural language query
            
        Returns:
            List of (tool_name, kwargs, result) tuples
        """
        # Get plan from LLM (single API call)
        plan = self.generate_plan(query)
        
        # Execute tools locally
        results = []
        last_created = None
        
        for tool_name, kwargs in plan:
            # Substitute placeholders
            resolved_kwargs = {}
            for k, v in kwargs.items():
                if v == "{last_created}" and last_created:
                    resolved_kwargs[k] = last_created
                elif v == "{data_source}":
                    resolved_kwargs[k] = self.data_source
                else:
                    resolved_kwargs[k] = v
            
            # Get tool function
            tool_func = getattr(self.mcp, tool_name, None)
            if tool_func is None:
                # Try base MCP
                tool_func = getattr(self.mcp._base, tool_name, None)
            
            if tool_func is None:
                result = {"error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    result = tool_func(**resolved_kwargs)
                    # Track created proxies
                    if isinstance(result, dict) and "name" in result:
                        last_created = result["name"]
                except Exception as e:
                    result = {"error": str(e)}
            
            results.append((tool_name, resolved_kwargs, result))
        
        return results
