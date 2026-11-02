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
from vtkmodules.vtkCommonDataModel import vtkDataObject
import re
from trame_llm.paraview import resolve_field


POINT = vtkDataObject.POINT
ROW = vtkDataObject.ROW


class CFDChatMCP:
    """MCP wrapper that adds cost tracking and optional live monitoring tools."""
    
    def __init__(self, workflow_mcp, llm_client, live_enabled=False, live_host="localhost", live_port=22222,
                 live_proxies=None):
        import os
        self._workflow_mcp = workflow_mcp
        # Proxy definitions (XML) for the simulation's steerable parameters, colon separated.
        self._live_proxies = live_proxies or os.environ.get("CATALYST_LIVE_PROXIES", "")
        self._live_proxies_loaded = False
        # Called as on_steer(name, value) after a steering change is sent, so a UI can follow.
        self.on_steer = None
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
            elif hasattr(data, 'GetRowData') or hasattr(data, 'GetNumberOfPoints'):
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

    RESIDUAL_PATTERN = re.compile(r"^(continuity|momentum|energy|mass|residual|res_|r_)", re.IGNORECASE)
    FORCE_PATTERN = re.compile(r"(drag|lift|^c[dl]$|force)", re.IGNORECASE)
    STATE_MONITORS = ("reynolds", "collision")

    @classmethod
    def is_residual(cls, name: str) -> bool:
        return bool(cls.RESIDUAL_PATTERN.match(name))

    @staticmethod
    def _monitor_arrays(data):
        """Columns of a monitor table, or point arrays of a monitor point set."""
        if data is None:
            return None
        if hasattr(data, 'GetRowData'):
            return data.GetRowData()
        if hasattr(data, 'GetPointData'):
            return data.GetPointData()
        return None

    @staticmethod
    def _field_names(proxy):
        """Array names of a source: columns for a table, point arrays otherwise."""
        info = proxy.GetDataInformation().DataInformation
        attributes = info.GetAttributeInformation(ROW if info.GetNumberOfRows() else POINT)
        if attributes is None:
            return []
        return [attributes.GetArrayInformation(i).GetName()
                for i in range(attributes.GetNumberOfArrays())]

    def _accumulate_monitor_points(self, data):
        """Append new iteration data to client-side monitor history.

        Scans point data arrays for iterations beyond ``_last_iteration``
        and appends them to ``_monitor_history``.  Returns the number of
        new points added.
        """
        pd = self._monitor_arrays(data)
        if pd is None:
            return 0
        iter_arr = pd.GetArray('iteration')
        if not iter_arr:
            return 0

        added = 0
        for i in range(iter_arr.GetNumberOfTuples()):
            iteration = iter_arr.GetValue(i)
            if iteration > self._last_iteration:
                self._monitor_history['iteration'].append(iteration)
                for a in range(pd.GetNumberOfArrays()):
                    arr, name = pd.GetArray(a), pd.GetArrayName(a)
                    if arr is not None and name != 'iteration' and i < arr.GetNumberOfTuples():
                        self._monitor_history.setdefault(name, []).append(arr.GetValue(i))
                self._last_iteration = iteration
                added += 1
        return added

    def _wait_for_data(self, proxy, timeout=15.0):
        """Pump Live events until a fresh extract has received its first data."""
        import time
        if proxy is None:
            return False
        end = time.time() + timeout
        while time.time() < end:
            self._process_events()
            proxy.UpdatePipeline()
            # Wait for real content: an empty composite arrives first, and showing it
            # would pick a representation without Volume or Slice.
            info = proxy.GetDataInformation().DataInformation
            if info.GetNumberOfPoints() > 0 or info.GetNumberOfRows() > 0:
                return True
            time.sleep(0.1)
        return False

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
    
    def connect_live(self, host: str | None = None, port: int | None = None, pause: bool | None = None) -> dict:
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

        if self._live_link and self.is_connection_alive():
            return {
                "status": "already_connected",
                "host": host,
                "port": port,
                "channels": self.live_channels(),
                "tip": "The live link is up; use get_live_status() and show_live_source() directly.",
            }

        # Use pause_on_connect flag if pause not explicitly specified
        should_pause = pause if pause is not None else self._pause_on_connect
        
        self._load_live_proxies()
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
    
    def _load_live_proxies(self):
        if self._live_proxies_loaded or not self._live_proxies:
            return
        from paraview.modules.vtkRemotingServerManager import vtkSMProxyManager
        plugins = vtkSMProxyManager.GetProxyManager().GetPluginManager()
        for path in filter(None, self._live_proxies.split(":")):
            if not plugins.LoadLocalPlugin(path):
                print(f"[Live] Could not load proxy definitions from {path}")
        self._live_proxies_loaded = True

    def _steerable_proxies(self) -> dict:
        if not self._live_link:
            return {}
        self._process_events()
        ipm = self._live_link.GetInsituProxyManager()
        if ipm is None:
            return {}
        proxies = {}
        for i in range(ipm.GetNumberOfProxies("sources")):
            name = ipm.GetProxyName("sources", i)
            proxy = ipm.GetProxy("sources", name)
            if proxy is not None and proxy.GetVTKClassName() == "vtkSteeringDataGenerator":
                proxies[name] = proxy
        return proxies

    @staticmethod
    def _is_text(prop):
        """A property marked <Expression/> in its hints holds text as UTF-8 byte values."""
        hints = prop.GetHints()
        return hints is not None and hints.FindNestedElementByName("Expression") is not None

    @classmethod
    def _describe_property(cls, proxy, key):
        from paraview.modules.vtkRemotingServerManager import vtkSMPropertyHelper
        prop = proxy.GetProperty(key)
        entry = {"name": key, "label": prop.GetXMLLabel()}
        if cls._is_text(prop):
            codes = [int(prop.GetElement(i)) for i in range(prop.GetNumberOfElements())]
            entry["kind"] = "text"
            entry["value"] = bytes(c for c in codes if 0 < c < 256).decode("utf-8", "replace")
            hint = prop.GetHints().FindNestedElementByName("Expression")
            if hint.GetAttribute("status"):
                entry["status_channel"] = hint.GetAttribute("status")
        else:
            entry["value"] = vtkSMPropertyHelper(proxy, key).GetAsDouble()
        doc = prop.GetDocumentation()
        if doc is not None and doc.GetDescription():
            entry["description"] = " ".join(doc.GetDescription().split())
        rng = prop.GetDomain("range")
        if rng is not None and rng.GetMinimumExists(0):
            entry["min"] = rng.GetMinimum(0)
            entry["max"] = rng.GetMaximum(0)
        enum = prop.GetDomain("enum")
        if enum is not None:
            entry["choices"] = {enum.GetEntryText(i): enum.GetEntryValue(i)
                                for i in range(enum.GetNumberOfEntries())}
        return entry

    def get_simulation_parameters(self) -> dict:
        """List the parameters of the running simulation that can be changed while it runs
        (steering), with their current values, valid ranges and choices."""
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        params = []
        for proxy in self._steerable_proxies().values():
            it = proxy.NewPropertyIterator()
            it.Begin()
            while not it.IsAtEnd():
                prop = it.GetProperty()
                if prop.GetPanelVisibility() != "never" and not prop.GetInformationOnly():
                    params.append(self._describe_property(proxy, it.GetKey()))
                it.Next()
        if not params:
            return {"status": "none", "message": "This simulation publishes no steerable parameters."}
        for entry in params:
            channel = entry.pop("status_channel", None)
            if channel:
                entry["outcome"] = self._read_text_channel(channel)
        return {"status": "ok", "parameters": params}

    def _read_text_channel(self, name):
        """A channel the simulation publishes as a table whose "message" column holds UTF-8
        byte values: the outcome of a text steering request, for example."""
        from paraview import servermanager
        from paraview.live import ExtractCatalystData
        if name not in self.live_channels():
            return None
        proxy = self._extracted_sources.get(name)
        if proxy is None:
            proxy = ExtractCatalystData(self._live_link, name)
            self._extracted_sources[name] = proxy
        self._wait_for_data(proxy, timeout=5.0)
        proxy.UpdatePipeline()
        data = servermanager.Fetch(proxy)
        tables = [data]
        if hasattr(data, "GetNumberOfPartitionedDataSets"):
            tables = [data.GetPartition(i, j) for i in range(data.GetNumberOfPartitionedDataSets())
                      for j in range(data.GetNumberOfPartitions(i))]
        elif hasattr(data, "GetNumberOfPartitions"):
            tables = [data.GetPartition(i) for i in range(data.GetNumberOfPartitions())]
        for table in tables:
            column = table.GetColumnByName("message") if table is not None and hasattr(table, "GetColumnByName") else None
            if column is not None:
                codes = [int(column.GetTuple1(i)) for i in range(column.GetNumberOfTuples())]
                return bytes(c for c in codes if 0 < c < 256).decode("utf-8", "replace")
        return None

    def set_simulation_parameter(self, name: str, value: str) -> dict:
        """Change a parameter of the running simulation, for example name="Reynolds", value="500"
        or name="Collision", value="Smagorinsky LES". A parameter of kind "text" takes text: for
        name="DerivedFields", NAME=EXPRESSION entries separated by ';' in VTK calculator syntax,
        with @cells after an expression with derivatives, for example
        value="helicity=dot(velocity, curl(velocity))@cells; cp=2 * pressure / 0.0064".
        The simulation applies it at its next Catalyst update, within a few hundred iterations.
        Call get_simulation_parameters() for the names, ranges, choices and descriptions."""
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        from paraview.modules.vtkRemotingServerManager import vtkSMPropertyHelper
        for proxy in self._steerable_proxies().values():
            it = proxy.NewPropertyIterator()
            it.Begin()
            while not it.IsAtEnd():
                if it.GetKey().lower() == str(name).lower():
                    name = it.GetKey()
                    break
                it.Next()
            prop = proxy.GetProperty(name)
            if prop is None:
                continue
            info = self._describe_property(proxy, name)
            choices = info.get("choices")
            if info.get("kind") == "text":
                text = str(value).strip()
                codes = list(text.encode("utf-8")) or [0]
                prop.SetNumberOfElements(len(codes))
                for i, code in enumerate(codes):
                    prop.SetElement(i, code)
                proxy.UpdateVTKObjects()
                self._live_link.GetInsituProxyManager().Modified()
                if self._live_link.GetProperty("SimulationPaused").GetElement(0) == 1:
                    self._live_link.PushUpdatedStates()
                if self.on_steer:
                    self.on_steer(name, text)
                result = {"status": "requested", "name": name, "previous": info["value"], "value": text,
                          "note": "The simulation applies this at its next Catalyst update. Call "
                                  "get_simulation_parameters() after it for the outcome: the fields "
                                  "added, or the error and where it is in the text. New fields "
                                  "appear on the grid channel."}
                names = [entry.partition("=")[0].strip() for entry in text.split(";") if "=" in entry]
                if names and self._extracted_sources:
                    ready = self._wait_for_fields(names)
                    result["fields_ready"] = ready
                    if len(ready) == len(names):
                        result["note"] = ("The new fields have arrived on the channels listed in fields_ready: "
                                          "color or analyze them now, without stepping or pausing the simulation.")
                return result
            if choices:
                match = {k.lower(): v for k, v in choices.items()}.get(str(value).strip().lower())
                number = float(match) if match is not None else float(value)
                if int(number) not in choices.values():
                    return {"error": f"'{value}' is not one of {list(choices)}"}
            else:
                number = float(value)
                if "min" in info and not info["min"] <= number <= info["max"]:
                    return {"error": f"{name} must be between {info['min']} and {info['max']}"}
            vtkSMPropertyHelper(proxy, name).Set(number)
            proxy.UpdateVTKObjects()
            # Marks the Live state dirty so it is pushed to the simulation.
            self._live_link.GetInsituProxyManager().Modified()
            if self._live_link.GetProperty("SimulationPaused").GetElement(0) == 1:
                self._live_link.PushUpdatedStates()
            if self.on_steer:
                self.on_steer(name, number)
            return {"status": "requested", "name": name, "previous": info["value"], "value": number,
                    "note": "The simulation applies this at its next Catalyst update."}
        return {"error": f"No steerable parameter named '{name}'",
                "available": [p["name"] for p in self.get_simulation_parameters().get("parameters", [])]}

    def _wait_for_fields(self, names: list, timeout: float = 20.0) -> dict:
        """Pump Live events until each name is a field of an extracted channel: {name: [channels]}."""
        import time
        end, found = time.time() + timeout, {}
        while time.time() < end:
            self._process_events()
            found = {}
            for channel, proxy in self._extracted_sources.items():
                try:
                    proxy.UpdatePipeline()
                    fields = set(proxy.PointData.keys()) | set(proxy.CellData.keys())
                except AttributeError:
                    continue
                for name in names:
                    if name in fields:
                        found.setdefault(name, []).append(channel)
            if len(found) == len(names):
                break
            time.sleep(0.25)
        return found

    @staticmethod
    def _describe(source) -> dict:
        """Type, size and extent of a source's output, with a hint for 3D volumes."""
        info = source.GetDataInformation().DataInformation
        result = {
            "data_type": info.GetPrettyDataTypeString() or info.GetDataClassName(),
            "points": info.GetNumberOfPoints(),
            "cells": info.GetNumberOfCells(),
            "bounds": [round(b, 4) for b in info.GetBounds()],
            "data_size_kb": info.GetMemorySize(),
        }
        extent = info.GetExtent()
        if extent[0] <= extent[1]:
            result["dimensions"] = [extent[2 * i + 1] - extent[2 * i] + 1 for i in range(3)]
        bounds = info.GetBounds()
        if info.GetNumberOfCells() and not info.HasDataSetType(0):
            if all(bounds[2 * i + 1] > bounds[2 * i] for i in range(3)):
                result["note"] = ("This channel is a full 3D volume. A Surface display shows only its "
                                  "outer faces; use a slice, clip, contour, streamlines or the Volume "
                                  "representation to see the interior.")
        return result

    def live_channels(self) -> list:
        """Names of the data channels the connected simulation publishes."""
        if not self._live_link:
            return []
        self._process_events()
        ipm = self._live_link.GetInsituProxyManager()
        if ipm is None:
            return []
        names = [ipm.GetProxyName("sources", i) for i in range(ipm.GetNumberOfProxies("sources"))]
        steering = set(self._steerable_proxies())
        return [name for name in names if name not in steering and not name.startswith("_")]

    def get_live_status(self) -> dict:
        """Get the live simulation's time, pause state and the names of its data channels."""
        if not self._live_link:
            return {"status": "not_connected"}

        try:
            time = simple.GetAnimationScene().TimeKeeper.Time
            paused = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            return {"status": "connected", "time": time, "paused": paused,
                    "channels": self.live_channels(),
                    "extracted": list(self._extracted_sources)}
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
            self._wait_for_data(extracted)
            
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
                    **self._describe(extracted),
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
    
    def show_live_source(self, source_name: str, color_by: str | None = None) -> dict:
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
            view = simple.GetActiveView()
            for other in simple.GetSources().values():
                if other is not source:
                    simple.Hide(other, view)
            simple.SetActiveSource(source)
            rep = simple.Show(source)
            # A volume grid shows as an outline by default, which hides the coloring.
            if rep.GetPropertyValue("Representation") == "Outline":
                rep.SetRepresentationType("Surface")

            if color_by:
                # Use proxy's PointData/CellData interface for field lookup
                point_fields = list(source.PointData.keys())
                cell_fields = list(source.CellData.keys())
                
                location = None
                actual_name = resolve_field(color_by, point_fields + cell_fields) or color_by
                color_by = actual_name
                
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
                **self._describe(source),
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
                "fields": self._field_names(self._monitor_source),
                "note": "Using existing extraction"
            }
        
        try:
            from paraview.live import ExtractCatalystData
            from paraview import servermanager
            
            self._process_events()
            extracted = ExtractCatalystData(self._live_link, channel_name)
            self._wait_for_data(extracted)
            
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
                
                fields = self._field_names(extracted)
                
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
        Show a live chart of monitor histories in the right drawer; it updates as the solver steps.

        Args:
            x_field: Field for the x axis (default: "iteration").
            y_fields: Monitor fields to plot (default: the residuals). For forces, for example
                ["drag", "lift"], set log_scale=False.
            log_scale: Logarithmic y axis, right for residuals (default: True).
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            self._monitor_source.UpdatePipeline()
            available_fields = self._field_names(self._monitor_source)
            info = self._monitor_source.GetDataInformation().DataInformation
            n_points = info.GetNumberOfRows() or info.GetNumberOfPoints()
            
            # Store config (used by get_monitor_data)
            self._chart_config = {
                'x_field': x_field,
                'y_fields': y_fields or [f for f in available_fields if self.is_residual(f)],
                'log_scale': log_scale
            }
            if self._app and hasattr(self._app, 'state'):
                self._app.state.analysis_chart_active = False
                self._app.state.chart_drawer_open = True
            
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
    
    def _convergence_summary(self, recent_fraction: float = 0.25) -> dict:
        """Orders of residual drop from each field's peak and the recent rate of drop."""
        import math
        iterations = self._monitor_history.get('iteration', [])
        if len(iterations) < 4:
            return {}
        fields = {}
        for name, values in self._monitor_history.items():
            if not self.is_residual(name) or len(values) != len(iterations):
                continue
            positive = [v for v in values if v and v > 0]
            if len(positive) < 4:
                continue
            peak, latest = max(positive), positive[-1]
            window = max(3, int(len(positive) * recent_fraction))
            recent_start = positive[-window]
            span = iterations[-1] - iterations[-window] or 1
            fields[name] = {
                "orders_dropped_from_peak": round(math.log10(peak / latest), 2),
                "recent_orders_per_100_iterations": round(100 * math.log10(recent_start / latest) / span, 2),
            }
        if not fields:
            return {}
        drops = [f["orders_dropped_from_peak"] for f in fields.values()]
        rates = [f["recent_orders_per_100_iterations"] for f in fields.values()]
        min_drop, decreasing = min(drops), all(r > 0.05 for r in rates)
        features_ok = min_drop >= 3.0 and decreasing
        return {
            "iterations": [iterations[0], iterations[-1]],
            "fields": fields,
            "min_orders_dropped": min_drop,
            "still_decreasing": decreasing,
            "flow_features_trustworthy": features_ok,
            "loads_trustworthy": self._loads_note(),
            "verdict": (f"Every residual has dropped at least {min_drop:.1f} orders from its peak"
                        + (" and is still decreasing" if decreasing else " but some have stopped decreasing")
                        + (": flow features can be trusted." if features_ok
                           else ": flow features should not be trusted yet.")
                        + " Integrated loads also need flat force histories: " + self._loads_note() + "."),
            "guidance": "Report the verdict. Details: ontology analysis_recommendations.convergence_assessment.",
        }

    def _loads_note(self) -> str:
        if any(self.FORCE_PATTERN.search(name) for name in self._monitor_history):
            return "force histories are monitored; get_force_statistics() reports whether they have settled"
        return "force and moment histories are not monitored in this session"

    def _monitor_columns(self) -> dict:
        """The full monitor history as lists, read from the monitors channel."""
        from paraview import servermanager
        self._process_events()
        self._monitor_source.UpdatePipeline()
        pd = self._monitor_arrays(self._unwrap_composite(servermanager.Fetch(self._monitor_source)))
        if pd is None or pd.GetArray("iteration") is None:
            return {}
        columns = {pd.GetArrayName(i): [pd.GetArray(i).GetValue(j) for j in range(pd.GetArray(i).GetNumberOfTuples())]
                   for i in range(pd.GetNumberOfArrays()) if pd.GetArray(i) is not None}
        order = sorted(range(len(columns["iteration"])), key=columns["iteration"].__getitem__)
        return {name: [values[j] for j in order] for name, values in columns.items() if len(values) == len(order)}

    @staticmethod
    def _shedding_period(x: list, y: list) -> float | None:
        """Mean spacing in x of upward zero crossings of y about its mean."""
        if len(y) < 8:
            return None
        mean = sum(y) / len(y)
        crossings = [x[i - 1] + (x[i] - x[i - 1]) * (mean - y[i - 1]) / (y[i] - y[i - 1])
                     for i in range(1, len(y)) if y[i - 1] < mean <= y[i]]
        if len(crossings) < 3:
            return None
        return (crossings[-1] - crossings[0]) / (len(crossings) - 1)

    def get_force_statistics(self, fields: list[str] | None = None) -> dict:
        """Time-averaged force coefficients from the monitor history, one entry per operating condition.

        Use this for average or accumulated drag and lift, how forces changed after steering, the
        vortex shedding frequency (Strouhal number), or whether the loads have settled.

        The history is split wherever a steered parameter (reynolds, collision) changes. For each
        condition it reports, per force coefficient: the mean over every sample since the condition
        began, and the mean, standard deviation and RMS over the settled second half, plus the
        drift between the last two quarters (settled when under 2 percent). The shedding period
        comes from the lift signal, as a Strouhal number when the monitors carry convective time.

        Args:
            fields: Force coefficient names (default: every drag, lift or force monitor).
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        try:
            columns = self._monitor_columns()
        except Exception as e:
            return {"status": "error", "message": str(e)}
        iterations = columns.get("iteration", [])
        fields = fields or [name for name in columns if self.FORCE_PATTERN.search(name)]
        missing = [name for name in fields if name not in columns]
        if missing or not fields or len(iterations) < 4:
            return {"error": "No force history to analyze", "missing": missing, "available": sorted(columns)}

        state = [name for name in self.STATE_MONITORS if name in columns]
        starts = [0] + [i for i in range(1, len(iterations))
                        if any(columns[name][i] != columns[name][i - 1] for name in state)]
        lift = next((name for name in fields if "lift" in name.lower() or name.lower() == "cl"), None)

        def r(v):
            return float(f"{v:.4g}")

        conditions = []
        for k, start in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(iterations)
            idx = list(range(start, end))
            half = idx[len(idx) // 2:]
            entry = {"iterations": [iterations[start], iterations[end - 1]], "samples": len(idx)}
            entry.update({name: r(columns[name][start]) for name in state})
            if len(idx) < 4:
                entry["note"] = "transitional: too few samples to average"
                conditions.append(entry)
                continue
            period = None
            if lift:
                period = self._shedding_period([iterations[i] for i in half], [columns[lift][i] for i in half])
            spacing = (iterations[half[-1]] - iterations[half[0]]) / max(len(half) - 1, 1)
            cycle = max(1, round(period / spacing)) if period and spacing else 1

            def whole_cycles(values):
                keep = len(values) // cycle * cycle
                return values[-keep:] if keep else values

            for name in fields:
                values = [columns[name][i] for i in idx]
                settled = [columns[name][i] for i in half]
                mean = sum(settled) / len(settled)
                std = (sum((v - mean) ** 2 for v in settled) / len(settled)) ** 0.5
                q = len(settled) // 2
                drift = None
                if q >= 2:
                    first, second = whole_cycles(settled[:q]), whole_cycles(settled[q:])
                    a, b = sum(first) / len(first), sum(second) / len(second)
                    drift = abs(b - a) / max(abs(mean), std, 1e-12)
                entry[name] = {
                    "mean_since_condition_start": r(sum(values) / len(values)),
                    "settled_mean": r(mean),
                    "settled_std": r(std),
                    "settled_rms": r((sum(v * v for v in settled) / len(settled)) ** 0.5),
                    "settled": drift is not None and drift < 0.02 and len(settled) >= 8,
                    "drift_fraction": None if drift is None else r(drift),
                }
            if period:
                entry["shedding_period_iterations"] = r(period)
                if "time" in columns:
                    t = [columns["time"][i] for i in half]
                    p_time = self._shedding_period(t, [columns[lift][i] for i in half])
                    if p_time:
                        entry["strouhal_number"] = r(1.0 / p_time)
            conditions.append(entry)

        return {
            "status": "ok",
            "fields": fields,
            "conditions": conditions,
            "note": "One entry per operating condition, oldest first. A condition that is not settled "
                    "needs more iterations before its mean can be quoted as final. These numbers are a "
                    "snapshot: call again after steering or for any later question.",
        }

    def get_current_monitors(self) -> dict:
        """Get the latest monitor values and a convergence assessment of the residual history.

        The 'convergence' entry reports, per residual, how many orders of magnitude it has
        dropped from its peak and how fast it is still dropping, so convergence can be judged
        against ontology analysis_recommendations.convergence_assessment.
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            info = self._monitor_source.GetDataInformation()
            data_type = info.GetDataClassName()
            
            result = {"status": "ok", "data_type": data_type, "values": {}}
            
            raw = info.DataInformation
            is_table = raw.GetNumberOfRows() > 0
            if is_table:
                result["num_rows"] = raw.GetNumberOfRows()
            else:
                result["num_points"] = raw.GetNumberOfPoints()
            attributes = raw.GetAttributeInformation(ROW if is_table else POINT)
            for i in range(attributes.GetNumberOfArrays() if attributes else 0):
                arr_info = attributes.GetArrayInformation(i)
                ranges = arr_info.GetComponentRange(0)
                result["values"][arr_info.GetName()] = {"min": ranges[0], "max": ranges[1]}

            latest = self._latest_monitor_values()
            if latest:
                result["latest"] = latest
            convergence = self._convergence_summary()
            if convergence:
                result["convergence"] = convergence
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def _latest_monitor_values(self) -> dict:
        """Each monitor's value at the most recent iteration (heater power, temperatures, forces)."""
        from paraview import servermanager
        try:
            data = self._unwrap_composite(servermanager.Fetch(self._monitor_source))
            pd = self._monitor_arrays(data)
            iteration = pd.GetArray("iteration") if pd else None
            if iteration is None or iteration.GetNumberOfTuples() == 0:
                return {}
            last = max(range(iteration.GetNumberOfTuples()), key=iteration.GetValue)
            return {pd.GetArrayName(i): pd.GetArray(i).GetTuple1(last)
                    for i in range(pd.GetNumberOfArrays()) if pd.GetArray(i) is not None}
        except Exception:
            return {}

    def _with_live_sources(self, update_color):
        """Wrap update_color so a live channel's name colors the extracted channel that is shown."""
        import functools

        @functools.wraps(update_color)
        def wrapper(proxy_name: str | None = None, field_name: str | None = None, rgb: list | None = None):
            source = self._extracted_sources.get(proxy_name or "")
            if source is None or rgb is not None or not field_name:
                return update_color(proxy_name=proxy_name, field_name=field_name, rgb=rgb)
            view = simple.GetActiveView()
            source.UpdatePipeline()
            points, cells = list(source.PointData.keys()), list(source.CellData.keys())
            name = resolve_field(field_name, points + cells) or field_name
            location = "POINTS" if name in points else "CELLS" if name in cells else None
            if location is None:
                return {"error": f"Could not find field {field_name} in {points + cells}"}
            rep = simple.GetDisplayProperties(source, view)
            simple.ColorBy(rep, (location, name))
            rep.RescaleTransferFunctionToDataRange(True, False)
            lut = simple.GetColorTransferFunction(name)
            lo, hi = lut.RGBPoints[0], lut.RGBPoints[-4]
            if lo < 0 < hi:
                extent = max(-lo, hi)
                lut.ApplyPreset("Cool to Warm", True)
                lut.AutomaticRescaleRangeMode = "Never"
                lut.RescaleTransferFunction(-extent, extent)
            rep.SetScalarBarVisibility(view, True)
            simple.Render(view)
            return {"name": proxy_name, "field": name, "location": location,
                    "range": [round(lo, 6), round(hi, 6)]}

        return wrapper

    def _with_live_channels(self, list_data):
        """Wrap list_data so its result also names the connected simulation's channels."""
        import functools

        @functools.wraps(list_data)
        def wrapper(*args, **kwargs):
            result = list_data(*args, **kwargs)
            if isinstance(result, dict) and self._live_link:
                pending = [c for c in self.live_channels() if c not in self._extracted_sources]
                result["live_simulation"] = {
                    "connected": True,
                    "channels": self.live_channels(),
                    "not_yet_extracted": pending,
                    "tip": "Channels from the running simulation are not listed above until extracted. "
                           "Call show_live_source('<channel>', color_by='<field>') to extract and display one.",
                }
            return result

        return wrapper

    @property
    def mcp(self) -> dict:
        """Return MCP declaration with all tools."""
        base_mcp = self._workflow_mcp.mcp
        
        tools = list(base_mcp["tools"]) + [
            self.get_session_cost,
            self.reset_session_cost,
        ]
        
        if self._live_enabled:
            wrappers = {"list_data": self._with_live_channels, "update_color": self._with_live_sources}
            tools = [wrappers[tool.__name__](tool) if getattr(tool, "__name__", "") in wrappers else tool
                     for tool in tools]
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
                self.get_simulation_parameters,
                self.set_simulation_parameter,
                self.extract_monitors,
                self.show_monitor_chart,
                self.get_current_monitors,
                self.get_force_statistics,
            ])
            
            base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

