# Architecture

## Design Philosophy

### Single-Shot vs In-Loop

This system uses **single-shot execution**: one LLM call generates a complete tool plan, which executes locally without further LLM interaction.

```
SINGLE-SHOT (implemented):
  Query → Orchestrator → Enriched Prompt → LLM (1 call) → Tool Plan → Execute

IN-LOOP (rejected):
  Query → LLM → Tool → Result → LLM → Tool → Result → LLM → ...
              $           $           $
```

**Why single-shot?**

| Concern | In-Loop | Single-Shot |
|---------|---------|-------------|
| Cost | ~$0.05/query (5+ calls) | ~$0.01/query (1 call) |
| Latency | ~10s (API round-trips) | ~2s (1 API call) |
| Determinism | Variable (LLM may retry) | Consistent |
| Error handling | LLM self-corrects (masks issues) | Fails fast (exposes issues) |

**Key insight**: If the LLM needs to self-correct, that's a signal to improve the ontology or tools—not to add runtime patching.

### Domain Knowledge Location

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WHERE DOMAIN KNOWLEDGE LIVES                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ONTOLOGY (cfd.json)                                                        │
│  ├── Concept definitions (what is a vortex, stagnation point, etc.)         │
│  ├── Keyword mappings (query terms → concepts)                              │
│  └── Detection hints (concept → tool + method)                              │
│                                                                             │
│  ORCHESTRATOR (orchestrator.py)                                             │
│  ├── Query → concept matching                                               │
│  ├── Prompt enrichment with relevant hints                                  │
│  └── Workflow patterns (hide_all → show_context → analyze → visualize)      │
│                                                                             │
│  TOOLS (extended_mcp.py)                                                    │
│  ├── Auto-detection (streamwise direction, field types)                     │
│  ├── Intelligent defaults (percentile thresholds, reference values)         │
│  └── Error handling (missing fields, invalid parameters)                    │
│                                                                             │
│  LLM (external)                                                             │
│  └── Final tool selection given enriched context                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

The goal is to encode as much domain knowledge as possible in ontology/tools, minimizing what the LLM must figure out.

## Component Details

### 1. Ontology (`ontology/cfd.json`)

JSON database of CFD domain knowledge:

```json
{
  "concepts": {
    "vortex_core": {
      "definition": "Region of concentrated rotation in a fluid",
      "physical_meaning": "Coherent rotating structure",
      "keywords": ["vortex", "vortices", "swirl", "rotation", "eddy"],
      "detection": {
        "tool": "create_vortex_isosurface",
        "method": "q_criterion"
      }
    }
  },
  "visualizations": {
    "isosurface": {
      "description": "3D surface of constant field value",
      "best_for": ["vortex cores", "shock waves", "interfaces"],
      "tool": "create_isosurface"
    }
  }
}
```

**Extension**: Add new CFD concepts by editing JSON—no code changes needed.

### 2. Orchestrator (`orchestrator.py`)

Transforms user queries into enriched prompts:

```python
class Orchestrator:
    def build_prompt(self, user_query: str, data_source: str) -> str:
        # 1. Match query keywords to ontology concepts
        # 2. Extract relevant detection hints
        # 3. Match to visualization suggestions
        # 4. Assemble enriched prompt with workflow
```

**Input**: `"show me the vortices"`

**Output**:
```
You are a CFD post-processing assistant...

DATA SOURCE: simulation.vtm
USER REQUEST: show me the vortices

RELEVANT CFD CONCEPTS:
- vortex_core: Region of concentrated rotation
  → create_vortex_isosurface(method="q_criterion", proxy_name="simulation.vtm")

WORKFLOW:
1. hide_all()
2. show_data_context(proxy_name="simulation.vtm", opacity=0.15)
3. [analysis/visualization tools]
4. focus_on(proxy_name=result)
```

### 3. Extended MCP (`extended_mcp.py`)

CFD-specific tools extending trame-llm's ParaViewMCP:

