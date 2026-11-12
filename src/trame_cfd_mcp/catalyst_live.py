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

    # A running simulation that sends no new step for this long is reported as stalled.
    LIVE_STALL_SECONDS = 30
    
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
        self._step_seen = (None, 0.0)

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
    STATE_MONITORS = ("reynolds", "collision", "power", "stiffness")

    @classmethod
    def is_residual(cls, name: str) -> bool:
        return bool(cls.RESIDUAL_PATTERN.match(name))

    def default_chart_fields(self, fields) -> list:
        """Residuals that carry values; without them, the simulation's own monitors."""
        def has_values(name):
            return any(v == v for v in self._monitor_history.get(name, [])[-200:])
        residuals = [f for f in fields if self.is_residual(f) and has_values(f)]
        if residuals:
            return residuals
        skip = {"iteration", "time", "reduced_velocity", "derived_error", *self.STATE_MONITORS}
        return [f for f in fields if f not in skip and not self.is_residual(f) and has_values(f)]

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
                result["tip"] = "Simulation paused. get_live_status() lists the channels to extract."
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
                    else:
                        outcome = next((p.get("outcome") for p in self.get_simulation_parameters().get("parameters", [])
                                        if p.get("name") == name), None)
                        result["status"] = "not_applied"
                        result["outcome"] = outcome
                        result["note"] = ("The fields did not arrive. If outcome reports an error, correct the "
                                          "expression and set it again; do not step or pause the simulation.")
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
                    "note": "The simulation applies this at its next Catalyst update and keeps "
                            "running; its effect builds up in the monitors over the following updates."}
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

    def live_step(self):
        """The link's latest timestep, and the seconds since it last changed while the run was not paused."""
        import time
        link = getattr(self._live_link, "SMProxy", self._live_link)
        step = link.GetTimeStep()
        now = time.time()
        paused = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
        if paused or step != self._step_seen[0]:
            self._step_seen = (step, now)
        return step, now - self._step_seen[1]

    def get_live_status(self) -> dict:
        """Get the live simulation's step, pause state and the names of its data channels."""
        if not self._live_link:
            return {"status": "not_connected"}

        try:
            paused = self._live_link.GetProperty('SimulationPaused').GetElement(0) == 1
            step, quiet = self.live_step()
            result = {"status": "connected", "step": step, "paused": paused,
                      "seconds_since_last_update": round(quiet),
                      "channels": self.live_channels(),
                      "extracted": list(self._extracted_sources)}
            if not paused and quiet > self.LIVE_STALL_SECONDS:
                result["warning"] = (f"No update from the simulation for {quiet:.0f} s although it is not "
                                     "paused. The run may have stopped or be blocked.")
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def pause_simulation(self) -> dict:
        """Pause the running simulation. Call only when the user asks to pause: every analysis
        tool works while the simulation runs."""
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
    
    def _set_link_breakpoint(self, timestep: int) -> bool:
        """Hand a breakpoint to the simulation, which pauses itself at the first update that
        reaches it (-1 clears it). False when ParaView has no PauseAtTimeStep: the client then
        pauses once it sees the step, which is late by however far the run got meanwhile."""
        prop = self._live_link.GetProperty('PauseAtTimeStep')
        if prop is None:
            return False
        prop.SetElement(0, int(timestep))
        self._live_link.UpdateVTKObjects()
        return True

    def _continue(self):
        """Let the simulation run on, whether the client or a breakpoint paused it."""
        self._live_link.GetProperty('SimulationPaused').SetElement(0, 0)
        self._live_link.UpdateVTKObjects()
        self._live_link.InvokeCommand('LiveChanged')

    def resume_simulation(self) -> dict:
        """Resume a paused simulation, clearing any breakpoint."""
        if not self._live_link:
            return {"error": "Not connected to live simulation"}

        try:
            self._pause_at_iteration = None
            self._set_link_breakpoint(-1)
            self._continue()
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
        exact = bool(self._live_link) and self._set_link_breakpoint(iteration)
        return {
            "status": "breakpoint_set",
            "pause_at": iteration,
            "current_iteration": self._last_iteration,
            "exact": exact,
        }
    
    def clear_breakpoint(self) -> dict:
        """Clear any active breakpoint."""
        was_set = self._pause_at_iteration
        self._pause_at_iteration = None
        if self._live_link:
            self._set_link_breakpoint(-1)
        return {
            "status": "breakpoint_cleared",
            "was_set_at": was_set,
        }
    
    def step_simulation(self, count: int = 1) -> dict:
        """
        Step the simulation forward by a number of iterations, then pause. The simulation
        stays paused afterwards, so call this only when the user asks to step.

        The simulation pauses itself at the first published update at or past
        current_iteration + count, so count=1 advances exactly one update.
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
        try:
            exact = self._set_link_breakpoint(target)
            self._continue()
        except Exception as e:
            return {"status": "error", "message": str(e)}

        print(f"[Live] Stepping from iteration {self._last_iteration} to {target}")
        
        return {
            "status": "stepping",
            "from_iteration": self._last_iteration,
            "to_iteration": target,
            "count": count,
            "exact": exact,
        }
    
    def extract_live_data(self, source_name: str) -> dict:
        """
        Extract data from the live simulation to local ParaView session.
        
        This uses the same mechanism as ParaView GUI's extract button.
        The data is copied from the simulation to the local session.
        
        Args:
            source_name: A channel name from get_live_status()["channels"], such as "grid"
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

            # Live advances the client's timestep only once every extract has received data, so an
            # extract of a channel the simulation does not publish would stop all later updates.
            channels = self.live_channels()
            if source_name not in channels:
                return {"status": "error",
                        "message": f"The simulation does not publish a '{source_name}' channel.",
                        "channels": channels,
                        "tip": "Use one of these channel names."}

            print(f"[extract_live_data] Extracting '{source_name}'")

            previous = simple.GetActiveSource()
            extracted = ExtractCatalystData(self._live_link, source_name)
            try:
                return self._finish_extract(source_name, extracted)
            except Exception:
                self._drop_extract(extracted, previous)
                raise

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _drop_extract(self, proxy, previous=None):
        """Undo a failed extract so the Live link stops asking the simulation for it."""
        if proxy is not None:
            if self._live_link:
                getattr(self._live_link, "SMProxy", self._live_link).RemoveExtract(proxy.SMProxy)
            simple.Delete(proxy)
        simple.SetActiveSource(previous)

    def _finish_extract(self, source_name, extracted) -> dict:
        """Wait for a new extract's first data, register it and describe it."""
        if not extracted:
            return {"status": "error", "message": f"Failed to extract '{source_name}'",
                    "channels": self.live_channels()}
        self._wait_for_data(extracted)
        extracted.UpdatePipeline()

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

        point_fields = list(extracted.PointData.keys()) if hasattr(extracted, 'PointData') else []
        cell_fields = list(extracted.CellData.keys()) if hasattr(extracted, 'CellData') else []
        description = self._describe(extracted)
        self._extracted_sources[source_name] = extracted

        print(f"[extract_live_data] {data_type}: {n_points} pts, {n_cells} cells, "
              f"fields: {point_fields} / {cell_fields}")

        # Update trame app to refresh pipeline browser
        if self._app:
            self._app.update()
            if hasattr(self._app.server.controller, 'on_data_change'):
                self._app.server.controller.on_data_change()

        return {
            "status": "extracted",
            "source": source_name,
            **description,
            "points": n_points,
            "cells": n_cells,
            "point_fields": point_fields,
            "cell_fields": cell_fields,
            "tip": "Data extracted. Use show_live_source() to visualize."
        }

    def show_live_source(self, source_name: str, color_by: str | None = None,
                         show_with: list[str] | str | None = None) -> dict:
        """
        Show a live source in the render view, hiding everything else.

        Automatically extracts the data first if not already extracted.

        Args:
            source_name: Name of the source to show (e.g., "grid")
            color_by: Optional field name to color by
            show_with: Other channels to keep visible with it, for example a body such as
                "wing" or "solid" shown with the colored "grid"
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
        
        companions = [show_with] if isinstance(show_with, str) else list(show_with or [])
        shown_with = []
        for name in companions:
            if name not in self._extracted_sources and self._live_link and name in self.live_channels():
                if self.extract_live_data(name).get("status") == "error":
                    continue
            other = self._extracted_sources.get(name) or simple.FindSource(name)
            if other is not None and other is not source:
                shown_with.append((name, other))

        try:
            view = simple.GetActiveView()
            keep = {id(source)} | {id(other) for _, other in shown_with}
            for other in simple.GetSources().values():
                if id(other) not in keep:
                    simple.Hide(other, view)
            for _, other in shown_with:
                simple.Show(other, view)
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
            info = source.GetDataInformation().DataInformation
            bounds = info.GetBounds()
            volume = not info.HasDataSetType(0) and all(bounds[2 * i + 1] > bounds[2 * i] for i in range(3))
            if volume and not info.HasDataSetType(4) or not hasattr(self._workflow_mcp, "_workflows"):
                simple.ResetCamera(view)
            else:
                self._workflow_mcp._workflows._frame_body(view, pad=0.1, direction="iso", target=source)
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
                "shown_with": [name for name, _ in shown_with],
                **self._describe(source),
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    @staticmethod
    def _sm(item):
        item = getattr(item, "Proxy", item)
        return getattr(item, "SMProxy", item)

    def _delete_with_consumers(self, proxy) -> list:
        """Delete proxy and every filter built on it; the names removed, consumers first."""
        removed = []
        for (name, _), other in list(simple.GetSources().items()):
            if other is proxy:
                continue
            inputs = []
            for key in ("Input", "SeedSource", "Source"):
                if key in other.ListProperties():
                    value = other.GetPropertyValue(key)
                    inputs += value if isinstance(value, (list, tuple)) else [value]
            if any(item is not None and self._sm(item) is self._sm(proxy) for item in inputs):
                removed += self._delete_with_consumers(other)
        names = [name for (name, _), p in simple.GetSources().items() if p is proxy]
        simple.Delete(proxy)
        return removed + names

    def release_live_source(self, source_name: str) -> dict:
        """Stop transferring a live channel: remove its extract and the filters built on it.

        Every extracted channel is sent on each Live update whether it is shown or not, so
        release the full grid when switching to a leaner channel."""
        proxy = self._extracted_sources.get(source_name)
        if proxy is None:
            return {"error": f"'{source_name}' is not extracted", "extracted": list(self._extracted_sources)}
        if proxy is self._monitor_source:
            return {"error": "The monitors channel stays extracted for the charts and force statistics."}
        size = proxy.GetDataInformation().DataInformation.GetMemorySize()
        if self._live_link:
            getattr(self._live_link, "SMProxy", self._live_link).RemoveExtract(proxy.SMProxy)
        removed = self._delete_with_consumers(proxy)
        del self._extracted_sources[source_name]
        if self._app:
            self._app.update()
            if hasattr(self._app.server.controller, "on_data_change"):
                self._app.server.controller.on_data_change()
        return {"status": "released", "source": source_name, "no_longer_sent_kb": size,
                "removed": removed, "still_extracted": list(self._extracted_sources)}

    def use_live_channel(self, channel: str) -> dict:
        """Switch the analysis to one live field channel, for example from the full "grid" to a
        leaner one: extract it and release the other extracted field channels so they stop
        transferring (the monitors stay). show_vortices() and the other analysis tools then read
        this channel. Reports what each update now sends and what was released."""
        if not self._live_link:
            return {"error": "Not connected. Call connect_live() first."}
        result = self.extract_live_data(channel)
        if "error" in result or result.get("status") == "error":
            return result
        keep = {channel, "derived_status"}
        released = {}
        for name in list(self._extracted_sources):
            if name in keep or self._extracted_sources[name] is self._monitor_source:
                continue
            outcome = self.release_live_source(name)
            if outcome.get("status") == "released":
                released[name] = outcome["no_longer_sent_kb"]
        source = self._extracted_sources[channel]
        result = {"status": "switched", "channel": channel,
                  "sent_kb_per_update": source.GetDataInformation().DataInformation.GetMemorySize(),
                  "released_kb_per_update": released,
                  "point_fields": list(source.PointData.keys()), "cell_fields": list(source.CellData.keys()),
                  "tip": "Analysis tools now read this channel."}
        from paraview import servermanager
        view = simple.GetActiveView()
        reps = (servermanager.GetRepresentation(p, view) for p in simple.GetSources().values())
        visible = any(rep.Visibility for rep in reps if rep is not None)
        workflows = getattr(self._workflow_mcp, "_workflows", None)
        if not visible and workflows is not None and "q_criterion" in result["cell_fields"] + result["point_fields"]:
            # Releasing the old channel removed what was on screen: show this channel's vortices.
            shown = workflows.show_vortices(method="q_criterion", color_by="speed")
            result["shown"] = {key: shown.get(key) for key in ("status", "proxy_name", "result", "error") if key in shown}
            result["tip"] = "The view now shows q_criterion vortices contoured from this channel."
        return result

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
            channels = self.live_channels()
            if channel_name not in channels:
                return {"status": "error",
                        "message": f"The simulation does not publish a '{channel_name}' channel.",
                        "channels": channels}
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
                           log_scale: bool | None = None) -> dict:
        """
        Show a live chart of monitor histories in the right drawer; it updates as the solver steps.

        Args:
            x_field: Field for the x axis (default: "iteration").
            y_fields: Monitor fields to plot (default: the residuals).
            log_scale: Logarithmic y axis (default: on when every plotted field is a residual).
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        
        try:
            self._monitor_source.UpdatePipeline()
            available_fields = self._field_names(self._monitor_source)
            info = self._monitor_source.GetDataInformation().DataInformation
            n_points = info.GetNumberOfRows() or info.GetNumberOfPoints()
            
            # Store config (used by get_monitor_data)
            fields = y_fields or self.default_chart_fields(available_fields)
            if log_scale is None and fields:
                log_scale = all(self.is_residual(f) for f in fields)
            self._chart_config = {
                'x_field': x_field,
                'y_fields': fields or None,
                'log_scale': log_scale
            }
            if self._app and hasattr(self._app, 'state'):
                self._app.state.analysis_chart_active = False
                self._app.state.chart_drawer_open = True
            
            return {
                "status": "chart_ready",
                "message": "The chart panel shows the live monitors",
                "plotted": fields,
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
        drift between the last two quarters (settled when under 2 percent over at least 20 samples
        and two shedding periods). The shedding period
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
                    "settled": drift is not None and drift < 0.02 and len(settled) >= max(20, 2 * cycle),
                    "drift_fraction": None if drift is None else r(drift),
                }
            if period:
                entry["shedding_period_iterations"] = r(period)
                if "time" in columns:
                    t = [columns["time"][i] for i in half]
                    p_time = self._shedding_period(t, [columns[lift][i] for i in half])
                    if p_time:
                        entry["strouhal_number"] = r(1.0 / p_time)
            elif lift and len(idx) >= 4:
                entry["shedding_note"] = ("Fewer than three lift cycles in the second half of this condition, so "
                                          "there is no shedding period or Strouhal number yet; ask again after "
                                          "the run has gone further.")
            conditions.append(entry)

        return {
            "status": "ok",
            "fields": fields,
            "conditions": conditions,
            "note": "One entry per operating condition, oldest first. A condition that is not settled "
                    "needs more iterations before its mean can be quoted as final. These numbers are a "
                    "snapshot: call again after steering or for any later question.",
        }

    def get_oscillation_statistics(self, field: str, cycles: int = 4) -> dict:
        """Amplitude, period and growth of an oscillating monitor, one entry per operating condition.

        Use this for whether a motion or signal is growing, decaying or steady (for example flutter:
        field="pitch" or "plunge"), its amplitude and its frequency. Each cycle runs between upward
        crossings of the condition's late mean; the amplitude of a cycle is half its peak-to-peak.
        Growth is the ratio of successive cycle amplitudes over the last ``cycles`` cycles: above 1.05
        "growing", below 0.95 "decaying", otherwise "sustained": the amplitude holds. Each condition
        also reports the amplitude it started from (the previous condition's last cycle). A
        sustained oscillation that grew to that amplitude in this condition is a limit cycle; for a
        moving structure such as a wing on springs, that is flutter at a steady amplitude.

        Args:
            field: Monitor name, for example "pitch".
            cycles: How many of the most recent cycles to measure (default 4).
        """
        import math

        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        try:
            columns = self._monitor_columns()
        except Exception as e:
            return {"status": "error", "message": str(e)}
        if field not in columns:
            return {"error": f"No monitor named {field!r}", "available": sorted(columns)}
        iterations = columns["iteration"]
        state = [name for name in self.STATE_MONITORS if name in columns]
        starts = [0] + [i for i in range(1, len(iterations))
                        if any(columns[name][i] != columns[name][i - 1] for name in state)]

        def r(v):
            return float(f"{v:.4g}")

        conditions = []
        entering = None
        for k, start in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(iterations)
            x = iterations[start:end]
            y = columns[field][start:end]
            entry = {"iterations": [x[0], x[-1]], "samples": len(x)}
            entry.update({name: r(columns[name][start]) for name in state})
            if entering is not None:
                entry["amplitude_entering"] = r(entering)
            late = y[len(y) // 2:]
            mean = sum(late) / len(late) if late else 0.0
            ups = [i for i in range(1, len(y)) if y[i - 1] < mean <= y[i]]
            spans = [(ups[j], ups[j + 1]) for j in range(len(ups) - 1)]
            amps = [(max(y[a:b + 1]) - min(y[a:b + 1])) / 2 for a, b in spans]
            if len(amps) < 2:
                entry["note"] = "fewer than two complete cycles in this condition"
                entry["latest_value"] = r(y[-1])
                if amps:
                    entry["amplitude_latest_cycle"] = r(amps[-1])
                    entering = amps[-1]
                conditions.append(entry)
                continue
            recent = amps[-cycles:]
            ratios = [recent[j + 1] / recent[j] for j in range(len(recent) - 1) if recent[j] > 1e-12]
            growth = math.exp(sum(math.log(v) for v in ratios) / len(ratios)) if ratios else 1.0
            period = (x[spans[-1][1]] - x[spans[-len(recent)][0]]) / len(recent)
            entry.update({
                "complete_cycles": len(amps),
                "amplitude_latest_cycle": r(amps[-1]),
                "amplitude_first_cycle": r(amps[0]),
                "mean": r(mean),
                "period_iterations": r(period),
                "growth_per_cycle": r(growth),
                "trend": "growing" if growth > 1.05 else ("decaying" if growth < 0.95 else "sustained"),
            })
            grew = amps[-1] > 1.5 * amps[0] or (entering is not None and amps[-1] > 2.0 * entering)
            entering = amps[-1]
            if entry["trend"] == "sustained" and grew:
                entry["limit_cycle"] = True
                entry["meaning"] = ("The oscillation grew in this condition and now holds its amplitude: a limit "
                                    "cycle. For a structure on springs this is flutter, held at a steady amplitude "
                                    "by a nonlinearity.")
            if "time" in columns:
                tt = columns["time"][start:end]
                entry["period_in_time_column"] = r((tt[spans[-1][1]] - tt[spans[-len(recent)][0]]) / len(recent))
            conditions.append(entry)
        return {"status": "ok", "field": field, "conditions": conditions,
                "note": "One entry per operating condition, oldest first; the last is the current one. "
                        "period_in_time_column is in the unit of the monitors' time column, which the "
                        "simulation defines (often a convective time such as chord transits, not seconds). "
                        "Call again for any later question: the run keeps going."}

    def get_thermal_statistics(self) -> dict:
        """Heat balance, peak temperature and thermal resistance from the monitor history, one entry per operating condition.

        Use this for whether a heated part has reached thermal steady state, how hot it runs, its
        thermal resistance, or how these changed after the heater power or the flow was steered.
        Needs the monitors power (heat input), heat_flux (heat into the fluid) and solid_t_max.

        The history is split wherever a steered parameter (power, reynolds, collision) changes. For
        each condition it reports the settled means (second half of the condition) of heat_flux,
        solid_t_max and solid_t_mean, the energy balance heat_flux / power, and the thermal
        resistance (solid_t_max - t_ambient) / power: the peak temperature rise above the inflow air
        per unit power, in K/W when the simulation publishes SI units.
        A quantity is settled when it drifts under 1 percent between the last two quarters.
        """
        if not self._monitor_source:
            return {"error": "No monitor data. Call extract_monitors() first."}
        try:
            columns = self._monitor_columns()
        except Exception as e:
            return {"status": "error", "message": str(e)}
        needed = ["power", "heat_flux", "solid_t_max"]
        missing = [name for name in needed if name not in columns]
        iterations = columns.get("iteration", [])
        if missing or len(iterations) < 4:
            return {"error": "No thermal history to analyze", "missing": missing, "available": sorted(columns)}
        fields = [name for name in ("heat_flux", "solid_t_max", "solid_t_mean") if name in columns]
        state = [name for name in self.STATE_MONITORS if name in columns]
        starts = [0] + [i for i in range(1, len(iterations))
                        if any(columns[name][i] != columns[name][i - 1] for name in state)]

        def r(v):
            return float(f"{v:.4g}")

        conditions = []
        for k, start in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(iterations)
            idx = list(range(start, end))
            entry = {"iterations": [iterations[start], iterations[end - 1]], "samples": len(idx)}
            entry.update({name: r(columns[name][start]) for name in state})
            if len(idx) < 8:
                entry["note"] = "transitional: too few samples to judge"
                conditions.append(entry)
                continue
            half = idx[len(idx) // 2:]
            q = len(half) // 2
            settled_all = True
            means = {}
            for name in fields:
                values = [columns[name][i] for i in half]
                mean = sum(values) / len(values)
                a = sum(values[:q]) / q
                b = sum(values[q:]) / (len(values) - q)
                drift = abs(b - a) / max(abs(mean), 1e-12)
                settled = drift < 0.01 and len(half) >= 10
                settled_all &= settled
                means[name] = mean
                entry[name] = {"settled_mean": r(mean), "latest": r(columns[name][end - 1]),
                               "settled": settled, "drift_fraction": r(drift)}
            power = columns["power"][end - 1]
            ambient = columns["t_ambient"][end - 1] if "t_ambient" in columns else 0.0
            if "t_ambient" in columns:
                entry["peak_rise_above_inflow"] = r(means["solid_t_max"] - ambient)
            if power:
                entry["energy_balance"] = r(means["heat_flux"] / power)
                entry["thermal_resistance"] = r((means["solid_t_max"] - ambient) / power)
            entry["thermal_steady_state"] = settled_all and abs(entry.get("energy_balance", 0) - 1) < 0.02
            conditions.append(entry)

        si = "t_ambient" in columns
        return {
            "status": "ok",
            "conditions": conditions,
            "units": ("SI: temperatures in degC (t_ambient is the inflow air), power and heat_flux in W, "
                      "peak_rise_above_inflow in K, thermal_resistance in K/W." if si else
                      "Lattice units: temperatures are rises above the inflow air, power and heat_flux are "
                      "heat per step. Quote them as given, without physical units such as W or K."),
            "note": "One entry per operating condition, oldest first. Thermal steady state means the heat "
                    "leaving into the air matches the heater power and the temperatures have stopped "
                    "rising. Call again after steering or for any later question.",
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
            source = self._extracted_sources.get(proxy_name or "") or (proxy_name and simple.FindSource(proxy_name))
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
        import os
        if os.environ.get("CFD_MCP_VIEW_CRITIC", "1") == "0":
            # Without a vision endpoint the critic only repeats computable checks; leave it out.
            tools = [tool for tool in tools if getattr(tool, "__name__", "") != "inspect_view"]
            base_mcp["instructions"] = re.sub(r"== LOOK AND CORRECT ==.*?(?=KEEP RESPONSES CONCISE)", "",
                                              base_mcp["instructions"], flags=re.S)
        
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
                self.get_oscillation_statistics,
                self.get_thermal_statistics,
                self.release_live_source,
                self.use_live_channel,
            ])
            
            base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

A live simulation publishes named data channels. get_live_status() lists them
in "channels" (for example "grid" for the flow field and "monitors" for residuals
and forces). Use those names; never assume "surface" or "volume". Each channel is
one dataset: a request for "the live volume" or "the flow field" means the fluid
grid channel. Any other channel in that list is a separate dataset, and only the
listed names can be extracted: a body surface or a solid exists only when its
channel is listed. A 3D grid shown as a Surface displays only its outer faces,
so show the interior with slices, clips, contours, streamlines or the Volume
representation.

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
For a heated part (power, heat_flux and solid_t_max monitors), questions about thermal steady
state, how hot it runs, thermal resistance or the response to a power change go to
get_thermal_statistics(), called fresh each time; quote its values in the units it reports
(SI or lattice units), and never add units it does not report. Chart the heat balance with
show_monitor_chart(y_fields=["power", "heat_flux"], log_scale=False) and temperatures with
show_monitor_chart(y_fields=["solid_t_max", "solid_t_mean"], log_scale=False).
For a structure that moves (pitch and plunge monitors, a fluttering wing), questions about
whether it is fluttering, growing, decaying or steady, its amplitude or frequency go to
get_oscillation_statistics(field="pitch"), called fresh each time; chart the motion with
show_monitor_chart(y_fields=["pitch"], log_scale=False).
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
@cells for expressions with curl, grad, div or qcrit).
Channels: "grid" is the full flow field. A "lean" channel is the same grid with only speed and
the fields the solver computed (q_criterion and the steered derived fields). To switch to a
channel ("switch to", "use the lean channel"), call use_live_channel(channel) first, never
show_live_source(): it also releases the full grid, then show_vortices() contours its
precomputed q_criterion instead of differentiating velocity. A channel such as "vortices" is a surface the simulation extracted
itself, shown with show_live_source(): the smallest transfer, but it refreshes less often and
costs solver time. Every extracted channel is sent on each update, shown or not, which is why
use_live_channel() releases the others. Results
report data_size_kb: compare the channels' sizes when the user asks what was transferred.

Other tools:
- resume_simulation() - Continue after analysis
- step_simulation(count=5) - Advance N iterations then auto-pause
- set_breakpoint(iteration=100) - Pause when iteration is reached
- clear_breakpoint() - Remove active breakpoint
- extract_monitors("monitors") - Get residual data
- show_monitor_chart() - Live chart of residuals, or of chosen monitors such as drag and lift
- get_force_statistics() - Time-averaged forces and shedding per operating condition
- get_oscillation_statistics(field) - Amplitude, period and growth of an oscillating monitor
- get_thermal_statistics() - Heat balance, peak temperature and thermal resistance per operating condition
"""
        
        base_mcp["tools"] = tools
        return base_mcp
