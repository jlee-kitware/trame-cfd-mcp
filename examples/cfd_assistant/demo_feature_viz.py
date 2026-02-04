#!/usr/bin/env python
"""
End-to-end demo: User asks about flow features, system analyzes and visualizes.

This demonstrates the full value proposition:
1. User asks: "show me the vortices" (or stagnation, wake, etc.)
2. Analysis layer finds features and determines visualization parameters
3. Prompt sent to trame-llm with resolved values
4. ParaView renders the visualization
"""

import sys
sys.path.insert(0, "/Users/jeff.lee/gitsync/paraview_llm/src")

from paraview import simple

# Initialize ParaView
print("="*70)
print("CFD Assistant - Feature-Driven Visualization")
print("="*70)

# Load test data
print("\n[1] Loading CFD data...")
reader = simple.OpenDataFile("test.vtm")
simple.UpdatePipeline()
simple.Show(reader)
simple.ResetCamera()
print("    ✓ Loaded flow field around cylinder")

# Initialize analysis
print("\n[2] Initializing flow analyzer...")
from paraview_llm.analysis import FlowAnalyzer
analyzer = FlowAnalyzer(reader)
print("    ✓ Analyzer ready")

# Initialize trame-llm
print("\n[3] Initializing visualization engine (trame-llm)...")
try:
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    from trame_llm.paraview import ParaViewMCP
    from trame_llm.core import LLMClient
    
    class MinimalApp:
        def update(self):
            simple.Render()
        def reset_camera(self):
            simple.ResetCamera()
            simple.Render()
        class ctrl:
            @staticmethod
            def on_active_proxy_change():
                return None
            @staticmethod
            def on_data_change():
                return None
            on_active_proxy_change.exists = lambda: False
            on_data_change.exists = lambda: False
    
    mcp = ParaViewMCP(MinimalApp())
    llm_client = LLMClient(max_iteractions=15)
    llm_client.register_mcp(mcp)
    
    # Initialize
    import asyncio
    async def init_llm():
        await llm_client.initialize()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_llm())
    
    # Progress handler
    def progress(msg_type, msg):
        if msg_type.value in ["mcp", "mcp-selection"]:
            print(f"        {msg}")
    llm_client.set_progress_handler(progress)
    
    print(f"    ✓ {len(llm_client.tools)} visualization tools available")
    HAS_TRAME_LLM = True
except Exception as e:
    print(f"    ⚠ trame-llm not available: {e}")
    HAS_TRAME_LLM = False