```python
class ExtendedParaViewMCP:
    def __init__(self, base_mcp: ParaViewMCP):
        self._base = base_mcp  # Inherit base ParaView tools
    
    # Analysis tools
    def find_minimum(self, field, proxy_name) -> dict
    def find_maximum(self, field, proxy_name) -> dict
    def find_high_gradient(self, field, proxy_name) -> dict
    def field_statistics(self, field, proxy_name) -> dict
    def field_histogram(self, field, num_bins, proxy_name) -> dict
    def compute_forces(self, ...) -> dict
    
    # Visualization tools  
    def create_vortex_isosurface(self, method, threshold, percentile, ...) -> dict
    def create_slice(self, origin, normal, color_field, ...) -> dict
    def create_streamlines(self, seed_point, ...) -> dict
    def create_force_distribution_chart(self, force_axis, distribution_axis, ...) -> dict
    
    # Utility tools
    def detect_streamwise_direction(self, proxy_name) -> dict
    def hide_all(self) -> dict
    def show_data_context(self, proxy_name, opacity) -> dict
    def focus_on(self, proxy_name) -> dict
```

**Key design patterns**:

1. **Semantic field resolution**: `"velocity"` → finds `"U"`, `"Velocity"`, `"velocity"`, etc.
2. **Auto-detection**: Streamwise direction from velocity field
3. **Intelligent defaults**: Percentile-based thresholds adapt to data range
4. **Consistent returns**: All tools return `dict` with `status`/`error` keys

### 4. Mock Executor (`mock_llm.py`)

Deterministic tool sequences for testing:

```python
MOCK_RESPONSES = {
    "vortices_q": [
        ("hide_all", {}),
        ("show_data_context", {"proxy_name": "{data_source}", "opacity": 0.15}),
        ("create_vortex_isosurface", {"method": "q_criterion", "proxy_name": "{data_source}"}),
        ("focus_on", {"proxy_name": "{last_created}"}),
        ("set_streamwise_view", {"proxy_name": "{last_created}"}),
    ],
    # ... more test cases
}
```

**Purpose**: 
- Fast CI testing (no API calls)
- Regression detection (deterministic)
- Tool validation (exercises all tools)

**NOT the "correct" answer**: Mock defines ONE valid approach. Real LLM may choose differently and still be correct.

### 5. Single-Shot Executor (`single_shot.py`)

Production executor with one LLM call:

```python
class SingleShotExecutor:
    def __init__(self, extended_mcp, data_source, model="gpt-4o"):
        self.orchestrator = Orchestrator()  # Domain knowledge
        self.mcp = extended_mcp              # Tools
        self.client = OpenAI()               # LLM client
    
    def execute(self, query: str) -> list:
        # 1. Build enriched prompt (orchestrator)
        prompt = self.orchestrator.build_prompt(query, self.data_source)
        
        # 2. Single LLM call to get tool plan
        response = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            tools=self.tools,
            tool_choice="required"
        )
        
        # 3. Execute tools locally
        for tool_name, kwargs in plan:
            result = getattr(self.mcp, tool_name)(**kwargs)
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User: "show me how drag accumulates along the wing"                        │
│                           │                                                 │
│                           ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ ORCHESTRATOR                                                        │    │
│  │                                                                     │    │
│  │ 1. Keyword match: "drag" → drag_force concept                       │    │
│  │ 2. Keyword match: "accumulates" → distribution visualization        │    │
│  │ 3. Build enriched prompt with hints:                                │    │
│  │    - create_force_distribution_chart(force_axis="drag", ...)        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                           │                                                 │
│                           ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ LLM (OpenAI gpt-4o)                                                 │    │
│  │                                                                     │    │
│  │ Input: Enriched prompt + tool schemas                               │    │
│  │ Output: [                                                           │    │
│  │   ("create_force_distribution_chart", {                             │    │
│  │     "force_axis": "drag",                                           │    │
│  │     "distribution_axis": "streamwise",                              │    │
│  │     "proxy_name": "simulation.vtm"                                  │    │
│  │   })                                                                │    │
│  │ ]                                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                           │                                                 │
│                           ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ EXTENDED MCP                                                        │    │
│  │                                                                     │    │
│  │ create_force_distribution_chart():                                  │    │
│  │ 1. Auto-detect streamwise direction (velocity-weighted average)     │    │
│  │ 2. Extract body surface (filter boundary cells)                     │    │
│  │ 3. Compute cell normals                                             │    │
│  │ 4. Integrate pressure forces: F = -∫ p·n·dA                        │    │
│  │ 5. Bin by position along streamwise axis                            │    │
│  │ 6. Compute cumulative sum                                           │    │
│  │ 7. Create XY chart view                                             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                           │                                                 │
│                           ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ PARAVIEW                                                            │    │
│  │                                                                     │    │
│  │ [XY Plot showing accumulated drag vs. position]                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Vortex Detection Methods

The system supports five vortex identification methods:

| Method | Formula | Threshold | Best For |
|--------|---------|-----------|----------|
| **Q-criterion** | Q = ½(‖Ω‖² - ‖S‖²) | Percentile of Q > 0 | General vortices |
| **Lambda2** | λ₂(S² + Ω²) | 1% of min(λ₂) | Vortex cores |
| **Swirling Strength** | λ_ci (imaginary eigenvalue) | Percentile > 0 | Attached vortices |
| **Vorticity Magnitude** | ‖ω‖ = ‖∇ × V‖ | Percentile | Shear layers |
| **Normalized Helicity** | Hₙ = (ω · V) / (‖ω‖‖V‖) | |Hₙ| > 0.7 | Helical structures |

Implementation uses vectorized NumPy for performance (~0.1s vs 1.5s naive).

## Force Computation

Aerodynamic forces computed by pressure integration:

```
F = -∫∫_S p · n dA

