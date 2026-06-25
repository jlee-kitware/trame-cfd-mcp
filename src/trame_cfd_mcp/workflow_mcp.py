"""
Workflow-based MCP for CFD visualization.

Exposes high-level workflow tools plus refinement tools for tweaking results.
LLM does intent matching, workflows execute deterministically.
Ontology provides domain knowledge for explanations.
"""

import json
import os
from paraview import simple
from .cfd_analysis import CFDAnalysis
from .workflows import CFDWorkflows
from .topology_analysis import TopologyAnalysis
from .topology_workflows import TopologyWorkflows


# Load ontology at module level
_ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), "ontology.json")
with open(_ONTOLOGY_PATH) as f:
    CFD_ONTOLOGY = json.load(f)

# Merge the topology (TTK) domain ontology so its hints resolve in the same
# validated dict. Authored as a separate file (separate domain), unified at load.
_TOPOLOGY_ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), "topology_ontology.json")
try:
    with open(_TOPOLOGY_ONTOLOGY_PATH) as f:
        _TOPOLOGY_ONTOLOGY = json.load(f)
    for _k, _v in _TOPOLOGY_ONTOLOGY.items():
        if _k in ("version", "domain"):
            continue
        if isinstance(_v, dict) and isinstance(CFD_ONTOLOGY.get(_k), dict):
            CFD_ONTOLOGY[_k].update(_v)   # merge sub-keys, don't clobber CFD content
        else:
            CFD_ONTOLOGY[_k] = _v
except FileNotFoundError:
    pass


