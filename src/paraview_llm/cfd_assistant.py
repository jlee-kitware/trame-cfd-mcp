"""
CFD Visualization Assistant - Safe, Tiered Architecture

DESIGN PRINCIPLE: LLM never makes execution decisions.

Architecture:
    Tier 1: Intent Recognition (LLM) - Classify user query
    Tier 2: Workflow Selection (Deterministic) - Map intent to workflow
    Tier 3: Execution (Deterministic) - Run workflow steps, manage state
    Tier 4: Summary (LLM) - Explain results to user

The LLM is restricted to:
    - Understanding what the user wants (intent classification)
    - Explaining what happened (result summarization)

The LLM is NEVER allowed to:
    - Decide which tools to call
    - Manage proxy names or pipeline state
    - Loop or retry on failures
    - Compose novel tool sequences
"""

from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
import json


# =============================================================================
# INTENT TYPES - The only things LLM can classify into
# =============================================================================

class IntentType(Enum):
    """Predefined intent categories. LLM classifies into ONE of these."""
    
    # Vortex visualization - different methods
    VISUALIZE_VORTICES = "visualize_vortices"           # Default Q-criterion
    VISUALIZE_VORTICES_LAMBDA2 = "visualize_vortices_lambda2"
    VISUALIZE_VORTICES_HELICITY = "visualize_vortices_helicity"
    
    # Flow visualization
    VISUALIZE_WAKE = "visualize_wake"
    VISUALIZE_STREAMLINES = "visualize_streamlines"
    CREATE_SLICE = "create_slice"
    
    # Force analysis
    COMPUTE_FORCES = "compute_forces"
    ANALYZE_DRAG = "analyze_drag"
    ANALYZE_LIFT = "analyze_lift"
    
    # Field analysis
    FIELD_STATISTICS = "field_statistics"
    FIELD_HISTOGRAM = "field_histogram"              # histogram chart of field distribution
    
    # Feature/location finding (analytical interrogation)
    FIND_STAGNATION = "find_stagnation"          # min velocity
    FIND_MAXIMUM = "find_maximum"                 # max of any field
    FIND_MINIMUM = "find_minimum"                 # min of any field  
    FIND_BY_QUERY = "find_by_query"              # query-based location finding
    COUNT_BY_QUERY = "count_by_query"            # count points matching query
    
    # Region detection
    DETECT_WAKE = "detect_wake"
    
    # Data exploration
    DESCRIBE_DATA = "describe_data"
    
    # View control
    RESET_VIEW = "reset_view"
    HIDE_ALL = "hide_all"
    
    # Information
    EXPLAIN_CONCEPT = "explain_concept"
    DESCRIBE_SESSION = "describe_session"        # what have we done so far
    
    # Fallback
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """Structured intent from LLM classification."""
    type: IntentType
    
    # Parameters extracted from query
    target_field: Optional[str] = None      # pressure, velocity, etc.
    target_region: Optional[str] = None     # wake, body, center, etc.
    slice_normal: Optional[str] = None      # x, y, z, streamwise, etc.
    color_by: Optional[str] = None          # Field to color by
    topic: Optional[str] = None             # For explain_concept
    query_expression: Optional[str] = None  # For find_by_query, count_by_query
    
    # Original query for context
    raw_query: str = ""


# =============================================================================
# WORKFLOW DEFINITIONS - Predefined, deterministic sequences
# =============================================================================

# Placeholders resolved at execution:
#   {data_source} - Name of loaded dataset
#   {result.field} - Field from previous step result

