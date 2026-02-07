"""
CFD Assistant - Agent-based architecture with persistent context.

Supports both OpenAI and Claude as backends.
Uses triple-based ontology for semantic reasoning.
Maintains conversation history for multi-turn interactions.
"""

import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path

from paraview_llm.ontology_planning import PlanningOntology


def _load_dotenv():
    """Load .env file if present."""
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_CFD_SYSTEM_PROMPT = """You are a CFD (Computational Fluid Dynamics) visualization assistant.
You help users analyze and visualize simulation results using ParaView.

## Tool Categories

1. **Reasoning tools (reasoning__*)**: Query the CFD ontology to understand domain relationships
   - ontology_query: Find relationships (e.g., "What detects vortices?")
   - ontology_requirements: Find what's needed for a goal
   - ontology_can_achieve: Check if goal is feasible with available data
   - ontology_explain: Get full explanation of a concept

2. **Extended tools (extended__*)**: High-level CFD operations — ALWAYS prefer these
   - characterize_dataset: Analyze what fields are available
   - create_vortex_isosurface: Visualize vortical structures (Q-criterion contour)
   - create_streamlines: Seed and display flow streamlines (auto-sizes to wake/body)
   - compute_forces: Calculate drag/lift
   - create_force_distribution_chart: Show force distribution
   - show_data_context: Show body surface as semi-transparent context layer
   - hide_all: Hide all pipeline objects
   - focus_on: Frame camera on a named filter (use the name returned by create_* tools)
   - get_geometry_info: Get bounds, center, extents for positioning
   - find_by_query: Find centroid of points matching expression (for positioning slices, etc.)
   - detect_wake_region: Find wake centroid (for downstream slice positioning)

3. **Base tools (base__*)**: Low-level ParaView operations (use only when extended tools don't cover your need)

## Slices: Use base tools with positioning from extended tools

For slices, use reasoning + base tools:
1. Get position: extended__get_geometry_info() for center, or find_by_query()/detect_wake_region() for features
2. Create: base__create("Slice")
3. Configure: base__update_sub_property for SliceType.Origin and SliceType.Normal
4. Color: base__update_color

Example slice at body center:
  info = get_geometry_info() → center = info["center"]
  base__create("Slice") → "Slice1"
  base__update_sub_property("Slice1", "SliceType", "Origin", center)
  base__update_sub_property("Slice1", "SliceType", "Normal", [1, 0, 0])
  base__update_color("Slice1", "pressure")

## Streamlines and Vortices: Use extended tools

ALWAYS use extended__create_streamlines instead of building StreamTracer manually.
ALWAYS use extended__create_vortex_isosurface for vortex visualization.
These extended tools handle all property setup, coloring, and naming correctly.

## Visualization Workflow

For any visualization request:
1. The body surface context is already shown (semi-transparent gray).
2. Call the appropriate extended__create_* tool.
3. Call extended__focus_on with the name returned by the create tool.
4. The result is: body context + colored feature + framed camera.

## Reasoning Process

Before taking action, use the ontology to reason about what's needed:
1. Use ontology_query or ontology_explain to understand the domain
2. Use ontology_requirements to find dependencies
3. Use ontology_can_achieve to verify feasibility
4. Then execute the appropriate extended tools
"""