class WorkflowMCP:
    """MCP with workflow tools and refinement capabilities."""
    
    def __init__(self, base_mcp, app=None):
        """
        Initialize workflow MCP.
        
        Args:
            base_mcp: ParaViewMCP instance from trame-llm
            app: Optional trame app for rendering charts
        """
        self._base_mcp = base_mcp
        self._app = app
        self._analysis = CFDAnalysis()
        self._workflows = CFDWorkflows(
            self._analysis, 
            on_pipeline_changed=self._base_mcp.pipeline_changed,
            app=app,
            ontology=CFD_ONTOLOGY,
        )
        self._ontology = CFD_ONTOLOGY
        self._topology = TopologyAnalysis()
        self._topology_workflows = TopologyWorkflows(
            self._workflows, self._topology, app=app,
        )
        print(f"[WorkflowMCP] Initialized with app={app is not None}, has_render={hasattr(app, 'render_analysis_chart') if app else False}")
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration (property for compatibility with LLMClient)."""
        return self.get_mcp()
    
    def list_data(self) -> dict:
        """
        List all loaded data sources and filters in the pipeline.
        
        Call this FIRST to see what data is available before analysis.
        
        Returns:
            Dict with:
            - readers: List of data sources (files loaded)
            - filters: List of filters created
            - active_source: Currently active proxy
        """
        result = self._analysis.list_data()
        result["tip"] = "Use proxy names from this list with refinement tools like update_representation()"
        return result
    
    def save_screenshot(
        self,
        filename: str,
        width: int = 1024,
        height: int = 768
    ) -> dict:
        """
        Save screenshot of the current view to a file.
        
        Args:
            filename: Output filename (e.g., "output/result.png")
            width: Image width in pixels (default: 1024)
            height: Image height in pixels (default: 768)
            
        Returns:
            Dict with filename and status
        """
        result = self._analysis.save_screenshot(filename, width, height)
        if "error" not in result:
            result["tip"] = "Screenshot saved. Use set_view() to change camera angle before saving another."
        return result
    
    def save_all_charts(
        self,
        prefix: str = "output/chart",
        width: int = 800,
        height: int = 600
    ) -> dict:
        """
        Save all pending chart views to files.
        
        Charts are created by workflows like show_boundary_layer, show_histogram,
        show_forces, etc. This saves all of them at once with sequential numbering.
        
        Args:
            prefix: Output filename prefix (e.g., "output/bl" -> bl_0.png, bl_1.png, ...)
            width: Image width in pixels (default: 800)
            height: Image height in pixels (default: 600)
            
        Returns:
            Dict with list of saved filenames and count
        """
        result = self._analysis.save_all_charts(prefix, width, height)
        if result.get("count", 0) > 0:
            result["tip"] = f"Saved {result['count']} charts. Charts are cleared after saving."
        return result
    
    def set_view(self, direction: str = "+x") -> dict:
        """
        Set camera view direction.
        
        Args:
            direction: "+x", "-x", "+y", "-y", "+z", "-z", or "iso"
            
        Returns:
            Dict with view info
            
        Tip:
            Use before save_screenshot() to capture different angles.
        """
        result = self._analysis.set_view(direction)
        if "error" not in result:
            result["tip"] = "Camera set. Call save_screenshot() to capture this view."
        return result
    
    def update_display_property(
        self,
        property_name: str,
        value,
        proxy_name: str = None
    ) -> dict:
        """
        Set display/representation property like opacity, interpolation, or line width.
        
        These are visual properties on how the data is displayed, NOT filter properties.
        Use list_properties() for filter properties, this is for display properties.
        
        Args:
            property_name: One of:
                - "Opacity": 0.0 (transparent) to 1.0 (opaque)
                - "Interpolation": "Flat", "Gouraud", or "PBR"
                - "LineWidth": line thickness (default 1.0)
                - "PointSize": point size for Points representation (default 2.0)
                - "Metallic": 0.0-1.0 for PBR materials
                - "Roughness": 0.0-1.0 for PBR materials
            value: The value to set (number or string depending on property)
            proxy_name: Proxy to modify, or active source if None
            
        Returns:
            Dict with proxy name, property, and value set
        """
        # Map common names to ParaView property names
        property_map = {
            "opacity": "Opacity",
            "linewidth": "LineWidth",
            "line_width": "LineWidth",
            "pointsize": "PointSize",
            "point_size": "PointSize",
            "interpolation": "Interpolation",
            "metallic": "Metallic",
            "roughness": "Roughness",
            "pbr": "Interpolation",  # Shortcut: "pbr" -> set Interpolation to PBR
        }
        
        # Normalize property name
        prop_key = property_name.lower().replace(" ", "")
        actual_prop = property_map.get(prop_key, property_name)
        
        # Handle "pbr" shortcut - set value to "PBR" if using the shortcut
        if prop_key == "pbr":
            value = "PBR"
        
        # Get proxy
        if proxy_name:
            proxy = simple.FindSource(proxy_name)
        else:
            proxy = simple.GetActiveSource()
        
        if proxy is None:
            return {"error": f"Could not find proxy '{proxy_name}'" if proxy_name else "No active source"}
        
        # Get representation
        view = simple.GetActiveView()
        rep = simple.GetRepresentation(proxy, view)
        
        if rep is None:
            return {"error": f"No representation found for '{proxy_name or 'active source'}'"}
        
        # Check if property exists on representation
        if not hasattr(rep, actual_prop):
            available = [p for p in dir(rep) if not p.startswith('_') and p[0].isupper()]
            return {
                "error": f"Property '{actual_prop}' not found on representation",
                "hint": "Common display properties: Opacity, LineWidth, PointSize",
                "tip": "Use update_representation() to change type (Wireframe, Surface, etc.)"
            }
        
        try:
            setattr(rep, actual_prop, value)
            simple.Render(view)
            
            # Get proxy name for return
            name = proxy_name
            if not name:
                for n, p in simple.GetSources().items():
                    if p == proxy:
                        name = n[0]
                        break
            
            return {
                "name": name,
                "property": actual_prop,
                "value": value,
                "tip": "Display property set. Opacity=0 is invisible, Opacity=1 is fully opaque."
            }
        except Exception as e:
            return {"error": str(e)}
    
    def save_state(self, filename: str) -> dict:
        """
        Save ParaView state for reproducibility.
        
        Saves complete pipeline state that can be loaded in ParaView GUI
        or via LoadState() in Python.
        
        Args:
            filename: Output filename (.pvsm for XML, .py for Python script)
            
        Returns:
            Dict with filename and status
        """
        simple.SaveState(filename)
        return {
            "status": "saved",
            "filename": filename,
            "tip": "Load with File > Load State in ParaView GUI, or simple.LoadState() in Python"
        }
    
    def update_list_property(self, property_name: str, property_value=None, proxy_name: str = None) -> dict:
        """Update array property and refresh pipeline browser."""
        if property_value is None:
            return {"error": "property_value is required"}
        if not isinstance(property_value, list):
            property_value = [float(property_value)]
        result = self._base_mcp.update_list_property(property_name=property_name,
                                                      property_value=property_value,
                                                      proxy_name=proxy_name)
        if "error" not in result:
            self._notify_pipeline_and_panel()
        return result

    def update_representation(self, representation_type: str, proxy_name: str = None) -> dict:
        """Update representation and refresh pipeline browser."""
        result = self._base_mcp.update_representation(representation_type=representation_type,
                                                       proxy_name=proxy_name)
        if "error" not in result:
            self._notify_pipeline_and_panel()
        return result

    def update_color(self, proxy_name: str = None, field_name: str = None) -> dict:
        """Update coloring and refresh pipeline browser."""
        result = self._base_mcp.update_color(proxy_name=proxy_name, field_name=field_name)
        if "error" not in result:
            self._notify_pipeline_and_panel()
        return result

    def _notify_pipeline_and_panel(self):
        """Flush proxy state and force property panel refresh."""
        active = simple.GetActiveSource()
        if active is not None:
            simple.UpdatePipeline(proxy=active)
        self._base_mcp.pipeline_changed()
        ctrl = self._base_mcp.app.ctrl
        state = self._base_mcp.app.state
        # Directly write ptc_yaml_props inside a state context so it flushes
        # to the client. This replicates ProxyEditor._reset() which calls
        # active_widget.update_ui(proxy) → state.ptc_yaml_props = "...".
        # Using `with state:` ensures flush() is called on exit regardless
        # of thread context.
        if active is not None:
            try:
                lines = []
                for prop_name in active.ListProperties():
                    if prop_name.endswith("Info"):
                        continue
                    if not hasattr(active, prop_name):
                        continue
                    entry = f"{prop_name}: {getattr(active, prop_name)}"
                    if ": <" in entry:
                        continue
                    lines.append(entry)
                with state:
                    state.ptc_yaml_props = ""  # clear first so the new value is always dirty
                    state.ptc_yaml_props = "\n".join(lines)
            except Exception:
                pass
        if ctrl.on_active_proxy_change.exists():
            ctrl.on_active_proxy_change()
        with state:
            pass  # flush any remaining pending state

    def get_ontology(self) -> dict:
        """
        Get CFD domain knowledge for interpreting results.
        
        Returns ontology containing:
        - flow_features: What each visualization type means
        - causal_relationships: What causes drag/lift changes
        - analysis_recommendations: Which tools to use for different questions
        
        Use this to explain visualizations and answer "why" questions.
        """
        return self._ontology
    
    def set_filter_property(self, proxy_name: str, properties: dict = None) -> dict:
        """
        Modify properties of an existing filter.
        
        Use this to adjust filter parameters without recreating.
        
        Args:
            proxy_name: Name of the filter to modify
            properties: Dict of property name-value pairs to set (REQUIRED)
            
        Examples:
            set_filter_property("Streamlines_wake", {"SeedType.NumberOfPoints": 50})
            set_filter_property("Contour1", {"Isosurfaces": [0.5, 1.0, 1.5]})
            set_filter_property("Slice1", {"SliceType.Origin": [0,0,0]})
            
        Returns:
            Dict with status and updated properties
        """
        if properties is None or not properties:
            return {"error": "properties argument is required. Example: set_filter_property('Streamlines_wake', {'SeedType.NumberOfPoints': 50})"}
        try:
            proxy = simple.FindSource(proxy_name)
            if proxy is None:
                return {"error": f"Filter '{proxy_name}' not found"}
            
            updated = {}
            errors = []
            
            for prop_name, value in properties.items():
                try:
                    # Handle nested properties like SeedType.NumberOfPoints
                    if "." in prop_name:
                        parts = prop_name.split(".")
                        obj = proxy
                        for part in parts[:-1]:
                            obj = getattr(obj, part)
                        setattr(obj, parts[-1], value)
                    else:
                        setattr(proxy, prop_name, value)
                    updated[prop_name] = value
                except Exception as e:
                    errors.append(f"{prop_name}: {e}")
            
            # Update pipeline
            simple.UpdatePipeline(proxy=proxy)
            simple.Render()
            self._base_mcp.pipeline_changed()
            
            result = {
                "status": "modified",
                "proxy_name": proxy_name,
                "updated": updated,
            }
            if errors:
                result["errors"] = errors
            
            return result
        except Exception as e:
            return {"error": str(e)}
    
    def get_filter_properties(self, proxy_name: str) -> dict:
        """
        Get current properties of a filter.
        
        Use this to inspect filter settings before modifying.
        
        Args:
            proxy_name: Name of the filter
            
        Returns:
            Dict with filter type and properties
        """
        try:
            proxy = simple.FindSource(proxy_name)
            if proxy is None:
                return {"error": f"Filter '{proxy_name}' not found"}
            
            def get_prop_value(prop):
                """Extract serializable value from a property."""
                data = None
                
                # Try GetData first
                if hasattr(prop, 'GetData'):
                    try:
                        data = prop.GetData()
                    except:
                        pass
                
                # If that didn't work or returned non-serializable, try other methods
                if data is None or hasattr(data, 'GetClassName'):
                    # Try to get elements for vector/array properties
                    if hasattr(prop, 'GetNumberOfElements'):
                        n = prop.GetNumberOfElements()
                        if n > 0 and n < 100:  # Limit to reasonable size
                            try:
                                data = [prop.GetElement(i) for i in range(n)]
                                if len(data) == 1:
                                    data = data[0]
                            except:
                                pass
                
                # Convert to Python types if needed
                if data is not None:
                    if hasattr(data, '__iter__') and not isinstance(data, (str, list)):
                        try:
                            data = list(data)
                        except:
                            data = str(data)
                    # Skip if still not serializable
                    if not isinstance(data, (str, int, float, bool, list, type(None))):
                        data = str(data)
                
                return data
            
            props = {}
            # Get commonly useful properties
            prop_names = proxy.ListProperties()
            for name in prop_names:
                try:
                    prop = proxy.GetProperty(name)
                    if prop is not None:
                        data = get_prop_value(prop)
                        if data is not None:
                            props[name] = data
                except:
                    pass
            
            # For StreamTracer, also get SeedType properties
            if proxy.GetXMLName() == 'StreamTracer' and hasattr(proxy, 'SeedType'):
                try:
                    seed = proxy.SeedType
                    seed_props = {}
                    for attr in ['Center', 'Radius', 'NumberOfPoints', 'Point1', 'Point2', 'Resolution']:
                        if hasattr(seed, attr):
                            try:
                                val = getattr(seed, attr)
                                # Convert VectorProperty or other ParaView types
                                if hasattr(val, 'GetData'):
                                    val = val.GetData()
                                if hasattr(val, '__iter__') and not isinstance(val, str):
                                    val = [float(x) if isinstance(x, (int, float)) else str(x) for x in val]
                                elif isinstance(val, (int, float)):
                                    val = float(val) if isinstance(val, float) else int(val)
                                else:
                                    val = str(val) if val is not None else None
                                if val is not None:
                                    seed_props[attr] = val
                            except:
                                pass
                    if seed_props:
                        props['SeedType_properties'] = seed_props
                        props['SeedType_type'] = str(type(seed).__name__)
                except:
                    pass
            
            # Final pass to ensure all values are JSON serializable
            clean_props = {}
            for k, v in props.items():
                try:
                    import json
                    json.dumps(v)  # Test if serializable
                    clean_props[k] = v
                except:
                    clean_props[k] = str(v)  # Convert to string if not
            
            return {
                "proxy_name": proxy_name,
                "type": proxy.GetXMLName(),
                "properties": clean_props,
            }
        except Exception as e:
            return {"error": str(e)}
    
    def delete_filter(self, proxy_name: str) -> dict:
        """
        Delete a filter from the pipeline.
        
        Checks for downstream consumers before deletion — if other filters
        depend on this one, deletion is refused.
        
        Use this to clean up unwanted visualizations and free resources.
        
        Args:
            proxy_name: Name of the filter to delete (from list_data)
            
        Returns:
            Dict with status, or error if proxy has consumers
        """
        return self._base_mcp.delete_proxy(proxy_name)
    
    def clear_all_filters(self) -> dict:
        """
        Delete all filters, keeping only the original data sources.
        
        Deletes in leaf-first order using consumer checks to avoid
        breaking the pipeline DAG.
        
        Use this to reset the pipeline and free OpenGL resources.
        
        Returns:
            Dict with list of deleted filters
        """
        deleted = []
        errors = []
        try:
            # Iteratively delete leaf nodes until only readers remain.
            # Each pass removes proxies with no consumers; repeat since
            # deleting a leaf may make its parent a new leaf.
            max_passes = 50  # Guard against infinite loops
            for _ in range(max_passes):
                sources = dict(simple.GetSources())
                deleted_this_pass = False
                
                for name_tuple, proxy in list(sources.items()):
                    info = self._base_mcp.proxy_info(name_tuple[0])
                    if "error" in info:
                        continue
                    if info["is_reader"]:
                        continue
                    if info["can_delete"]:
                        result = self._base_mcp.delete_proxy(name_tuple[0])
                        if "error" not in result:
                            deleted.append(name_tuple[0])
                            deleted_this_pass = True
                        else:
                            errors.append(f"{name_tuple[0]}: {result['error']}")
                
                if not deleted_this_pass:
                    break
            
            self._base_mcp.pipeline_changed()
            
            # Report remaining proxies
            remaining = [
                n[0] for n in simple.GetSources().keys()
            ]
            
            result = {
                "status": "cleared",
                "deleted": deleted,
                "remaining": remaining,
            }
            if errors:
                result["errors"] = errors
            return result
        except Exception as e:
            return {"error": str(e), "deleted_before_error": deleted}
    
    def hide_all_scalar_bars(self) -> dict:
        """
        Hide all scalar bars (color legends) to reduce OpenGL texture usage.
        
        Use this if you see texture warnings or rendering issues.
        
        Returns:
            Dict with count of hidden bars
        """
        view = simple.GetActiveView()
        count = 0
        
        for name, proxy in simple.GetSources().items():
            rep = simple.GetRepresentation(proxy=proxy, view=view)
            if rep:
                try:
                    rep.SetScalarBarVisibility(view, False)
                    count += 1
                except:
                    pass
        
        simple.Render(view)
        return {
            "status": "hidden",
            "count": count,
            "tip": "Scalar bars hidden. Use update_color to show a specific one."
        }
    
    def get_mcp(self) -> dict:
        """Return MCP declaration with workflow and refinement tools."""
        return {
            "name": "cfd_visualization",
            "instructions": """
