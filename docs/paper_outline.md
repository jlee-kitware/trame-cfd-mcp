# Domain-Grounded Tool Orchestration for LLM-Guided Scientific Analysis

## Paper Outline

### Abstract
Scientific analysis workflows encode deep domain knowledge: a CFD engineer knows that
a Cp plateau suggests separation and should be confirmed with boundary layer profiles;
a topological data analyst knows that low-persistence features are noise and that
Morse-Smale segmentation reveals the dominant structure. Current LLM approaches generate
scripts that encode this knowledge implicitly (and often incorrectly). We present an
architecture where the LLM interprets intent and explains results while deterministic
domain tools handle execution, connected via the Model Context Protocol (MCP). A domain
ontology constrains planning to valid analysis chains. We demonstrate the approach in
two domains on the same ParaView infrastructure — computational fluid dynamics and
topological data analysis (TTK) — showing that adding a domain requires only an ontology
and tool wrappers around existing filters, not new software. Client-server deployment
(pvserver) provides scalability to production datasets.

---

### 1. Introduction

**The general problem:** Scientific toolkits are powerful but inaccessible. ParaView
has hundreds of filters. TTK has persistence diagrams, Morse-Smale complexes, contour
trees, critical points. 3D Slicer has hundreds of modules. The capability exists.
The gap: given a scientific question, which tools do you run, in what order, with
what parameters, and what do the results mean?

**The LLM opportunity and trap:**
- LLMs can interpret natural language intent and explain results
- But they cannot reliably encode procedural domain knowledge in generated code
- Script generation conflates two roles: deciding *what* to do (LLM strength)
  and *how* to do it (domain tool strength)

**Our thesis:** Separate the roles. The LLM handles intent and interpretation.
Domain tools handle execution. MCP provides the protocol. An ontology grounds
the planning in domain knowledge. This pattern generalizes across scientific
domains — we demonstrate it by adding a second domain (topological analysis)
to the same running system with only an ontology file and MCP tool wrappers.

**Contributions:**
1. Architecture: Plan-Execute-Interpret with domain ontology and MCP tool layer
2. CFD instantiation: three use cases showing diagnostic reasoning on aero data
3. TTK instantiation: three use cases showing topological analysis on scalar fields
4. Both domains on same pvserver — adding a domain is ontology + tool wrappers
5. Evidence that tool orchestration outperforms script generation on correctness
6. Scalable deployment via ParaView client-server with thin browser client

---

### 2. The Pattern: Domain-Grounded Tool Orchestration

*Domain-independent. The conceptual contribution.*

**2.1 Why script generation fails for scientific workflows**

Reference Zhao et al. 2026 (RAG for vtk.js) as representative state of the art.
Their error taxonomy: module errors, missing params, API hallucination, wrong logic.
Even with RAG, wrong-strategy errors persist — the hardest category.

The fundamental issue is domain knowledge, not code quality:
- Missing a step (no surface extraction before wall shear) → silent wrong results
- Wrong operator choice (streamlines when wall shear is needed) → plausible but wrong
- Array name assumptions (FUN3D "Pressure" vs OpenFOAM "p") → solver-specific fragility
- Parameter sensitivity (persistence threshold in TTK, contour level in ParaView)
  → requires domain judgment that LLMs approximate poorly

**2.2 Separation of concerns**

| Role | Component | Strength |
|------|-----------|----------|
| Decide what to analyze | LLM + Ontology | Intent interpretation, reasoning |
| Execute the analysis | Domain tools via MCP | Deterministic, validated, reusable |
| Explain what it means | LLM + Knowledge graph | Synthesis, contextualization |

The LLM never writes code. The tools never interpret intent. MCP connects them.

**2.3 Plan-Execute-Interpret loop**

Plan (Intent):
- User states question in domain language
- LLM consults domain ontology: phenomena → quantities → tools
- Ontology constrains plan to valid analysis chains
- Output: sequence of named tool invocations with parameters