A live simulation publishes named data channels. get_live_status() lists them
in "channels" (for example "grid" for the flow field and "monitors" for residuals
and forces). Use those names; never assume "surface" or "volume". Each channel is
one dataset: a request for "the live volume" or "the flow field" means the fluid
grid channel, and a second channel such as "solid" is a separate body. A 3D grid
shown as a Surface displays only its outer faces, so show the interior with
slices, clips, contours, streamlines or the Volume representation.

Workflow for visualizing live data:
1. connect_live() - Connect to simulation (optionally with pause=True)
2. get_live_status() - Find the channel names
3. show_live_source("<channel>", color_by="<field>") - Extracts the channel and displays it.
   Pausing first is optional; the simulation keeps running and the data refreshes.
4. After a channel is extracted it behaves like any loaded dataset: the analysis
   tools (slices, contours, vortex detection, statistics) take its name as input.

Alternative: Call set_pause_on_connect() before starting simulation to auto-pause on connect.

The extract step is REQUIRED when paused - it copies data from simulation memory.

The "monitors" channel carries the simulation's scalar histories: residuals, forces and
any case quantities (for example heater power, heat_flux into the fluid, solid_t_max).
For questions like "how hot is it" or "how much heat is leaving", call extract_monitors()
once, then get_current_monitors() and read its "latest" values. For average or accumulated
drag and lift, how the forces changed after steering, the shedding frequency, or whether the
loads are settled, call get_force_statistics() and quote its numbers per operating condition.
The history grows while the simulation runs and changes after every steering change, so call
get_force_statistics() again for each such question; never reuse an earlier result.
To plot forces live, call show_monitor_chart(y_fields=["drag", "lift"], log_scale=False). Field channels (for
example "grid" for the fluid and "solid" for a solid part) are displayed and analyzed
with show_live_source() and the regular tools.