You are a CFD visualization and analysis assistant. You create visualizations AND explain what they mean.

ALWAYS call list_data() first to see what data is loaded.

== WORKFLOW PATTERN ==

1. Create visualization with show_* tools (they return proxy_name and parameters)
2. If a show_* tool FAILS, fall back to general filter creation tools (create, find_or_create) — do NOT present long error diagnostics or ask the user to troubleshoot
3. If user wants refinement, use the proxy_name with refinement tools
4. Use get_ontology() to get domain knowledge for explanations
5. Save with save_screenshot()

KEEP RESPONSES CONCISE.  Never present numbered option lists when a tool fails.
Try the fallback tools first, and only ask the user if you truly cannot proceed.

== VISUALIZATION TOOLS (use these first) ==

- show_vortices(method="q_criterion") - Create vortex structure visualization (initial creation only —
  to adjust an existing vortex visualization use update_list_property, not show_vortices again)
- show_streamlines() - Show flow streamlines in wake region  
- show_slice(location="wake") - Show slice through data
- show_histogram(field="p") - Show field distribution chart
- show_forces() - Show force distribution chart
- show_boundary_layer(x_location=0.5) - Show boundary layer profile
- show_flow_topology() - Show vortex core lines

== TOPOLOGY TOOLS (TTK; for scalar-field topology, any domain) ==