Execute:
- MCP dispatches tool calls to ParaView pipeline (or any backend)
- Tools are deterministic workflows, not generated scripts
- Return structured results (quantitative data, not just renders)
- Session persists — pipeline state carries across invocations

Interpret:
- LLM receives structured results + domain knowledge graph
- Generates grounded explanation with quantitative specifics
- May propose follow-up analysis (closes the loop → next Plan)
- Knowledge graph provides causal reasoning chains

**2.4 Domain ontology structure**

General schema (domain-independent):
- phenomena: what can be observed or investigated
- indicators: quantities that reveal a phenomenon
- tools: operations that extract those quantities
- follow_ups: what to investigate next if detected
- significance: why it matters

Instantiated differently per domain but same schema:
- CFD: separation → {Cf zero-crossing, reversed BL velocity} → {wall_shear, bl_profile}
- TTK: noisy features → {low persistence pairs} → {persistence_diagram, simplification}

**2.5 MCP as the protocol layer**

Why MCP over direct function calling:
- Standardized tool discovery — LLM learns available operations dynamically
- Typed parameters and structured return values
- Stateless protocol over stateful session (pipeline persists server-side)
- Same protocol works regardless of domain tools behind it
- Tool metadata enables the LLM to reason about capabilities

Tool design principles:
- Two tiers: high-level domain workflows + low-level refinement
- Tools return structured data, not just confirmation
- Dynamic field resolution: semantic names → solver/format-specific arrays
- Safe pipeline management: consumer-aware deletion, filter reuse

**2.6 Client-server architecture**

- pvserver holds data, renders, executes pipeline — MPI-parallel
- trame mediates UI and MCP
- Browser is thin client (VtkRemoteView — compressed frames only)
- Dual-mode: same codebase runs in-process or client-server
- Scales to 100M+ cells — only extracted results transfer to client
- Both CFD and TTK tools run on the same pvserver instance

---

### 3. Domain 1: Computational Fluid Dynamics

**3.1 Implementation**

CFD ontology (~30 entries):
- Phenomena: separation, stagnation, recirculation, vortex breakdown, shock, wake
- Quantities: Cf, Cp, wall shear, velocity profiles, Q-criterion, total pressure
- Tools: show_vortices, show_streamlines, show_boundary_layer, show_forces,
  show_slice, show_flow_topology, show_histogram

MCP tool examples:
- show_boundary_layer(x_location): extracts BL profile normal to surface,
  returns displacement/momentum thickness, shape factor, velocity profile data
- show_forces(): integrates pressure and viscous forces, returns Cl/Cd decomposition

**3.2 Use case: Natural language → validated analysis**

Query: "Is there flow separation on the upper surface?"

Plan: ontology maps "separation" → Cf extraction + zero-crossing detection
Execute: extract surface → compute skin friction → find sign reversals
Interpret: "Separation at x/c = 0.72 based on Cf sign reversal. Reattachment
at x/c = 0.85."

Validation: 10 canonical flows, compare plan correctness and interpretation
accuracy against expert baseline.

**3.3 Use case: Iterative diagnostic reasoning**

Step 1: "Show me the pressure distribution"
→ Cp plateau detected on upper surface x/c = 0.55-0.70
→ Interpret proposes: "Consistent with laminar separation bubble. Recommend
  boundary layer profiles upstream and downstream to confirm."

Step 2: User approves → BL profiles at x/c = 0.50, 0.60, 0.70, 0.80
→ Reverse flow in velocity profiles at x/c = 0.60-0.70
→ Interpret: "Confirmed laminar separation bubble. Reattachment by x/c = 0.75."

Key: interpret phase drives next plan via ontology causal chains.
Script generation has no mechanism for this — it is one-shot.

**3.4 Use case: Cross-quantity synthesis**

Query: "What's driving the drag increase between 4° and 8° AoA?"

Plan (ontology decomposes drag): pressure drag (Cp integration) + viscous drag
(wall shear integration) + separation location + wake momentum deficit

Execute: all extractions for both cases in persistent pipeline session

