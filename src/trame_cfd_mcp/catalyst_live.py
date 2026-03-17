"""
Catalyst Live integration for trame-cfd-mcp.

Provides MCP tools for connecting to and monitoring live Catalyst simulations,
including residual convergence tracking and data extraction.

Usage:
    from trame_cfd_mcp import CFDChatMCP
    
    base_mcp = ParaViewMCP(app)
    workflow_mcp = WorkflowMCP(base_mcp)
    chat_mcp = CFDChatMCP(workflow_mcp, llm_client, live_enabled=True)
    llm_client.register_mcp(chat_mcp)
"""

from paraview import simple


class CFDChatMCP:
    """MCP wrapper that adds cost tracking and optional live monitoring tools."""
    
    def __init__(self, workflow_mcp, llm_client, live_enabled=False, live_host="localhost", live_port=22222):
        self._workflow_mcp = workflow_mcp
        self._llm_client = llm_client
        self._live_enabled = live_enabled
        self._live_host = live_host
        self._live_port = live_port
        # Note: _app is a property that gets app from workflow_mcp._base_mcp.app
        self._live_link = None
        self._display_session = None
        self._monitor_source = None
        self._monitoring_active = False
        self._extracted_sources = {}
        self._pause_on_connect = False  # Flag to auto-pause when simulation connects
        # Client-side accumulation of monitor history
        self._monitor_history = {
            'iteration': [],
            'continuity': [],
            'momentum_x': [],
            'momentum_y': [],
            'momentum_z': [],
            'energy': [],
        }
        self._last_iteration = -1
        self._pause_at_iteration = None  # Breakpoint target (iteration number)

    @property
    def _app(self):
        """Get the trame app from the base MCP."""
        return self._workflow_mcp._base_mcp.app

    # =========================================================================
    # Internal helpers
    # =========================================================================

    @staticmethod
    def _unwrap_composite(data):
        """Unwrap composite/partitioned datasets to leaf dataset.

        Descends through vtkPartitionedDataSet and vtkMultiBlockDataSet
        wrappers, returning the first non-empty leaf or None.
        """
        while data is not None:
            if hasattr(data, 'GetPartition') and data.GetNumberOfPartitions() > 0:
                data = data.GetPartition(0)
            elif hasattr(data, 'GetBlock') and data.GetNumberOfBlocks() > 0:
                data = data.GetBlock(0)
            elif hasattr(data, 'GetNumberOfPoints'):
                break
            else:
                data = None
        return data

    @staticmethod
    def _composite_stats(fetched):
        """Get total point/cell counts across all partitions/blocks.

        Returns (n_points, n_cells).
        """
        n_points = 0
        n_cells = 0
        if hasattr(fetched, 'GetNumberOfPartitions'):
            for p in range(fetched.GetNumberOfPartitions()):
                part = fetched.GetPartition(p)
                if part:
                    n_points += part.GetNumberOfPoints()
                    n_cells += part.GetNumberOfCells()
        elif hasattr(fetched, 'GetNumberOfBlocks'):
            for b in range(fetched.GetNumberOfBlocks()):
                block = fetched.GetBlock(b)
                if block:
                    n_points += block.GetNumberOfPoints()
                    n_cells += block.GetNumberOfCells()
        elif hasattr(fetched, 'GetNumberOfPoints'):
            n_points = fetched.GetNumberOfPoints()
            n_cells = fetched.GetNumberOfCells()
        return n_points, n_cells

    def _accumulate_monitor_points(self, data):
        """Append new iteration data to client-side monitor history.

        Scans point data arrays for iterations beyond ``_last_iteration``
        and appends them to ``_monitor_history``.  Returns the number of
        new points added.
        """
        if not data or not hasattr(data, 'GetPointData'):
            return 0
        pd = data.GetPointData()
        iter_arr = pd.GetArray('iteration')
        if not iter_arr:
            return 0

        added = 0
        for i in range(iter_arr.GetNumberOfTuples()):
            iteration = iter_arr.GetValue(i)
            if iteration > self._last_iteration:
                self._monitor_history['iteration'].append(iteration)
                for name in ['continuity', 'momentum_x', 'momentum_y', 'momentum_z', 'energy']:
                    arr = pd.GetArray(name)
                    if arr and i < arr.GetNumberOfTuples():
                        self._monitor_history[name].append(arr.GetValue(i))
                self._last_iteration = iteration
                added += 1
        return added

    def _process_events(self):
        """Pump the VTK network access manager event queue."""
        from paraview import servermanager
        pm = servermanager.vtkProcessModule.GetProcessModule()
        nam = pm.GetNetworkAccessManager()
        while nam.ProcessEvents(1) == 1:
            pass

    # =========================================================================
    # Cost tracking tools
    # =========================================================================
    
    def get_session_cost(self) -> dict:
        """Get current chat session cost and usage statistics."""
        return self._llm_client.get_cost()
    
    def reset_session_cost(self) -> dict:
        """Reset the cost tracking counters to zero."""
        self._llm_client.reset_cost()
        return {"status": "reset", "message": "Cost counters reset to zero"}
    
    # =========================================================================
    # Live connection tools (only available if --live flag used)
    # =========================================================================
    
    def connect_live(self, host: str = None, port: int = None, pause: bool = None) -> dict:
        """
        Connect to a running Catalyst-enabled simulation.
        
        Args:
            host: Hostname (default from --host arg)
            port: Port number (default from --port arg)
            pause: If True, immediately pause simulation after connecting
        """
        if not self._live_enabled:
            return {"error": "Live mode not enabled. Restart with --live flag."}
        
        from paraview import servermanager
        from paraview.simple import SetActiveConnection
        
        host = host or self._live_host
        port = port or self._live_port
        
        # Use pause_on_connect flag if pause not explicitly specified
        should_pause = pause if pause is not None else self._pause_on_connect
        
        try:
            # IMPORTANT: Save the display session before connecting to Catalyst
            # This is what ParaView GUI does - we need to restore it after connecting
            self._display_session = servermanager.ActiveConnection.Session
            
            # Connect to Catalyst - this changes the active connection
            self._live_link = servermanager.ConnectToCatalyst(host, port)
            
            # Process pending notifications
            self._process_events()
            
            # Initialize the link
            self._live_link.InvokeCommand('Initialize')
            
            # CRITICAL: Restore the active connection to the display session
            # Without this, all subsequent operations try to work on the Catalyst
            # session instead of the local rendering session
            SetActiveConnection(servermanager.GetConnectionFromSession(self._display_session))
            
            # Ensure we have an active view
            view = simple.GetActiveView()
            if view is None:
                view = simple.GetActiveViewOrCreate('RenderView')
                print(f"[Live] Created new RenderView: {view}")
            
            result = {
                "status": "connected",
                "host": host,
                "port": port,
            }
            
            # Auto-pause if requested
            if should_pause:
                self._live_link.GetProperty('SimulationPaused').SetElement(0, 1)
                self._live_link.UpdateVTKObjects()
                result["paused"] = True
                result["tip"] = "Simulation paused. Use 'extract surface' or 'extract volume' to get data."
            else:
                result["tip"] = "Use 'pause simulation' then extract data to visualize."
            
            # Clear the flag after use
            self._pause_on_connect = False
            
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def set_pause_on_connect(self, enabled: bool = True) -> dict:
        """
        Set flag to automatically pause simulation when it connects.
        
        Call this before starting the simulation. When the simulation
        connects, it will be immediately paused.
        
        Args:
            enabled: True to pause on connect, False to disable
        """
        self._pause_on_connect = enabled
        return {
            "status": "ok",
            "pause_on_connect": enabled,
            "tip": "Now start the simulation. It will pause automatically when it connects."
        }
    
    def disconnect_live(self) -> dict:
        """Disconnect from the simulation and clean up resources."""
        if self._live_link:
            try:
                # Clean up extracted source proxies before dropping the link
                for name, proxy in self._extracted_sources.items():
                    try:
                        simple.Delete(proxy)
                    except Exception:
                        pass
                # Drop the Catalyst connection session
                from paraview import servermanager
                link_spm = self._live_link.GetInsituProxyManager()
                if link_spm:
                    session = link_spm.GetSession()
                    if session:
                        conn = servermanager.GetConnectionFromSession(session)
                        if conn:
                            servermanager.Disconnect(conn)
            except Exception as e:
                print(f"[Live] Disconnect error (non-fatal): {e}")
            self._live_link = None
            self._display_session = None
            self._monitor_source = None
            self._monitoring_active = False
            self._extracted_sources = {}
        return {"status": "disconnected"}
    
    def is_connection_alive(self) -> bool:
        """Check if the live connection is still active."""
        if not self._live_link:
            return False
        try:
            # Try to get a property - will fail if connection dropped
            self._live_link.GetProperty('SimulationPaused')
            return True
        except:
            return False
    
    def get_live_status(self) -> dict:
        """Get current timestep and time from the live simulation."""
        if not self._live_link:
            return {"status": "not_connected"}
        
        try:
            time = simple.GetAnimationScene().TimeKeeper.Time
            return {"status": "connected", "time": time}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def pause_simulation(self) -> dict:
        """Pause the running simulation for detailed analysis."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        try:
            # Use same logic as paraview.live.PauseCatalyst
            current_state = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            if not current_state:
                self._live_link.GetProperty('SimulationPaused').SetElement(0, 1)
                self._live_link.UpdateVTKObjects()
            return {"status": "paused"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def resume_simulation(self) -> dict:
        """Resume a paused simulation."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        try:
            current_state = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            if current_state:
                self._live_link.GetProperty('SimulationPaused').SetElement(0, 0)
                self._live_link.UpdateVTKObjects()
                self._live_link.InvokeCommand('LiveChanged')
            return {"status": "resumed"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def set_breakpoint(self, iteration: int) -> dict:
        """
        Set a breakpoint at a specific iteration number.
        
        The simulation will automatically pause when it reaches this
        iteration.  Requires monitoring to be active (extract_monitors).
        
        Args:
            iteration: Iteration number to pause at
        """
        self._pause_at_iteration = iteration
        return {
            "status": "breakpoint_set",
            "pause_at": iteration,
            "current_iteration": self._last_iteration,
        }
    
    def clear_breakpoint(self) -> dict:
        """Clear any active breakpoint."""
        was_set = self._pause_at_iteration
        self._pause_at_iteration = None
        return {
            "status": "breakpoint_cleared",
            "was_set_at": was_set,
        }
    
    def step_simulation(self, count: int = 1) -> dict:
        """
        Step the simulation forward by a number of iterations, then pause.
        
        Resumes the simulation and sets a breakpoint at current_iteration + count.
        Auto-starts monitoring if not already active.
        
        Args:
            count: Number of iterations to advance (default: 1)
        """
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        # Auto-start monitoring if needed — we need iteration tracking
        if not self._monitoring_active:
            result = self.extract_monitors()
            if result.get("status") == "error":
                return result
            print(f"[Live] Auto-started monitoring for step")
        
        target = self._last_iteration + count
        self._pause_at_iteration = target
        
        # Resume the simulation
        result = self.resume_simulation()
        if result.get("status") == "error":
            return result
        
        print(f"[Live] Stepping from iteration {self._last_iteration} to {target}")
        
        return {
            "status": "stepping",
            "from_iteration": self._last_iteration,
            "to_iteration": target,
            "count": count,
        }
    
    def extract_live_data(self, source_name: str) -> dict:
        """
        Extract data from the live simulation to local ParaView session.
        
        This uses the same mechanism as ParaView GUI's extract button.
        The data is copied from the simulation to the local session.
        
        Args:
            source_name: Name of the source to extract (e.g., "surface", "volume", "grid")
        """
        if not self._live_link:
            return {"error": "Not connected to live simulation"}
        
        from paraview.live import ExtractCatalystData
        
        # Check if already extracted - just update the existing source
        if source_name in self._extracted_sources:
            existing = self._extracted_sources[source_name]
            existing.UpdatePipeline()
            info = existing.GetDataInformation()
            return {
                "status": "updated",
                "source": source_name,
                "data_type": info.GetDataClassName(),
                "points": info.GetNumberOfPoints(),
                "cells": info.GetNumberOfCells(),
                "note": "Using existing extraction, data updated"
            }
        
        try:
            # Process any pending notifications first
            self._process_events()
            
            print(f"[extract_live_data] Extracting '{source_name}'")
            
            # Use ExtractCatalystData like extract_monitors does
            extracted = ExtractCatalystData(self._live_link, source_name)
            
            # Process notifications after extraction
            self._process_events()
            
            if extracted:
                # Force pipeline update
                extracted.UpdatePipeline()
                
                self._extracted_sources[source_name] = extracted
                
                # Get info after update
                info = extracted.GetDataInformation()
                data_type = info.GetDataClassName()
                n_points = info.GetNumberOfPoints()
                n_cells = info.GetNumberOfCells()
                
                # For composite/partitioned datasets, Fetch to get actual counts
                if info.IsCompositeDataSet() or n_points == 0:
                    from paraview import servermanager
                    try:
                        fetched = servermanager.Fetch(extracted)
                        if fetched:
                            n_points, n_cells = self._composite_stats(fetched)
                    except Exception as e:
                        print(f"[extract_live_data] Fetch failed: {e}")
                
                # Get field names
                point_fields = list(extracted.PointData.keys()) if hasattr(extracted, 'PointData') else []
                cell_fields = list(extracted.CellData.keys()) if hasattr(extracted, 'CellData') else []
                
                print(f"[extract_live_data] {data_type}: {n_points} pts, {n_cells} cells, "
                      f"fields: {point_fields} / {cell_fields}")
                
                # Update trame app to refresh pipeline browser
                if self._app:
                    self._app.update()
                    if hasattr(self._app.server.controller, 'on_data_change'):
                        self._app.server.controller.on_data_change()
                
                result = {
                    "status": "extracted",
                    "source": source_name,
                    "data_type": data_type,
                    "points": n_points,
                    "cells": n_cells,
                    "point_fields": point_fields,
                    "cell_fields": cell_fields,
                    "tip": "Data extracted. Use show_live_source() to visualize."
                }
                
                return result
            else:
                # List what sources are available
                available = [name for (name, _id) in simple.GetSources().keys()]
                return {
                    "status": "error", 
                    "message": f"Failed to extract '{source_name}'",
                    "available_sources": available
                }
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def show_live_source(self, source_name: str, color_by: str = None) -> dict:
        """
        Show a live source in the render view.
        
        Automatically extracts the data first if not already extracted.
        
        Args:
            source_name: Name of the source to show (e.g., "grid")
            color_by: Optional field name to color by
        """
        # Extract first if needed
        if source_name not in self._extracted_sources:
            if self._live_link:
                result = self.extract_live_data(source_name)
                if result.get("status") == "error":
                    return result
        
        # Get the source (either extracted or regular)
        source = self._extracted_sources.get(source_name) or simple.FindSource(source_name)
        
        if not source:
            available = [name for (name, _id) in simple.GetSources().keys()]
            return {"error": f"Source '{source_name}' not found. Available: {available}"}
        
        try:
            simple.SetActiveSource(source)
            rep = simple.Show(source)
            
            if color_by:
                # Use proxy's PointData/CellData interface for field lookup
                point_fields = list(source.PointData.keys())
                cell_fields = list(source.CellData.keys())
                
                location = None
                actual_name = color_by
                
                # Check point data
                for name in point_fields:
                    if name.lower() == color_by.lower():
                        location = "POINTS"
                        actual_name = name
                        break
                
                # Check cell data if not found in points
                if not location:
                    for name in cell_fields:
                        if name.lower() == color_by.lower():
                            location = "CELLS"
                            actual_name = name
                            break
                
                if location:
                    simple.ColorBy(rep, (location, actual_name))
                    rep.RescaleTransferFunctionToDataRange(True, False)
            
            view = simple.GetActiveView()
            simple.ResetCamera(view)
            simple.Render(view)
            
            # Update the trame app to refresh pipeline browser
            if self._app:
                self._app.update()
                # Trigger pipeline browser refresh
                if hasattr(self._app.server.controller, 'on_data_change'):
                    self._app.server.controller.on_data_change()
            
            return {
                "status": "shown",
                "source": source_name,
                "color_by": color_by,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def extract_monitors(self, channel_name: str = "monitors") -> dict:
        """
        Start monitoring residuals from the live simulation.
        
        Extracts once and then accumulates data on client side.
        """
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        
        # Check if already extracted
        if channel_name in self._extracted_sources and self._monitor_source:
            # Just update the existing source
            self._monitor_source.UpdatePipeline()
            self._monitoring_active = True  # Ensure monitoring is active
            # Reset analysis chart flag to allow live updates
            if self._app and hasattr(self._app, 'state'):
                self._app.state.analysis_chart_active = False
            return {
                "status": "monitoring",
                "channel": channel_name,
                "history_points": len(self._monitor_history['iteration']),
                "fields": list(self._monitor_source.PointData.keys()),
                "note": "Using existing extraction"
            }
        
        try:
            from paraview.live import ExtractCatalystData
            from paraview import servermanager
            
            self._process_events()
            extracted = ExtractCatalystData(self._live_link, channel_name)
            self._process_events()
            
            if extracted:
                extracted.UpdatePipeline()
                self._monitor_source = extracted
                self._extracted_sources[channel_name] = extracted
                self._monitoring_active = True
                
                # Reset analysis chart flag to allow live updates
                if self._app and hasattr(self._app, 'state'):
                    self._app.state.analysis_chart_active = False
                
                # Reset client-side history
                self._monitor_history = {
                    'iteration': [],
                    'continuity': [],
                    'momentum_x': [],
                    'momentum_y': [],
                    'momentum_z': [],
                    'energy': [],
                }
                self._last_iteration = -1
                
                # Immediately fetch and populate initial data
                try:
                    data = servermanager.Fetch(extracted)
                    data = self._unwrap_composite(data)
                    self._accumulate_monitor_points(data)
                except Exception as e:
                    print(f"[extract_monitors] Initial fetch failed: {e}")
                
                # Trigger pipeline browser refresh
                if self._app:
                    self._app.update()
                    if hasattr(self._app.server.controller, 'on_data_change'):
                        self._app.server.controller.on_data_change()
                
                info = extracted.GetDataInformation()
                n_points = info.GetNumberOfPoints()
                fields = list(extracted.PointData.keys())
                
                return {
                    "status": "monitoring",
                    "channel": channel_name,
                    "history_points": len(self._monitor_history['iteration']),
                    "fields": fields,
                    "tip": "Open chart panel (top-right) to see live residuals."
                }
            else:
                available = [name for (name, _id) in simple.GetSources().keys()]
                return {
                    "status": "error", 
                    "message": f"Channel '{channel_name}' not found.",
                    "available_sources": available,
                }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def stop_monitoring(self) -> dict:
        """Stop monitoring residual values."""
        self._monitoring_active = False
        return {"status": "stopped"}
    
    def show_monitor_chart(self, 
                           x_field: str = "iteration",
                           y_fields: list | None = None,
                           log_scale: bool = True) -> dict:
        """
        Start showing the live residual chart.
        
        The chart appears in the right drawer panel and updates automatically.
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            self._monitor_source.UpdatePipeline()
            available_fields = list(self._monitor_source.PointData.keys())
            
            info = self._monitor_source.GetDataInformation()
            n_points = info.GetNumberOfPoints()
            
            # Store config (used by get_monitor_data)
            self._chart_config = {
                'x_field': x_field,
                'y_fields': y_fields or [f for f in available_fields if f not in ['iteration', 'time']],
                'log_scale': log_scale
            }
            
            return {
                "status": "chart_ready",
                "message": "Open the chart panel (top-right icon) to see live residuals",
                "history_points": n_points,
                "fields": available_fields,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def get_monitor_data(self) -> dict:
        """
        Get monitor data, accumulating new points from simulation.

        Uses the cached _monitor_source proxy (created by extract_monitors)
        rather than re-calling ExtractCatalystData each poll.  The
        _accumulate_monitor_points helper handles deduplication via
        _last_iteration, so we always update+fetch here — no time guard.
        """
        if not self._live_link or not self._monitoring_active:
            return {"error": "Not monitoring"}

        if not self._monitor_source:
            return {"error": "No monitor source. Call extract_monitors() first."}

        try:
            from paraview import servermanager

            # Pump network events so pipeline sees new data
            self._process_events()

            # Update the existing proxy and fetch data
            self._monitor_source.UpdatePipeline()
            data = servermanager.Fetch(self._monitor_source)
            data = self._unwrap_composite(data)
            self._accumulate_monitor_points(data)

            # Check breakpoint
            if (self._pause_at_iteration is not None
                    and self._last_iteration >= self._pause_at_iteration):
                self.pause_simulation()
                self._pause_at_iteration = None
                print(f"[Live] Breakpoint hit at iteration {self._last_iteration}")

            return {
                "iteration": self._monitor_history['iteration'],
                "residuals": {k: v for k, v in self._monitor_history.items() if k != 'iteration'},
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
    
    def get_current_monitors(self) -> dict:
        """Get the latest monitor values."""
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName()
            
            result = {"status": "ok", "data_type": data_type, "values": {}}
            
            if data_type == "vtkTable":
                row_info = info.GetRowDataInformation()
                result["num_rows"] = info.GetNumberOfRows()
                
                for i in range(row_info.GetNumberOfArrays()):
                    arr_info = row_info.GetArrayInformation(i)
                    name = arr_info.GetName()
                    ranges = arr_info.GetComponentRange(0)
                    result["values"][name] = {"min": ranges[0], "max": ranges[1]}
            else:
                point_info = info.GetPointDataInformation()
                result["num_points"] = info.GetNumberOfPoints()
                
                for i in range(point_info.GetNumberOfArrays()):
                    arr_info = point_info.GetArrayInformation(i)
                    name = arr_info.GetName()
                    ranges = arr_info.GetComponentRange(0)
                    result["values"][name] = {"min": ranges[0], "max": ranges[1]}
            
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration with all tools."""
        base_mcp = self._workflow_mcp.mcp
        
        tools = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        
        if self._live_enabled:
            tools.extend([
                self.connect_live,
                self.disconnect_live,
                self.get_live_status,
                self.set_pause_on_connect,
                self.pause_simulation,
                self.resume_simulation,
                self.set_breakpoint,
                self.clear_breakpoint,
                self.step_simulation,
                self.extract_live_data,
                self.show_live_source,
                self.extract_monitors,
                self.show_monitor_chart,
                self.get_current_monitors,
            ])
            
            base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

Workflow for visualizing live data:
1. connect_live() - Connect to simulation (optionally with pause=True)
2. pause_simulation() - Pause for detailed analysis  
3. extract_live_data("surface") or extract_live_data("volume") - Extract data
4. show_live_source("surface", color_by="p") - Display with coloring

Alternative: Call set_pause_on_connect() before starting simulation to auto-pause on connect.

The extract step is REQUIRED when paused - it copies data from simulation memory.

Other tools:
- resume_simulation() - Continue after analysis
- step_simulation(count=5) - Advance N iterations then auto-pause
- set_breakpoint(iteration=100) - Pause when iteration is reached
- clear_breakpoint() - Remove active breakpoint
- extract_monitors("monitors") - Get residual data
- show_monitor_chart() - Visualize convergence
"""
        
        base_mcp["tools"] = tools
        return base_mcp