- show_persistence_diagram(field) - Birth/death pairs; reveals the signal-vs-noise gap
- show_critical_points(field) - Minima, saddles, maxima (colored by CriticalType)
- show_morse_smale(field) - Separatrix skeleton + critical points (structural decomposition)
- show_simplified(field, persistence_threshold) - Denoise by cancelling low-persistence pairs

  Typical chain for "find the significant features": show_persistence_diagram to see the
  gap, then show_simplified with a threshold in the gap, then show_critical_points.

== REFINEMENT TOOLS (use after show_* to tweak) ==

After a workflow runs, it returns proxy_name and parameters. Use these to refine:

- update_representation(representation_type, proxy_name) 
  → Change to "Wireframe", "Surface", "Points", "Surface With Edges"
  
- update_color(proxy_name, field_name) 
  → Change coloring to different field (e.g., "pressure", "Velocity")
  
- update_list_property(property_name, property_value, proxy_name)
  → Adjust thresholds: update_list_property("Isosurfaces", [new_value], proxy_name)
  → property_value MUST be a list, e.g. [14.03] not 14.03
  → Lower threshold = more structures, higher = fewer
  
- update_display_property(property_name, value, proxy_name)
  → Set Opacity (0.0=transparent, 1.0=opaque), LineWidth, PointSize
  → These are DISPLAY properties, not filter properties
  