Interpret: "Separation moved forward from x/c = 0.78 to 0.62. Pressure drag
increased 40%, viscous roughly constant. Wake deficit up 55%. Conclusion:
separation-induced pressure drag dominates — consistent with incipient stall."

Key: no single tool answers this. Value is orchestrated multi-step reasoning.

---

### 4. Domain 2: Topological Data Analysis (TTK)

*Same pvserver, same architecture. Different ontology, different tools.*

**4.1 Implementation**

TTK is already a ParaView plugin — runs on the same pvserver instance as CFD.
No new backend infrastructure. Adding this domain required:
- Topological analysis ontology (~25 entries)
- MCP tool wrappers around existing TTK filters
- Interpretation grounding in topological concepts

Ontology entries:
- Phenomena: noise vs signal features, dominant structures, merge/split events,
  symmetry breaking, topological transitions under parameter variation
- Quantities: persistence, number of critical points, Betti numbers,
  Morse-Smale cell count, saddle-connector topology
- Tools: persistence_diagram, persistence_curve, topological_simplification,
  critical_points, morse_smale_complex, contour_tree, merge_tree,
  fiber_surface, bottleneck_distance
- Follow-ups: if many low-persistence features → simplify and re-examine;
  if unexpected critical point → check data quality or resolution

MCP tool examples:
- compute_persistence(field): TTK PersistenceDiagram filter, returns
  birth-death pairs with persistence values and critical point types
- simplify_field(field, threshold): TTK TopologicalSimplification,
  removes features below persistence threshold, returns simplified field
  and count of features removed
- segment_morse_smale(field): TTK MorseSmaleComplex, returns cell
  segmentation with ascending/descending manifolds and separatrices

**4.2 Use case: Feature identification and denoising**

Query: "What are the dominant features in this scalar field?"

Plan (ontology): compute persistence diagram → identify persistence gap →
simplify below threshold → extract critical points of simplified field

Execute:
1. compute_persistence("temperature") → returns 47 pairs, persistence range [0.001, 4.2]
2. Interpret identifies gap: "Clear persistence gap at 0.15. 38 pairs below (noise),
   9 pairs above (signal). Recommend simplification at threshold 0.15."
3. User approves → simplify_field("temperature", 0.15) → simplified field
4. critical_points on simplified field → 9 critical points (3 maxima, 2 minima, 4 saddles)

Interpret: "The scalar field has 9 significant features after removing 38 noise
features (persistence < 0.15). Three dominant maxima correspond to thermal plumes.
The two minima mark cold pools. Saddle network connects them."

Key: ontology knows that the first step for any topological question is persistence,
and that a gap in the persistence spectrum separates signal from noise. LLM alone
would not reliably know to look for a persistence gap before simplifying.

**4.3 Use case: Structural decomposition**

Query: "Show me the basin structure of this flow"

Plan (ontology): "basin structure" maps to Morse-Smale decomposition.
Requires: clean scalar field → simplify first → then segment.

Execute:
1. compute_persistence("velocity_magnitude") → identifies noise threshold
2. simplify_field at threshold → clean field
3. segment_morse_smale on simplified field → ascending/descending manifolds
4. Returns: cell count per segment, separatrix geometry, segment statistics

Interpret: "Morse-Smale decomposition reveals 4 ascending basins and 3 descending
basins. The largest ascending basin (62% of domain) corresponds to the freestream.
Two smaller basins mark the recirculation zones. Separatrices align with shear layers."

Key: ontology encodes the prerequisite chain (simplify before segmenting).
Without this, LLM might run Morse-Smale on noisy data → thousands of spurious cells.

**4.4 Use case: Comparative topology**

Query: "How does the feature structure change between time steps 50 and 100?"

Plan (ontology): "change in feature structure" maps to persistence diagram
comparison via bottleneck distance + visual overlay.

Execute:
1. compute_persistence on both timesteps
2. bottleneck_distance between the two diagrams → scalar similarity measure
3. Overlay persistence diagrams → visual comparison
4. critical_points on both → track which features appear/disappear/move