def handle_query(query: str):
    """
    Handle a user query about flow features.
    
    Maps natural language to:
    1. Feature detection (analysis)
    2. Visualization prompt (trame-llm)
    """
    print(f"\n{'='*70}")
    print(f"User: \"{query}\"")
    print("="*70)
    
    query_lower = query.lower()
    
    # Determine what feature the user wants
    if "vortex" in query_lower or "vortices" in query_lower or "rotation" in query_lower:
        feature_type = "vortices"
    elif "stagnation" in query_lower or "streamline" in query_lower:
        feature_type = "stagnation"
    elif "wake" in query_lower or "deficit" in query_lower:
        feature_type = "wake"
    elif "pressure" in query_lower:
        feature_type = "pressure"
    elif "separation" in query_lower or "recirculation" in query_lower:
        feature_type = "separation"
    else:
        feature_type = "overview"
    
    print(f"\n[Analysis] Detected intent: {feature_type}")
    
    # Run appropriate analysis
    if feature_type == "vortices":
        print("    Computing Q-criterion for vortex detection...")
        result = analyzer.find_vortices()
        
        if "error" in result:
            print(f"    Error: {result['error']}")
            return
        
        isovalues = result["recommended_isovalues"]
        center = result.get("vortex_region_center")
        
        print(f"    Q range: [{result['Q_range'][0]:.2f}, {result['Q_range'][1]:.2f}]")
        print(f"    Recommended isovalues: {[f'{v:.1f}' for v in isovalues]}")
        if center:
            print(f"    Vortex region center: [{center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f}]")
        
        # Build visualization prompt
        # Use a middle isovalue for clearer visualization
        isovalue = isovalues[1]  # 75th percentile
        prompt = f"""First, compute Q-criterion on the data using the Calculator filter with the formula for Q-criterion.
Then create a Contour filter on the Q-criterion result with isovalue {isovalue:.2f}.
Color the isosurface by velocity magnitude.
Hide the original data.
Reset the camera to show the vortex structures."""

    elif feature_type == "stagnation":
        print("    Finding stagnation points...")
        result = analyzer.find_stagnation_points()
        
        if "error" in result:
            print(f"    Error: {result['error']}")
            return
        
        location = result["location"]
        vel_mag = result["velocity_magnitude"]
        
        print(f"    Stagnation point: [{location[0]:.3f}, {location[1]:.3f}, {location[2]:.3f}]")
        print(f"    Velocity magnitude: {vel_mag:.6f}")
        
        # Build visualization prompt
        prompt = f"""Create streamlines seeded at [{location[0]:.3f}, {location[1]:.3f}, {location[2]:.3f}] with a point cloud of radius 0.3 and 15 points.
Integrate in both directions.
Color by velocity magnitude.
Hide the original data.
Reset the camera."""

    elif feature_type == "wake":
        print("    Finding wake region...")
        result = analyzer.find_wake_region()
        
        if "error" in result:
            print(f"    Error: {result['error']}")
            return
        
        center = result["center"]
        freestream = result["freestream_velocity"]
        
        print(f"    Wake center: [{center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f}]")
        print(f"    Freestream velocity: {freestream:.3f}")
        
        # Build visualization prompt - slice through wake
        prompt = f"""Create a Slice filter at origin [{center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f}] with normal [0, 0, 1].
Color the slice by velocity magnitude.
Hide the original data.
Reset the camera."""

    elif feature_type == "pressure":
        print("    Finding pressure extrema...")
        result = analyzer.find_pressure_extrema()
        
        if "error" in result:
            print(f"    Error: {result['error']}")
            return
        
        p_min = result["minimum"]
        p_max = result["maximum"]
        
        print(f"    Min pressure: {p_min['value']:.4f} at {p_min['location']}")
        print(f"    Max pressure: {p_max['value']:.4f} at {p_max['location']}")
        
        # Build visualization prompt
        prompt = f"""Color the data by pressure.
Add a Glyph filter at the minimum pressure location [{p_min['location'][0]:.3f}, {p_min['location'][1]:.3f}, {p_min['location'][2]:.3f}].
Reset the camera."""

    else:
        # Overview - show streamlines at stagnation
        print("    Running full flow analysis...")
        result = analyzer.analyze()
        
        stag = result.get("stagnation_point", {})
        if "error" not in stag:
            location = stag["location"]
            print(f"    Stagnation point: {location}")
            prompt = f"""Create streamlines seeded at [{location[0]:.3f}, {location[1]:.3f}, {location[2]:.3f}].
Color by velocity.
Reset the camera."""
        else:
            prompt = "Color the data by velocity magnitude. Reset the camera."
    
    # Execute visualization via trame-llm
    if HAS_TRAME_LLM:
        print(f"\n[Visualization] Sending to trame-llm...")
        print(f"    Prompt: {prompt[:80]}...")
        
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(llm_client.process_prompt(prompt))
            print("    ✓ Visualization complete")
        except Exception as e:
            print(f"    Error: {e}")
    else:
        print(f"\n[Visualization] Would send prompt:")
        print(f"    {prompt}")


# Demo: Handle different user queries
print("\n" + "="*70)
print("DEMO: Feature-driven visualization queries")
print("="*70)

# Query 1: Show stagnation/streamlines
handle_query("show me streamlines through the flow")

# Save screenshot
print("\n[Screenshot] Saving result...")
simple.SaveScreenshot("output/demo_streamlines.png", simple.GetActiveView(), 
                      ImageResolution=[800, 600])
print("    ✓ Saved to output/demo_streamlines.png")

# Cleanup
analyzer.cleanup()
print("\n" + "="*70)
print("Demo complete!")
print("="*70)