- show_or_hide(action, proxy_name)
  → action="hide" or "show" to toggle visibility
  
- list_properties(proxy_name)
  → See all adjustable properties on a filter

== REFINEMENT EXAMPLES ==

After show_vortices() creates proxy "Vortices_q_criterion" with threshold=28.0:
- "Show more structures" (lower threshold) → update_list_property("Isosurfaces", [14.0], "Vortices_q_criterion")
- "Show fewer structures" (higher threshold) → update_list_property("Isosurfaces", [56.0], "Vortices_q_criterion")
- "Make it wireframe" → update_representation("Wireframe", "Vortices_q_criterion")
- "Color by pressure" → update_color("Vortices_q_criterion", "p")
- "Make semi-transparent" → update_display_property("Opacity", 0.5, "Vortices_q_criterion")

DO NOT call show_vortices again to adjust the threshold — that rebuilds the whole pipeline.
Use update_list_property("Isosurfaces", [new_threshold], proxy_name) to adjust existing results.

CRITICAL: When a user requests refinement, make the tool call immediately and silently.
Do NOT output tool call syntax as text. Just call the tool and describe what changed.

== DISCOVERY TOOLS ==

- list_data() - See loaded data sources and filters with proxy names
- get_fields() - List available fields with ranges
- analyze_data() - Get dataset info and recommendations
- list_properties(proxy_name) - See adjustable properties