class CFDAssistant(ABC):
    """Abstract base for CFD assistants."""
    
    # Pricing per 1M tokens (as of Feb 2025)
    PRICING = {
        # OpenAI
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        # Anthropic
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    }
    
    def __init__(self, base_mcp, extended_mcp, data_source: str = None):
        self.base_mcp = base_mcp
        self.extended_mcp = extended_mcp
        self.data_source = data_source  # Name of the data source proxy
        self.history = []
        self.model = None  # Set by subclass
        
        # Initialize triple-based ontology with planning capabilities
        self.ontology = PlanningOntology()
        
        # Track available fields (updated by characterize_dataset)
        self._available_fields = set()
        
        # Usage tracking
        self._usage = {
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    
    @property
    def usage(self) -> dict:
        """Get usage statistics including estimated cost."""
        pricing = self.PRICING.get(self.model, {"input": 0, "output": 0})
        
        # Cache reads are 90% cheaper
        regular_input = self._usage["input_tokens"] - self._usage.get("cache_read_tokens", 0)
        cached_input = self._usage.get("cache_read_tokens", 0)
        
        input_cost = (regular_input / 1_000_000) * pricing["input"]
        cached_cost = (cached_input / 1_000_000) * pricing["input"] * 0.1  # 90% discount
        output_cost = (self._usage["output_tokens"] / 1_000_000) * pricing["output"]
        
        result = {
            "model": self.model,
            "requests": self._usage["requests"],
            "input_tokens": self._usage["input_tokens"],
            "output_tokens": self._usage["output_tokens"],
            "total_tokens": self._usage["input_tokens"] + self._usage["output_tokens"],
            "estimated_cost_usd": input_cost + cached_cost + output_cost,
        }
        
        # Add cache stats if available
        if "cache_read_tokens" in self._usage:
            result["cache_read_tokens"] = self._usage["cache_read_tokens"]
            result["cache_creation_tokens"] = self._usage.get("cache_creation_tokens", 0)
        
        return result
    
    # ===================
    # Ontology Query Tools (exposed to LLM)
    # ===================
    
    def _normalize_ontology_term(self, term: str) -> str:
        """Normalize natural language to ontology key format."""
        if term is None:
            return None
        # Convert to lowercase and replace spaces with underscores
        normalized = term.lower().strip().replace(" ", "_").replace("-", "_")
        return normalized
    
    def ontology_query(self, subject: str = None, predicate: str = None, obj: str = None) -> dict:
        """
        Query the CFD ontology for semantic relationships.
        
        Use this to understand CFD domain knowledge before planning actions.
        
        Patterns:
        - ontology_query(subject="vortex") - What do we know about vortices?
        - ontology_query(predicate="detected_by") - What detection methods exist?
        - ontology_query(obj="velocity") - What depends on velocity?
        
        Args:
            subject: Entity to query about (e.g., "vortex", "drag", "mach_number")
            predicate: Relationship type (e.g., "detected_by", "computed_from", "requires")
            obj: Target entity (e.g., "velocity", "pressure")
            
        Returns:
            Dict with matching triples and their meanings
        """
        # Normalize inputs
        subject = self._normalize_ontology_term(subject)
        predicate = self._normalize_ontology_term(predicate)
        obj = self._normalize_ontology_term(obj)
        
        triples = self.ontology.query(subject=subject, predicate=predicate, obj=obj)
        return {
            "query": {"subject": subject, "predicate": predicate, "object": obj},
            "results": [{"subject": t.subject, "predicate": t.predicate, "object": t.object} for t in triples],
            "count": len(triples)
        }
    
    def ontology_requirements(self, goal: str) -> dict:
        """
        Find all requirements needed to achieve a goal.
        
        Walks backward through 'computed_from' and 'requires' relationships
        to find everything needed.
        
        Args:
            goal: What you want to achieve (e.g., "q_criterion", "drag", "mach_number")
            
        Returns:
            Dict with required fields and detection chain
        """
        goal = self._normalize_ontology_term(goal)
        requirements = self.ontology.infer_requirements(goal)
        detection_chain = self.ontology.infer_detection_chain(goal)
        
        return {
            "goal": goal,
            "requirements": list(requirements),
            "detection_chain": detection_chain,
            "explanation": f"To achieve '{goal}', you need: {', '.join(requirements) or 'nothing additional'}"
        }
    
    def ontology_can_achieve(self, goal: str, available_fields: list = None) -> dict:
        """
        Check if a goal is achievable with available data.
        
        Args:
            goal: What you want to achieve (e.g., "visualize_vortex", "mach_number")
            available_fields: List of available field names. If None, uses cached fields.
            
        Returns:
            Dict with feasibility analysis and suggested plan
        """
        goal = self._normalize_ontology_term(goal)
        
        if available_fields is None:
            available_fields = list(self._available_fields)
        
        fields_set = set(available_fields)
        
        # Check velocity assembly
        components = self.ontology.get_components("velocity")
        can_assemble_velocity = all(c in fields_set for c in components) if components else False
        if can_assemble_velocity:
            fields_set.add("velocity")
        
        # Get requirements
        requirements = self.ontology.infer_requirements(goal)
        
        # Check what's missing
        missing = requirements - fields_set
        
        # Can we compute the missing fields?
        computable = set()
        for field in missing:
            sources = self.ontology.get_objects(field, "computed_from")
            if sources and all(s in fields_set or s in computable for s in sources):
                computable.add(field)
        
        truly_missing = missing - computable
        
        return {
            "goal": goal,
            "available": list(fields_set),
            "required": list(requirements),
            "can_compute": list(computable),
            "missing": list(truly_missing),
            "feasible": len(truly_missing) == 0,
            "explanation": (
                f"Goal '{goal}' is {'achievable' if len(truly_missing) == 0 else 'NOT achievable'}. "
                f"Required: {requirements}. Missing: {truly_missing or 'none'}."
            )
        }
    
    def ontology_explain(self, entity: str) -> dict:
        """
        Get a full explanation of an entity from the ontology.
        
        Args:
            entity: The thing to explain (e.g., "vortex", "drag", "mach_number")
            
        Returns:
            Dict with all relationships involving this entity
        """
        entity = self._normalize_ontology_term(entity)
        
        # Get all triples where entity is subject
        as_subject = self.ontology.query(subject=entity)
        # Get all triples where entity is object
        as_object = self.ontology.query(obj=entity)
        
        return {
            "entity": entity,
            "properties": [{"predicate": t.predicate, "value": t.object} for t in as_subject],
            "referenced_by": [{"subject": t.subject, "predicate": t.predicate} for t in as_object],
            "visualization_options": self.ontology.find_visualization(entity),
            "tools": self.ontology.find_tool(entity) or self.ontology.find_tool(f"compute_{entity}")
        }
    
    def ontology_plan(self, goal: str, available_fields: list = None) -> dict:
        """
        Generate a plan to achieve a goal using semantic reasoning.
        
        Uses backward-chaining through preconditions and effects to find
        the sequence of tools needed. Returns the plan for your review
        before execution.
        
        Args:
            goal: What you want to achieve. Known goals:
                  - "visualize_vortex" - Show vortical structures
                  - "visualize_wake" - Show wake flow with streamlines
                  - "analyze_drag" - Compute and chart drag distribution
                  - "compute_drag" - Just compute drag forces
                  - "show_flow_field" - Visualize overall flow
            available_fields: Fields in the data. If None, uses cached fields.
            
        Returns:
            Dict with:
            - feasible: bool - Can this goal be achieved?
            - plan: list - Ordered tool calls [{"action": ..., "tool": ...}]
            - tools: list - Just the tool names in order
            - reasoning: list - Step-by-step explanation
            
        Example:
            ontology_plan("visualize_vortex", ["u", "v", "w", "p"])
            → plan: [ensure_velocity_vector, create_vortex_isosurface]
        """
        goal = self._normalize_ontology_term(goal)
        
        if available_fields is None:
            available_fields = list(self._available_fields)
        
        return self.ontology.plan(goal, set(available_fields))
    
    def execute_plan(self, plan: list) -> dict:
        """
        Execute a plan (list of tool calls) in sequence.
        
        Takes a plan from ontology_plan() and executes each tool.
        Stops on first error and returns partial results.
        
        Args:
            plan: List of {"tool": "tool_name", ...} dicts from ontology_plan()
            
        Returns:
            Dict with:
            - status: "completed" or "failed"
            - results: List of {step, result} for each executed tool
            - error: Error message if failed
            
        Example:
            plan = ontology_plan("visualize_vortex", fields)["plan"]
            execute_plan(plan)  # Runs ensure_velocity_vector, then create_vortex_isosurface
        """
        results = []
        
        for step in plan:
            tool_name = step.get("tool")
            if not tool_name:
                continue
            
            # Execute the tool
            result = self._execute_tool(f"extended__{tool_name}", {})
            results.append({
                "step": step,
                "tool": tool_name,
                "result": result
            })
            
            # Stop on error
            if isinstance(result, dict) and "error" in result:
                return {
                    "status": "failed",
                    "completed_steps": len(results) - 1,
                    "results": results,
                    "error": result["error"]
                }
        
        return {
            "status": "completed",
            "completed_steps": len(results),
            "results": results
        }
    
    def _get_ontology_tools(self) -> list:
        """Get ontology query and planning tools."""
        tools = []
        tool_names = [
            "ontology_query", 
            "ontology_requirements", 
            "ontology_can_achieve", 
            "ontology_explain",
            "ontology_plan",
            "execute_plan"
        ]
        for name in tool_names:
            func = getattr(self, name)
            tools.append(self._func_to_schema(name, func, "reasoning"))
        return tools
    
    def _get_all_tools(self) -> list:
        """Get tools from MCPs and ontology reasoning."""
        tools = []
        
        # Ontology reasoning tools (query domain knowledge)
        tools.extend(self._get_ontology_tools())
        
        # Extended MCP tools (CFD-specific)
        for name in dir(self.extended_mcp):
            if not name.startswith("_"):
                func = getattr(self.extended_mcp, name)
                if callable(func) and hasattr(func, "__doc__") and func.__doc__:
                    tools.append(self._func_to_schema(name, func, "extended"))
        
        # Base MCP tools
        if hasattr(self.base_mcp, "mcp"):
            for func in self.base_mcp.mcp.get("tools", []):
                tools.append(self._func_to_schema(func.__name__, func, "base"))
        
        return tools
    
    def _func_to_schema(self, name: str, func, source: str) -> dict:
        """Convert a Python function to OpenAI/Claude function schema."""
        import inspect
        import typing
        sig = inspect.signature(func)
        
        properties = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            
            # Infer type from annotation or default
            param_type = "string"
            param_schema = {"type": "string"}
            
            if param.annotation != inspect.Parameter.empty:
                annotation = param.annotation
                
                # Handle Optional types
                origin = getattr(annotation, "__origin__", None)
                if origin is type(None):
                    continue
                
                # Get the actual type for Optional/Union
                args = getattr(annotation, "__args__", ())
                if origin in (type(None), typing.Union) and args:
                    # For Optional[X], get X
                    annotation = args[0] if args[0] is not type(None) else (args[1] if len(args) > 1 else str)
                    origin = getattr(annotation, "__origin__", None)
                
                if annotation == int:
                    param_schema = {"type": "integer"}
                elif annotation == float:
                    param_schema = {"type": "number"}
                elif annotation == bool:
                    param_schema = {"type": "boolean"}
                elif annotation == list or origin == list:
                    # Array type - need items schema
                    item_type = "string"
                    if args:
                        item_arg = args[0]
                        if item_arg == int:
                            item_type = "integer"
                        elif item_arg == float:
                            item_type = "number"
                        elif item_arg == bool:
                            item_type = "boolean"
                    param_schema = {"type": "array", "items": {"type": item_type}}
            
            properties[param_name] = param_schema
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        return {
            "type": "function",
            "function": {
                "name": f"{source}__{name}",
                "description": func.__doc__ or f"Execute {name}",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
    
    def _execute_tool(self, tool_name: str, arguments: str) -> dict:
        """Execute a tool call from the assistant."""
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        
        # Parse source__name format
        if "__" in tool_name:
            source, name = tool_name.split("__", 1)
        else:
            source, name = "extended", tool_name
        
        # Handle reasoning (ontology) tools
        if source == "reasoning":
            func = getattr(self, name, None)
            if func is None:
                return {"error": f"Unknown reasoning tool: {name}"}
            try:
                result = func(**args)
                return result if isinstance(result, dict) else {"result": result}
            except Exception as e:
                return {"error": str(e)}
        
        # Get the right MCP
        mcp = self.extended_mcp if source == "extended" else self.base_mcp
        
        # Execute
        func = getattr(mcp, name, None)
        if func is None:
            return {"error": f"Unknown tool: {tool_name}"}
        
        try:
            result = func(**args)
            
            # Track available fields from characterize_dataset
            if name == "characterize_dataset" and isinstance(result, dict):
                if "available_fields" in result:
                    self._available_fields = set(result["available_fields"])
                if "resolved_fields" in result:
                    self._available_fields.update(result["resolved_fields"].values())
            
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            return {"error": str(e)}
    
    def reset(self):
        """Reset conversation history."""
        self.history = []
    
    @abstractmethod
    def execute(self, query: str) -> dict:
        """Execute a query and return results."""
        pass
    
    @abstractmethod
    def get_history(self) -> list:
        """Get conversation history."""
        pass


class OpenAICFDAssistant(CFDAssistant):
    """OpenAI Assistants API implementation."""
    
    def __init__(self, base_mcp, extended_mcp, model: str = None, data_source: str = None):
        super().__init__(base_mcp, extended_mcp, data_source)
        _load_dotenv()
        
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o")
        
        # Build tools
        self.tools = self._get_all_tools()
        
        # Create assistant
        instructions = self._build_instructions()
        self.assistant = self.client.beta.assistants.create(
            name="CFD Assistant",
            instructions=instructions,
            tools=self.tools,
            model=self.model,
        )
        
        # Create thread
        self.thread = self.client.beta.threads.create()
    
    def _build_instructions(self) -> str:
        """Build assistant instructions with ontology reasoning."""
        base = _CFD_SYSTEM_PROMPT
        if self.data_source:
            base += f"\n\nThe current data source is: {self.data_source}\nUse this as proxy_name when calling tools.\n"
        
        return base
    
    def execute(self, query: str) -> dict:
        """Execute a query using the assistant."""
        # Add message to thread
        self.client.beta.threads.messages.create(
            thread_id=self.thread.id,
            role="user",
            content=query,
        )
        
        # Run assistant
        run = self.client.beta.threads.runs.create(
            thread_id=self.thread.id,
            assistant_id=self.assistant.id,
        )
        
        # Poll and handle tool calls
        tool_results = []
        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(0.5)
            
            if run.status == "requires_action":
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                outputs = []
                
                for call in tool_calls:
                    result = self._execute_tool(call.function.name, call.function.arguments)
                    tool_results.append({
                        "tool": call.function.name,
                        "args": json.loads(call.function.arguments),
                        "result": result,
                    })
                    outputs.append({
                        "tool_call_id": call.id,
                        "output": json.dumps(result),
                    })
                
                run = self.client.beta.threads.runs.submit_tool_outputs(
                    thread_id=self.thread.id,
                    run_id=run.id,
                    tool_outputs=outputs,
                )
            else:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread.id,
                    run_id=run.id,
                )
        
        # Track usage
        if run.usage:
            self._usage["requests"] += 1
            self._usage["input_tokens"] += run.usage.prompt_tokens
            self._usage["output_tokens"] += run.usage.completion_tokens
        
        # Get response
        messages = self.client.beta.threads.messages.list(thread_id=self.thread.id)
        response = messages.data[0].content[0].text.value
        
        # Update history
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": response, "tools": tool_results})
        
        return {
            "response": response,
            "tools": tool_results,
        }
    
    def get_history(self) -> list:
        return self.history
    
    def cleanup(self):
        """Delete assistant and thread."""
        self.client.beta.assistants.delete(self.assistant.id)
        self.client.beta.threads.delete(self.thread.id)


class ClaudeCFDAssistant(CFDAssistant):
    """Claude implementation with manual thread management."""
    
    def __init__(self, base_mcp, extended_mcp, model: str = None, data_source: str = None):
        super().__init__(base_mcp, extended_mcp, data_source)
        _load_dotenv()
        
        from anthropic import Anthropic
        self.client = Anthropic()
        self.model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        
        # Build tools in Claude format
        self.tools = self._get_claude_tools()
        
        # System prompt (cached)
        self.system = self._build_system()
        
        # Conversation history
        self.messages = []
    
    def _get_claude_tools(self) -> list:
        """Convert tools to Claude format."""
        tools = []
        for tool in self._get_all_tools():
            func = tool["function"]
            tools.append({
                "name": func["name"],
                "description": func["description"],
                "input_schema": func["parameters"],
            })
        return tools
    
    def _build_system(self) -> str:
        """Build system prompt with ontology reasoning."""
        base = _CFD_SYSTEM_PROMPT
        if self.data_source:
            base += f"\n\nThe current data source is: {self.data_source}\nUse this as proxy_name when calling tools.\n"
        
        return base
    
    def execute(self, query: str) -> dict:
        """Execute a query using Claude."""
        # Add user message
        self.messages.append({"role": "user", "content": query})
        
        tool_results = []
        
        # Build system with cache control for prompt caching
        # This caches the instructions + ontology (90% cheaper on cache hit)
        system_with_cache = [
            {
                "type": "text",
                "text": self.system,
                "cache_control": {"type": "ephemeral"}
            }
        ]
        
        # Loop for tool use
        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_with_cache,
                tools=self.tools,
                messages=self.messages,
            )
            
            # Track usage (including cache stats)
            self._usage["requests"] += 1
            self._usage["input_tokens"] += response.usage.input_tokens
            self._usage["output_tokens"] += response.usage.output_tokens
            
            # Track cache performance if available
            if hasattr(response.usage, "cache_creation_input_tokens"):
                self._usage.setdefault("cache_creation_tokens", 0)
                self._usage["cache_creation_tokens"] += response.usage.cache_creation_input_tokens
            if hasattr(response.usage, "cache_read_input_tokens"):
                self._usage.setdefault("cache_read_tokens", 0)
                self._usage["cache_read_tokens"] += response.usage.cache_read_input_tokens
            
            # Check for tool use
            if response.stop_reason == "tool_use":
                # Process tool calls
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                
                # Add assistant response
                self.messages.append({"role": "assistant", "content": response.content})
                
                # Execute tools and collect results
                tool_results_content = []
                for block in tool_use_blocks:
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "tool": block.name,
                        "args": block.input,
                        "result": result,
                    })
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
                
                # Add tool results
                self.messages.append({"role": "user", "content": tool_results_content})
            else:
                # Done - extract text response
                text_blocks = [b for b in response.content if hasattr(b, "text")]
                response_text = text_blocks[0].text if text_blocks else ""
                
                # Add to history
                self.messages.append({"role": "assistant", "content": response.content})
                self.history.append({"role": "user", "content": query})
                self.history.append({"role": "assistant", "content": response_text, "tools": tool_results})
                
                return {
                    "response": response_text,
                    "tools": tool_results,
                }
    
    def get_history(self) -> list:
        return self.history
    
    def reset(self):
        """Reset conversation."""
        super().reset()
        self.messages = []


def create_assistant(
    base_mcp,
    extended_mcp,
    provider: str = "openai",
    model: str = None,
    data_source: str = None,
) -> CFDAssistant:
    """
    Factory function to create a CFD assistant.
    
    Args:
        base_mcp: ParaViewMCP instance from trame-llm
        extended_mcp: ExtendedParaViewMCP instance
        provider: "openai" or "claude"
        model: Model to use (optional, uses env var or default)
        data_source: Name of the data source proxy (optional but recommended)
    
    Returns:
        CFDAssistant instance
    """
    if provider == "openai":
        return OpenAICFDAssistant(base_mcp, extended_mcp, model, data_source)
    elif provider == "claude":
        return ClaudeCFDAssistant(base_mcp, extended_mcp, model, data_source)
    else:
        raise ValueError(f"Unknown provider: {provider}")