Interpret: "Bottleneck distance = 0.34 (moderate change). Two new maxima appeared
near the trailing edge (persistence 0.8 and 0.6) — these correspond to vortex
shedding onset. The dominant upstream maximum persisted but shifted 12% in value.
Three low-persistence features appeared and disappeared (transient noise)."

Key: this is the topological equivalent of CFD's cross-quantity synthesis.
Multiple tools orchestrated, results synthesized into a physical narrative.
Ontology tells the planner that bottleneck distance is the right comparison
metric and that persistence diagram overlay provides visual confirmation.

---

### 5. Cross-Domain Analysis

**5.1 What transfers, what doesn't**

Transfers directly (domain-independent):
- Plan-Execute-Interpret architecture and loop
- MCP protocol layer and tool discovery
- Ontology schema (phenomena → quantities → tools → follow-ups)
- Client-server deployment (same pvserver instance)
- Tool design principles (structured returns, safe pipeline management)
- trame UI and LLM integration

Requires domain-specific work:
- Ontology content (CFD phenomena ≠ topological phenomena)
- Tool wrappers (ParaView filters ≠ TTK filters, though both are PV plugins)
- Interpretation grounding (physics ≠ topological concepts)
- Evaluation criteria (physical correctness ≠ topological correctness)

**5.2 Combined workflows: TTK on CFD data**

The two domains can compose. TTK tools applied to CFD scalar fields:
- "Find the dominant topological features in the pressure field"
  → persistence diagram on Cp → identifies shocks, stagnation, separation as
    high-persistence features → Morse-Smale segments the flow into distinct regions
- The CFD ontology tells the planner *what* to look for (separation).
  The TTK ontology tells it *how* to find structure (persistence + segmentation).
- Single pvserver session, both tool sets available, planner selects from either.

**5.3 Marginal cost of adding a domain**

TTK domain required:
- Ontology: ~25 entries, authored by domain expert in JSON
- MCP tools: ~8 wrappers around existing TTK ParaView filters
- Lines of Python: [measure this]
- Time: [measure this]
- No changes to architecture, protocol, deployment, or UI

---

### 6. Why Not LLM-Generated Scripts

*Design rationale. Reference Zhao et al. 2026 as representative baseline.*

**Brittleness:** Scripts depend on exact array names, filter params, pipeline topology.
Dynamic field resolution handles solver-specific naming at runtime.

**No reasoning feedback:** Scripts produce renders, not structured data. No mechanism
for interpretation phase to reason quantitatively about results.

**Unverifiable correctness:** Named tool operations have declared intent and legible
provenance. A 40-line script obscures the reasoning.

**Wrong role for the LLM:** Zhao et al.'s error taxonomy confirms this — their hardest
errors (wrong intention/logic) are exactly what happens when the LLM writes code
instead of reasoning about domain questions. Our tool abstraction eliminates API
hallucination entirely (no APIs to hallucinate) and ontology-constrained planning
addresses wrong-strategy errors.

---

### 7. Evaluation

**7.1 CFD: Plan correctness and interpretation accuracy**
- 10 canonical external aero scenarios with known features
- Ground truth: expert-defined analysis chains and conclusions
- Metrics: tool selection precision/recall, conclusion correctness
- Ablation: with ontology vs without

**7.2 TTK: Plan correctness**
- 6 scalar field analysis scenarios with known topological structure
- Ground truth: expert-defined analysis chains (persistence → simplify → segment)
- Metrics: correct tool ordering, appropriate threshold selection, feature count
- Ablation: with ontology vs without (does LLM know to simplify before segmenting?)

**7.3 Cross-domain: Script generation comparison**
- Same scenarios given to RAG + script generation baseline
- Metrics: executability, correct analysis selection, silent wrong results
- Hypothesis: tool orchestration produces fewer silent failures because
  tools are validated; scripts can execute but produce wrong analysis