Steering: get_simulation_parameters() lists what can be changed while the simulation
runs (for example Reynolds number or the collision model); set_simulation_parameter()
changes one. Change parameters, pause, resume or step the simulation only when the user asks
for that. Report the requested change, and check the monitors afterwards to show
its effect (for example the reynolds monitor field and the drag and lift response).
A simulation may offer DerivedFields, a text parameter: fields computed on the grid from
VTK calculator expressions (helicity, vorticity components, pressure coefficient, any
quantity the user describes), which then appear on the grid channel to show or analyze.

Two places to compute: in ParaView (show_vortices, slices, calculators) after the full grid
is transferred, which is flexible; or in the simulation, which sends less data. When the
user asks for something computed "in the solver" or "in situ", use the simulation: a new
field goes into DerivedFields (keep the entries already there, separated by ';', and use
@cells for expressions with curl, grad, div or qcrit); a channel other than the grid and
monitors (for example "vortices") is an extract the simulation already computed, shown
with show_live_source(). An extract carries the grid's fields, derived ones included, so a
new derived field can color it. Results report data_size_kb: compare it with the grid's when
the user asks what was transferred.

Other tools:
- resume_simulation() - Continue after analysis
- step_simulation(count=5) - Advance N iterations then auto-pause
- set_breakpoint(iteration=100) - Pause when iteration is reached
- clear_breakpoint() - Remove active breakpoint
- extract_monitors("monitors") - Get residual data
- show_monitor_chart() - Live chart of residuals, or of chosen monitors such as drag and lift
- get_force_statistics() - Time-averaged forces and shedding per operating condition
"""
        
        base_mcp["tools"] = tools
        return base_mcp