WORKFLOWS = {
    IntentType.VISUALIZE_VORTICES: {
        "name": "Visualize Vortices (Q-criterion)",
        "description": "Show vortical structures using Q-criterion",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("create_vortex_isosurface", {"method": "q_criterion"}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.VISUALIZE_VORTICES_LAMBDA2: {
        "name": "Visualize Vortices (Lambda2)",
        "description": "Show vortex cores using Lambda2 criterion",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("create_vortex_isosurface", {"method": "lambda2"}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.VISUALIZE_VORTICES_HELICITY: {
        "name": "Visualize Vortices (Helicity)",
        "description": "Show helical vortex structures",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("create_vortex_isosurface", {"method": "helicity"}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.VISUALIZE_WAKE: {
        "name": "Visualize Wake",
        "description": "Show wake flow with streamlines",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("detect_wake_region", {}),
            ("create_streamlines", {}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.VISUALIZE_STREAMLINES: {
        "name": "Visualize Streamlines",
        "description": "Show flow streamlines",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("ensure_velocity_vector", {}),
            ("create_streamlines", {}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.CREATE_SLICE: {
        "name": "Create Slice",
        "description": "Create a slice plane through the data",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.15}),
            ("create_slice_at_center", {}),
            ("focus_on_last", {}),
        ],
    },
    
    IntentType.COMPUTE_FORCES: {
        "name": "Compute Forces",
        "description": "Calculate drag and lift forces",
        "steps": [
            ("compute_forces", {}),
        ],
    },
    
    IntentType.ANALYZE_DRAG: {
        "name": "Analyze Drag Distribution",
        "description": "Show accumulated drag distribution along body",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.3}),
            ("create_force_distribution_chart", {"force_axis": "drag"}),
        ],
    },
    
    IntentType.ANALYZE_LIFT: {
        "name": "Analyze Lift Distribution",
        "description": "Show accumulated lift distribution along body",
        "steps": [
            ("hide_all", {}),
            ("show_data_context", {"opacity": 0.3}),
            ("create_force_distribution_chart", {"force_axis": "lift"}),
        ],
    },
    
    IntentType.FIELD_STATISTICS: {
        "name": "Field Statistics",
        "description": "Get min/max/mean of a field",
        "steps": [
            ("field_statistics", {}),
        ],
    },
    
    IntentType.FIELD_HISTOGRAM: {
        "name": "Field Histogram",
        "description": "Create histogram chart showing field distribution",
        "steps": [
            ("create_histogram_chart", {}),
        ],
    },
    
    IntentType.FIND_STAGNATION: {
        "name": "Find Stagnation Point",
        "description": "Find location of minimum velocity (stagnation)",
        "steps": [
            ("find_minimum", {"field": "Velocity"}),
        ],
    },
    
    IntentType.FIND_MAXIMUM: {
        "name": "Find Maximum",
        "description": "Find location of maximum field value",
        "steps": [
            ("find_maximum", {}),
        ],
    },
    
    IntentType.FIND_MINIMUM: {
        "name": "Find Minimum",
        "description": "Find location of minimum field value",
        "steps": [
            ("find_minimum", {}),
        ],
    },
    
    IntentType.FIND_BY_QUERY: {
        "name": "Find by Query",
        "description": "Find centroid of region matching query expression",
        "steps": [
            ("find_by_query", {}),
        ],
    },
    
    IntentType.COUNT_BY_QUERY: {
        "name": "Count by Query",
        "description": "Count points matching query expression",
        "steps": [
            ("count_by_query", {}),
        ],
    },
    
    IntentType.DESCRIBE_DATA: {
        "name": "Describe Data",
        "description": "Characterize the dataset",
        "steps": [
            ("characterize_dataset", {}),
        ],
    },
    
    IntentType.DETECT_WAKE: {
        "name": "Detect Wake Region",
        "description": "Find wake region based on velocity deficit",
        "steps": [
            ("ensure_velocity_vector", {}),
            ("detect_wake_region", {}),
        ],
    },
    
    IntentType.RESET_VIEW: {
        "name": "Reset View",
        "description": "Reset camera to default view",
        "steps": [
            ("reset_camera", {}),
        ],
    },
    
    IntentType.HIDE_ALL: {
        "name": "Hide All",
        "description": "Hide all visualizations",
        "steps": [
            ("hide_all", {}),
        ],
    },
    
    IntentType.EXPLAIN_CONCEPT: {
        "name": "Explain Concept",
        "description": "Explain a CFD concept using ontology",
        "steps": [
            ("explain_from_ontology", {}),  # Uses intent.topic
        ],
    },
    
    IntentType.DESCRIBE_SESSION: {
        "name": "Describe Session",
        "description": "Describe what has been done in this session",
        "steps": [
            ("describe_session", {}),
        ],
    },
}


# =============================================================================
# EXECUTION STATE - Managed by executor, never by LLM
# =============================================================================

@dataclass
class ExecutionState:
    """Pipeline state managed by executor."""
    data_source: str
    available_fields: set = field(default_factory=set)
    last_created_proxy: Optional[str] = None
    created_proxies: dict = field(default_factory=dict)
    step_results: list = field(default_factory=list)         # current query steps
    query_history: list = field(default_factory=list)        # all queries in session
    
    def register_proxy(self, name: str, proxy_type: str):
        self.created_proxies[name] = proxy_type
        self.last_created_proxy = name
    
    def record_query(self, intent_type: str, workflow_name: str, success: bool):
        self.query_history.append({
            "intent": intent_type,
            "workflow": workflow_name,
            "success": success
        })


# =============================================================================
# WORKFLOW EXECUTOR - Deterministic, no LLM involvement
# =============================================================================

class WorkflowExecutor:
    """
    Executes predefined workflows deterministically.
    
    NO LLM calls happen here. All decisions are made by:
    - Workflow definitions (which steps to run)
    - Intent parameters (which field, which region)
    - Ontology (domain knowledge for validation)
    """
    
    def __init__(self, extended_mcp, base_mcp, data_source: str, ontology=None):
        self.extended = extended_mcp
        self.base = base_mcp
        self.state = ExecutionState(data_source=data_source)
        
        # Load ontology for domain knowledge (NOT for LLM reasoning)
        if ontology is None:
            from .ontology_triples import CFDOntology
            self.ontology = CFDOntology()
        else:
            self.ontology = ontology
        
        # Cache available fields
        self._init_available_fields()
        
        # Tool dispatch table
        self._tools = self._build_tool_dispatch()
    
    def _init_available_fields(self):
        """Cache available fields from data source."""
        result = self.extended.characterize_dataset(proxy_name=self.state.data_source)
        if "error" not in result:
            fields = result.get("point_arrays", []) + result.get("cell_arrays", [])
            self.state.available_fields = set(fields)
    
    def _build_tool_dispatch(self) -> dict:
        """Map tool names to execution functions."""
        return {
            # Extended MCP tools
            "hide_all": lambda i: self.extended.hide_all(),
            "show_data_context": lambda i: self.extended.show_data_context(
                proxy_name=self.state.data_source,
                opacity=i.get("opacity", 0.15)
            ),
            "ensure_velocity_vector": lambda i: self.extended.ensure_velocity_vector(
                proxy_name=self.state.data_source
            ),
            "create_vortex_isosurface": lambda i: self._create_vortex_isosurface(i),
            "create_streamlines": lambda i: self._create_streamlines(i),
            "create_slice_at_center": lambda i: self._create_slice(i),
            "compute_forces": lambda i: self.extended.compute_forces(
                proxy_name=self.state.data_source
            ),
            "create_force_distribution_chart": lambda i: self.extended.create_force_distribution_chart(
                proxy_name=self.state.data_source,
                force_axis=i.get("force_axis", "drag")
            ),
            "create_histogram_chart": lambda i: self.extended.create_histogram_chart(
                field=i.get("target_field", "Velocity"),
                proxy_name=self.state.data_source
            ),
            "field_statistics": lambda i: self._field_statistics(i),
            "characterize_dataset": lambda i: self.extended.characterize_dataset(
                proxy_name=self.state.data_source
            ),
            "detect_wake_region": lambda i: self._detect_wake_region(i),
            "find_minimum": lambda i: self._find_minimum(i),
            "find_maximum": lambda i: self._find_maximum(i),
            "find_by_query": lambda i: self._find_by_query(i),
            "count_by_query": lambda i: self._count_by_query(i),
            "reset_camera": lambda i: self._reset_camera(),
            "focus_on_last": lambda i: self._focus_on_last(),
            "explain_from_ontology": lambda i: self._explain_from_ontology(i),
            "describe_session": lambda i: self._describe_session(),
        }
    
    def execute(self, intent: Intent) -> dict:
        """
        Execute workflow for an intent.
        
        This is DETERMINISTIC - no LLM involved.
        """
        self.state.step_results = []
        
        # Get workflow definition
        workflow = WORKFLOWS.get(intent.type)
        if workflow is None:
            return {
                "success": False,
                "error": f"No workflow defined for intent: {intent.type.value}",
                "intent": intent.type.value
            }
        
        # Execute each step in sequence
        results = []
        for step_name, step_params in workflow["steps"]:
            tool_fn = self._tools.get(step_name)
            if tool_fn is None:
                return {
                    "success": False,
                    "error": f"Unknown tool in workflow: {step_name}",
                    "intent": intent.type.value,
                    "completed_steps": results
                }
            
            # Merge step params with intent params
            params = {**step_params}
            if intent.target_field:
                params["target_field"] = intent.target_field
            if intent.color_by:
                params["color_by"] = intent.color_by
            if intent.slice_normal:
                params["slice_normal"] = intent.slice_normal
            if intent.topic:
                params["topic"] = intent.topic
            if intent.query_expression:
                params["query_expression"] = intent.query_expression
            
            # Execute tool
            try:
                result = tool_fn(params)
                results.append({"step": step_name, "result": result})
                self.state.step_results.append(result)
                
                # Check for error
                if isinstance(result, dict) and "error" in result:
                    return {
                        "success": False,
                        "error": result["error"],
                        "intent": intent.type.value,
                        "workflow": workflow["name"],
                        "failed_step": step_name,
                        "completed_steps": results[:-1]
                    }
                    
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "intent": intent.type.value,
                    "workflow": workflow["name"],
                    "failed_step": step_name,
                    "completed_steps": results
                }
        
        # Return final result
        final_result = results[-1]["result"] if results else {}
        
        # Record this query in history
        self.state.record_query(intent.type.value, workflow["name"], True)
        
        return {
            "success": True,
            "intent": intent.type.value,
            "workflow": workflow["name"],
            "result": final_result,
            "all_steps": results
        }
    
    # =========================================================================
    # Tool implementations
    # =========================================================================
    
    def _create_vortex_isosurface(self, params: dict) -> dict:
        result = self.extended.create_vortex_isosurface(
            proxy_name=self.state.data_source,
            method=params.get("method", "q_criterion")
        )
        if "name" in result:
            self.state.register_proxy(result["name"], "Contour")
        return result
    
    def _create_streamlines(self, params: dict) -> dict:
        result = self.extended.create_streamlines(
            proxy_name=self.state.data_source,
            color_field=params.get("color_by", "Velocity")
        )
        if "tube_name" in result:
            self.state.register_proxy(result["tube_name"], "Tube")
        elif "streamlines_name" in result:
            self.state.register_proxy(result["streamlines_name"], "StreamTracer")
        return result
    
    def _create_slice(self, params: dict) -> dict:
        from paraview import simple
        
        # Get center position
        geo = self.extended.get_geometry_info(proxy_name=self.state.data_source)
        origin = geo.get("center", [0, 0, 0])
        
        # Get normal from intent
        normal_map = {
            "x": [1, 0, 0], "streamwise": [1, 0, 0],
            "y": [0, 1, 0], "vertical": [0, 1, 0],
            "z": [0, 0, 1], "spanwise": [0, 0, 1],
        }
        normal = normal_map.get(params.get("slice_normal"), [1, 0, 0])
        
        # Create slice
        create_result = self.base.create("Slice", input_proxy=self.state.data_source)
        
        # Get slice name
        slice_name = create_result.get("name")
        if slice_name is None:
            active = simple.GetActiveSource()
            if active:
                for name, p in simple.GetSources().items():
                    if p == active:
                        slice_name = name[0]
                        break
        
        if not slice_name:
            return {"error": "Failed to create slice"}
        
        # Configure
        self.base.update_sub_property("SliceType", "Origin", origin, slice_name)
        self.base.update_sub_property("SliceType", "Normal", normal, slice_name)
        
        # Color
        color_field = params.get("color_by") or params.get("target_field") or "Velocity"
        self.base.update_color(slice_name, color_field)
        
        self.state.register_proxy(slice_name, "Slice")
        
        return {
            "name": slice_name,
            "origin": origin,
            "normal": normal,
            "color_by": color_field
        }
    
    def _field_statistics(self, params: dict) -> dict:
        field = params.get("target_field", "Velocity")
        return self.extended.field_statistics(field, proxy_name=self.state.data_source)
    
    def _detect_wake_region(self, params: dict) -> dict:
        return self.extended.detect_wake_region(proxy_name=self.state.data_source)
    
    def _find_minimum(self, params: dict) -> dict:
        field = params.get("field", params.get("target_field", "Velocity"))
        return self.extended.find_minimum(field, proxy_name=self.state.data_source)
    
    def _find_maximum(self, params: dict) -> dict:
        field = params.get("field", params.get("target_field", "Velocity"))
        return self.extended.find_maximum(field, proxy_name=self.state.data_source)
    
    def _find_by_query(self, params: dict) -> dict:
        """Find location by query - uses full NumPy expression capability."""
        query = params.get("query_expression")
        if not query:
            return {"error": "No query expression provided. Use expressions like 'mag(Velocity) < 0.1' or 'Velocity_X < 0'"}
        return self.extended.find_by_query(query, proxy_name=self.state.data_source)
    
    def _count_by_query(self, params: dict) -> dict:
        query = params.get("query_expression")
        if not query:
            return {"error": "No query expression provided. Use expressions like 'mag(Velocity) < 0.1' or 'p < -0.5'"}
        return self.extended.query_select(query, proxy_name=self.state.data_source)
    
    def _reset_camera(self) -> dict:
        from paraview import simple
        simple.ResetCamera()
        return {"status": "camera_reset"}
    
    def _focus_on_last(self) -> dict:
        if self.state.last_created_proxy:
            return self.base.focus_on(self.state.last_created_proxy)
        return {"status": "no_proxy_to_focus"}
    
    def _explain_from_ontology(self, params: dict) -> dict:
        topic = params.get("topic", "")
        if not topic:
            return {"error": "No topic specified"}
        
        # Get all relationships for this topic
        as_subject = self.ontology.query(subject=topic)
        as_object = self.ontology.query(obj=topic)
        detection_chain = self.ontology.infer_detection_chain(topic)
        requirements = list(self.ontology.infer_requirements(topic))
        
        return {
            "topic": topic,
            "relationships": {
                "properties": [(p, o) for (s, p, o) in as_subject],
                "used_by": [(s, p) for (s, p, o) in as_object],
            },
            "detection_method": detection_chain,
            "requirements": requirements
        }
    
    def _describe_session(self) -> dict:
        """Describe what has been done in this session."""
        return {
            "data_source": self.state.data_source,
            "available_fields": list(self.state.available_fields),
            "created_visualizations": self.state.created_proxies.copy(),
            "query_history": self.state.query_history.copy(),
            "num_queries": len(self.state.query_history)
        }


# =============================================================================
# INTENT CLASSIFIER - The ONLY place LLM is used for decisions
# =============================================================================

INTENT_CLASSIFICATION_PROMPT = """Classify the user's CFD visualization request into exactly ONE intent type.

INTENT TYPES:
Vortex visualization:
- visualize_vortices: Show vortices using Q-criterion (DEFAULT for vortex requests)
- visualize_vortices_lambda2: Show vortex cores using Lambda2 criterion
- visualize_vortices_helicity: Show helical vortex structures

Flow visualization:
- visualize_wake: Show wake region with streamlines
- visualize_streamlines: Show flow streamlines
- create_slice: Create a slice/cut plane

Force analysis:
- compute_forces: Calculate drag and lift forces (when user wants VALUES)
- analyze_drag: Show accumulated drag distribution chart
- analyze_lift: Show accumulated lift distribution chart

Field analysis:
- field_statistics: Get min/max/mean of a field
- field_histogram: Create histogram chart showing field value distribution

Feature/location finding:
- find_stagnation: Find stagnation point (minimum velocity)
- find_maximum: Find maximum of a field (e.g., highest pressure)
- find_minimum: Find minimum of a field
- find_by_query: Find location matching a query expression (e.g., "where velocity < 0.1")
- count_by_query: Count points matching a query expression

Region detection:
- detect_wake: Detect wake region bounds

Data exploration:
- describe_data: Describe the dataset, list fields

Session/history:
- describe_session: Describe what has been done, what visualizations exist

Other:
- reset_view: Reset camera
- hide_all: Hide all visualizations
- explain_concept: Explain a CFD concept (ONLY for conceptual questions)
- unknown: Cannot determine intent

EXAMPLES:
- "Show vortices" → visualize_vortices
- "Show vortices with lambda2" → visualize_vortices_lambda2
- "Helical vortices" → visualize_vortices_helicity
- "Find stagnation point" → find_stagnation
- "Where is the highest pressure?" → find_maximum (target_field: "pressure")
- "What have we done?" → describe_session
- "What visualizations did we create?" → describe_session
- "Summarize our analysis" → describe_session
- "Where is velocity less than 0.1?" → find_by_query (query_expression: "mag(Velocity) < 0.1")
- "How many points have negative pressure?" → count_by_query (query_expression: "p < 0")
- "Find the recirculation zone" → find_by_query (query_expression: "Velocity_X < 0")
- "What is drag?" → explain_concept (conceptual/definitional question)
- "What is the drag force?" → compute_forces (wants numerical value)
- "What are the drag and lift forces?" → compute_forces (wants numerical values)
- "What are the forces?" → compute_forces
- "Calculate the forces" → compute_forces
- "Show drag distribution" → analyze_drag
- "Show lift distribution" → analyze_lift
- "Spanwise lift" → analyze_lift
- "Show histogram of pressure" → field_histogram (target_field: "pressure")
- "Distribution of velocity" → field_histogram (target_field: "Velocity")
- "Find high gradient" → find_maximum (NOT find_by_query - gradient isn't a queryable field)

IMPORTANT DISTINCTIONS:
- Questions asking "what is X" where X is a concept → explain_concept
- Questions asking "what is/are the X" where X is a measurable quantity → compute_forces or find_maximum/minimum
- "What are the forces?" → compute_forces (wants numbers)
- "What is force?" → explain_concept (wants definition)

RESPOND WITH JSON ONLY:
{
  "type": "intent_type",
  "target_field": "field name if mentioned",
  "target_region": "region if mentioned",
  "slice_normal": "direction if mentioned",
  "color_by": "field to color by if mentioned",
  "topic": "concept to explain if explain_concept",
  "query_expression": "ParaView query expression for find_by_query/count_by_query"
}
"""


def classify_intent_openai(query: str, client, model: str = "gpt-4o-mini") -> tuple[Intent, dict]:
    """
    Classify user query into an Intent using OpenAI.
    
    This is the ONLY LLM call for decision-making.
    
    Returns:
        Tuple of (Intent, usage_dict) where usage_dict has prompt_tokens, completion_tokens, total_tokens
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": query}
        ],
        response_format={"type": "json_object"},
        max_tokens=150,
        temperature=0
    )
    
    result = json.loads(response.choices[0].message.content)
    
    # Extract usage
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens
    }
    
    # Map to enum
    intent_type = IntentType.UNKNOWN
    type_str = result.get("type", "unknown").lower()
    for it in IntentType:
        if it.value == type_str:
            intent_type = it
            break
    
    intent = Intent(
        type=intent_type,
        target_field=result.get("target_field"),
        target_region=result.get("target_region"),
        slice_normal=result.get("slice_normal"),
        color_by=result.get("color_by"),
        topic=result.get("topic"),
        query_expression=result.get("query_expression"),
        raw_query=query
    )
    
    return intent, usage


def classify_intent_claude(query: str, client, model: str = "claude-sonnet-4-20250514") -> tuple[Intent, dict]:
    """Classify user query into an Intent using Claude."""
    response = client.messages.create(
        model=model,
        max_tokens=150,
        system=INTENT_CLASSIFICATION_PROMPT,
        messages=[{"role": "user", "content": query}]
    )
    
    text = response.content[0].text
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    
    result = json.loads(text.strip())
    
    # Extract usage
    usage = {
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.input_tokens + response.usage.output_tokens
    }
    
    intent_type = IntentType.UNKNOWN
    type_str = result.get("type", "unknown").lower()
    for it in IntentType:
        if it.value == type_str:
            intent_type = it
            break
    
    intent = Intent(
        type=intent_type,
        target_field=result.get("target_field"),
        target_region=result.get("target_region"),
        slice_normal=result.get("slice_normal"),
        color_by=result.get("color_by"),
        topic=result.get("topic"),
        query_expression=result.get("query_expression"),
        raw_query=query
    )
    
    return intent, usage


# =============================================================================
# RESULT SUMMARIZER - LLM used only for explanation, not decisions
# =============================================================================

def summarize_result_openai(query: str, result: dict, client, model: str = "gpt-4o-mini") -> tuple[str, dict]:
    """Generate natural language summary of execution result."""
    prompt = f"""The user asked: "{query}"

Result: {json.dumps(result, indent=2, default=str)[:1500]}

Write a brief response (2-3 sentences) explaining what was done and any key findings.
Be helpful and concise. Don't mention technical details like proxy names.
"""
    
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.3
    )
    
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens
    }
    
    return response.choices[0].message.content, usage


def summarize_result_claude(query: str, result: dict, client, model: str = "claude-sonnet-4-20250514") -> tuple[str, dict]:
    """Generate natural language summary using Claude."""
    prompt = f"""The user asked: "{query}"

Result: {json.dumps(result, indent=2, default=str)[:1500]}

Write a brief response (2-3 sentences) explaining what was done and any key findings.
Be helpful and concise. Don't mention technical details like proxy names.
"""
    
    response = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    
    usage = {
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.input_tokens + response.usage.output_tokens
    }
    
    return response.content[0].text, usage


# =============================================================================
# MAIN ASSISTANT - Ties together the safe architecture
# =============================================================================

class CFDAssistant:
    """
    Safe CFD visualization assistant.
    
    Architecture enforces:
    - LLM only classifies intent and summarizes results
    - All execution is deterministic via predefined workflows
    - No LLM in the execution loop
    """
    
    def __init__(
        self,
        extended_mcp,
        base_mcp,
        data_source: str,
        provider: str = "openai",
        model: str = None
    ):
        self.executor = WorkflowExecutor(extended_mcp, base_mcp, data_source)
        self.provider = provider
        
        # Initialize LLM client
        if provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()
            self.model = model or "gpt-4o-mini"
            self._classify = lambda q: classify_intent_openai(q, self.client, self.model)
            self._summarize = lambda q, r: summarize_result_openai(q, r, self.client, self.model)
        else:
            import anthropic
            self.client = anthropic.Anthropic()
            self.model = model or "claude-sonnet-4-20250514"
            self._classify = lambda q: classify_intent_claude(q, self.client, self.model)
            self._summarize = lambda q, r: summarize_result_claude(q, r, self.client, self.model)
        
        self.history = []
        self._usage = {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    
    def query(self, user_query: str) -> dict:
        """
        Process a user query through the safe pipeline.
        
        Tier 1: LLM classifies intent
        Tier 2: Workflow selected (deterministic)
        Tier 3: Workflow executed (deterministic)
        Tier 4: LLM summarizes result
        """
        # Tier 1: Intent classification (LLM)
        intent, classify_usage = self._classify(user_query)
        self._usage["requests"] += 1
        self._usage["prompt_tokens"] += classify_usage["prompt_tokens"]
        self._usage["completion_tokens"] += classify_usage["completion_tokens"]
        self._usage["total_tokens"] += classify_usage["total_tokens"]
        
        # Tier 2 & 3: Workflow selection and execution (DETERMINISTIC)
        exec_result = self.executor.execute(intent)
        
        # Tier 4: Result summarization (LLM)
        if exec_result["success"]:
            response, summarize_usage = self._summarize(user_query, exec_result["result"])
            self._usage["requests"] += 1
            self._usage["prompt_tokens"] += summarize_usage["prompt_tokens"]
            self._usage["completion_tokens"] += summarize_usage["completion_tokens"]
            self._usage["total_tokens"] += summarize_usage["total_tokens"]
        else:
            response = f"I couldn't complete that request: {exec_result.get('error', 'Unknown error')}"
        
        # Track history
        self.history.append({
            "query": user_query,
            "intent": intent.type.value,
            "success": exec_result["success"],
            "response": response
        })
        
        return {
            "response": response,
            "intent": intent,
            "result": exec_result,
            "success": exec_result["success"]
        }
    
    @property
    def usage(self) -> dict:
        """Get usage statistics including token counts and estimated cost."""
        # Pricing for gpt-4o-mini (as of 2024): $0.15/1M input, $0.60/1M output
        # Pricing for claude-sonnet: $3/1M input, $15/1M output
        if self.provider == "openai":
            input_cost = self._usage["prompt_tokens"] * 0.15 / 1_000_000
            output_cost = self._usage["completion_tokens"] * 0.60 / 1_000_000
        else:
            input_cost = self._usage["prompt_tokens"] * 3.0 / 1_000_000
            output_cost = self._usage["completion_tokens"] * 15.0 / 1_000_000
        
        return {
            **self._usage,
            "model": self.model,
            "estimated_cost_usd": round(input_cost + output_cost, 6)
        }