== GENERAL FILTER CREATION ==

For operations not covered by show_* workflow tools, or when a show_* tool FAILS,
fall back to the base ParaView tools to accomplish the task directly:

- list_compatible_filters(proxy_name) - See which filters can be applied to a source
- create(proxy_name, input_proxy) - Create any ParaView filter by name (e.g., "Contour", "Slice", "Clip", "Glyph", "PlotOverLine", "StreamTracerWithCustomSource")
- find_or_create(proxy_name, input_proxy) - Reuse existing filter or create new one
- proxy_info(proxy_name) - Get detailed info about a filter or source

After creating a filter, use list_properties() and update_*_property() to configure it.

IMPORTANT: If a show_* workflow tool returns an error, DO NOT ask the user for diagnostic
information or present long lists of options.  Instead:
- For visualization tools (isosurfaces, slices, clips, streamlines): fall back to the
  general tools above to accomplish the same goal with create() + update_*_property().
- For analysis tools (boundary layer, forces, topology): these perform domain-specific
  computations that cannot be replicated with raw filters.  Report the failure briefly
  and suggest what might be wrong (e.g., "boundary layer analysis requires a Velocity field").
  Do NOT present long numbered option lists.

== EXPLANATION GUIDANCE ==

When explaining visualizations, use the ontology to provide:
- What the visualization method means (e.g., Q > 0 indicates vortex cores)
- What the specific results show (threshold value, location, etc.)
- Design relevance (what this means for aerodynamic performance)