**7.4 Robustness**
- CFD: same query on FUN3D vs OpenFOAM outputs
- TTK: same query on structured vs unstructured grids
- Metric: identical conclusions without user intervention

**7.5 Iterative reasoning**
- CFD: multi-step diagnostic chains (how many steps, do they match expert?)
- TTK: simplification → re-analysis chains (does system iterate correctly?)
- With vs without knowledge graph causal chains

**7.6 Scalability**
- pvserver on compute node, browser on laptop
- Progressive mesh sizes (1M → 100M cells)
- Client memory constant regardless of dataset size

---

### 8. Discussion

**8.1 The pattern works because...**
- Scientific analysis is procedural + domain-constrained → ontology captures this
- LLMs are good at intent + explanation → right role
- Tools are deterministic + validated → right role
- MCP standardizes the interface → swappable domains on same infrastructure

**8.2 What the ontology buys — and its limits**
- Small ontology (25-30 entries per domain) has outsized impact on plan quality
- But coverage is bounded — novel phenomena fall outside the ontology
- Ontology authoring is expert effort, not automated
- Open question: semi-automatic expansion from literature or tool documentation

**8.3 Comparison to Zhao et al. 2026**
- Their approach: RAG + code generation. Metric: correction cost (lines of diff).
- Our approach: ontology + tool orchestration. Metric: domain correctness.
- Their error taxonomy supports our design: wrong-strategy errors persist with RAG.
- Complementary: their RAG techniques could augment our tool discovery.
- Key difference: their system generates code for a single task. Ours maintains
  a persistent session with iterative reasoning across multiple analysis steps.

**8.4 Limitations**
- Ontology coverage bounds what the system can reason about
- LLM interpretation can still be overconfident or subtly wrong
- TTK integration is proof-of-concept — not as deeply exercised as CFD
- Knowledge graph causal chains are manually authored
- Evaluation scenarios are canonical/controlled, not production workflows

---

### 9. Future Work

- In-situ analysis via Catalyst Live (same MCP tools on live simulation data)
- ADIOS/Fides in-transit for non-Catalyst solvers (same tool layer, different data path)
- Additional domains: medical imaging (3D Slicer), materials (tomviz), climate
  — each requires only ontology + tool wrappers on existing toolkits
- Multi-domain composition: TTK topology on CFD fields, structural analysis on
  CFD-predicted loads — cross-domain ontology linking
- Semi-automatic ontology expansion from documentation and literature
- Uncertainty-aware interpretation: when should the system express low confidence?

---

### 10. Conclusion

The central claim: for scientific analysis, the right architecture separates
intent interpretation (LLM) from execution (domain tools) from explanation (LLM),
connected by a standard protocol (MCP) and grounded by domain knowledge (ontology).

This is not a tool looking for a problem. CFD engineers spend significant time
translating engineering questions into analysis procedures. Topological data
analysts must configure multi-step pipelines where ordering and parameterization
critically affect results. The pattern is the same: map a high-level question
through domain expertise to a concrete multi-step procedure, execute it correctly,
and interpret the results.

Script generation puts all of this burden on the LLM. Our architecture puts
each burden where it belongs. Demonstrated on the same ParaView infrastructure
across two domains with different ontologies and tools, comparable improvements
over script generation, and seamless scalability via client-server deployment.

---

### Meta

**Target venues:**
- IEEE VIS / TVCG (visualization audience, both domains fit naturally)
- SC / Supercomputing (scalability + in-situ angle, HPC audience)
- AIAA SciTech (if CFD-heavy version, aero audience)

**Why TTK is the right second domain:**
- Already a ParaView plugin — zero new backend infrastructure
- Same pvserver instance runs both CFD and TTK tools
- Topological analysis has the same knowledge-gap problem: powerful tools,
  expert knowledge required to configure and interpret
- Multi-step prerequisite chains (simplify before segment) parallel CFD
  (extract surface before compute wall shear)
- Combined workflows (TTK on CFD scalar fields) show domain composition
- Kitware maintains TTK — natural collaboration