Where:
  S = body surface (excluding domain boundaries)
  p = pressure field
  n = outward normal
  dA = cell area

Coefficients:
  Cd = F_drag / (½ρV²A_ref)
  Cl = F_lift / (½ρV²A_ref)

Auto-detection:
  V_∞ = max(|velocity|)  # Freestream velocity
  A_ref = frontal area    # Projected area normal to flow
```

## Adding New Tools

1. **Add method to `ExtendedParaViewMCP`**:
```python
def my_new_tool(self, param1: str, param2: float = 1.0, proxy_name: str = None) -> dict:
    """
    Tool description for LLM.
    
    Args:
        param1: Description
        param2: Description with default
        proxy_name: Data source
        
    Returns:
        Dict with results or error
    """
    proxy = self._get_proxy(proxy_name)
    # ... implementation
    return {"status": "done", "result": value}
```

2. **Register in `mcp` property**:
```python
extended_tools = [
    # ... existing tools
    self.my_new_tool,
]
```

3. **Add to ontology if concept-related**:
```json
{
  "concepts": {
    "my_concept": {
      "definition": "...",
      "keywords": ["keyword1", "keyword2"],
      "detection": {
        "tool": "my_new_tool",
        "param1": "default_value"
      }
    }
  }
}
```

4. **Add mock test**:
```python
MOCK_RESPONSES = {
    "my_test": [
        ("my_new_tool", {"param1": "value", "proxy_name": "{data_source}"}),
    ],
}
```

## Testing Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TESTING LAYERS                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MOCK TESTS (CI - every commit)                                             │
│  ├── Tests tool execution correctness                                       │
│  ├── Deterministic, fast (3.7s for 16 tests)                                │
│  ├── Free (no API calls)                                                    │
│  └── Catches tool regressions                                               │
│                                                                             │
│  SINGLE-SHOT TESTS (nightly/pre-release)                                    │
│  ├── Tests LLM understanding of domain                                      │
│  ├── Variable (LLM may choose different valid approaches)                   │
│  ├── ~$0.16 for 16 tests                                                    │
│  └── Catches ontology/prompt issues                                         │
│                                                                             │
│  VISUAL INSPECTION (manual/release)                                         │
│  ├── Review output images                                                   │
│  ├── Verify visualizations are meaningful                                   │
│  └── Catch subtle rendering issues                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