Some workflow returns include an `ontology_hints` field — a short list of
dotted keys into the ontology. Hints are only provided for two cases where
reasoning from memory is unreliable:

1. Expert-level thresholds that use our conventions rather than textbook
   canon (e.g. shape-factor regime bands for BL flow state).
2. Causal relationships that point at other tools via the `evidence` field
   (e.g. "what to run next to confirm why drag increased").

When hints are present, call get_ontology() and look up the hinted keys
rather than answering from memory. When hints are absent, explain from
your own CFD knowledge — the workflow didn't flag anything as requiring
grounded interpretation.

ALWAYS relay the `tip` field verbatim to the user when it is present in
a tool result. Never say "see the provided tips" or "use the tips above"
— quote or paraphrase the actual tip text so the user can act on it
without having to ask what the tips are.

When the user asks to refine a visualization (e.g. "show more structures",
"make it wireframe", "color by pressure"), CALL THE TOOL — do not output
the tool call syntax as plain text. The tip field shows what tool calls
are available; when the user requests one of those refinements, execute
the corresponding tool immediately rather than printing the command.

When explaining a tool result, focus on the fields most relevant to the
user: `type`, `method`, `result` (threshold, field, range), and `tip`.
The `provenance` and `filter_chain` fields are internal bookkeeping —
do not summarize or repeat them in your response unless the user asks.
""",
            "tools": [
                # Discovery
                self.list_data,
                self._workflows.get_fields,
                self._workflows.analyze_data,
                
                # Visualization workflows
                self._workflows.show_vortices,
                self._workflows.show_streamlines,
                self._workflows.show_slice,
                self._workflows.show_schlieren,
                self._workflows.show_shadowgraph,
                self._workflows.show_histogram,
                self._workflows.show_forces,
                self._workflows.show_boundary_layer,
                self._workflows.show_boundary_layer_context,
                self._workflows.show_flow_topology,

                # Topology (TTK) domain workflows
                self._topology_workflows.show_persistence_diagram,
                self._topology_workflows.show_critical_points,
                self._topology_workflows.show_morse_smale,
                self._topology_workflows.show_simplified,
                
                # Refinement tools (from base MCP)
                self._base_mcp.reset_camera,
                self._base_mcp.focus_on,
                self.update_representation,
                self.update_color,
                self.update_list_property,
                self._base_mcp.show_or_hide,
                self._base_mcp.list_properties,
                self.update_display_property,
                
                # General filter creation (fallback for non-CFD workflows)
                self._base_mcp.create,
                self._base_mcp.find_or_create,
                self._base_mcp.list_compatible_filters,
                self._base_mcp.proxy_info,
                
                # Knowledge and utilities
                self.get_ontology,
                self.save_screenshot,
                self.save_state,
                self.set_view,
                self.set_filter_property,
                self.get_filter_properties,
                self.delete_filter,
                self.clear_all_filters,
                self.hide_all_scalar_bars,
            ],
            "resources": {},
        }
