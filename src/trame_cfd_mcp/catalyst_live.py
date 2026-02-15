"""
Catalyst Live integration for trame-cfd-mcp.

Connects to a running simulation via ParaView's Live connection,
enabling real-time monitoring and analysis through the LLM chat interface.

Usage:
    # In cfd_chat.py or standalone:
    from trame_cfd_mcp.catalyst_live import CatalystLiveSource
    
    live = CatalystLiveSource(host="localhost", port=22222)
    live.connect()
    
    # Now the live data appears as a source in ParaView
    # LLM can analyze it like any other data
"""

from paraview import simple


class CatalystLiveSource:
    """
    Connect to a Catalyst-enabled simulation for live visualization.
    
    The simulation must be running with Catalyst and configured to
    accept Live connections (typically via catalyst_pipeline.py with
    a coprocessor that calls EnableLive()).
    """
    
    def __init__(self, host: str = "localhost", port: int = 22222):
        """
        Initialize live source configuration.
        
        Args:
            host: Hostname where simulation is running
            port: Catalyst Live port (default 22222)
        """
        self.host = host
        self.port = port
        self._connection = None
        self._extractor = None
    
    def connect(self) -> dict:
        """
        Connect to the running simulation.
        
        Returns:
            Dict with connection status and available data
        """
        try:
            # Create the Live connection
            self._connection = simple.ConnectCatalystLive(self.host, self.port)
            
            if self._connection is None:
                return {
                    "status": "error",
                    "message": f"Could not connect to {self.host}:{self.port}"
                }
            
            # Get the live source
            self._extractor = simple.GetActiveSource()
            
            return {
                "status": "connected",
                "host": self.host,
                "port": self.port,
                "source_name": self._extractor.GetGlobalIDAsString() if self._extractor else None,
                "tip": "Live data is now available. Use list_data() to see it."
            }
            
        except Exception as e:
            return {
                "status": "error", 
                "message": str(e)
            }
    
    def disconnect(self) -> dict:
        """Disconnect from the simulation."""
        try:
            if self._connection:
                simple.Disconnect()
                self._connection = None
                self._extractor = None
            return {"status": "disconnected"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_timestep_info(self) -> dict:
        """Get current timestep information from the simulation."""
        if not self._extractor:
            return {"status": "error", "message": "Not connected"}
        
        try:
            info = self._extractor.GetDataInformation()
            time = info.GetTime() if info else None
            
            return {
                "status": "ok",
                "time": time,
                "timestep": simple.GetAnimationScene().TimeKeeper.Time,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def pause_simulation(self) -> dict:
        """Request the simulation to pause (if steering enabled)."""
        # This requires Catalyst steering support in the simulation
        try:
            simple.PauseCatalyst()
            return {"status": "paused"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def resume_simulation(self) -> dict:
        """Request the simulation to resume."""
        try:
            simple.ResumeCatalyst()
            return {"status": "resumed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class CatalystLiveMCP:
    """
    MCP wrapper for Catalyst Live functionality.
    
    Add this to the MCP chain to enable live simulation monitoring:
    
        base_mcp = ParaViewMCP(app)
        workflow_mcp = WorkflowMCP(base_mcp)
        live_mcp = CatalystLiveMCP(workflow_mcp)
        llm_client.register_mcp(live_mcp)
    """
    
    def __init__(self, base_mcp, host: str = "localhost", port: int = 22222):
        self._base_mcp = base_mcp
        self._live = CatalystLiveSource(host, port)
        self._connected = False
    
    def connect_live(self, host: str = None, port: int = None) -> dict:
        """
        Connect to a running Catalyst-enabled simulation.
        
        Args:
            host: Hostname (default: localhost)
            port: Port number (default: 22222)
            
        Returns:
            Connection status and available data info
        """
        if host:
            self._live.host = host
        if port:
            self._live.port = port
            
        result = self._live.connect()
        self._connected = result.get("status") == "connected"
        return result
    
    def disconnect_live(self) -> dict:
        """Disconnect from the simulation."""
        result = self._live.disconnect()
        self._connected = False
        return result
    
    def get_live_status(self) -> dict:
        """
        Get current status of the live connection.
        
        Returns timestep, simulation time, and connection state.
        """
        if not self._connected:
            return {"status": "not_connected"}
        
        return self._live.get_timestep_info()
    
    def pause_simulation(self) -> dict:
        """
        Pause the running simulation.
        
        Requires Catalyst steering support in the simulation.
        """
        return self._live.pause_simulation()
    
    def resume_simulation(self) -> dict:
        """Resume a paused simulation."""
        return self._live.resume_simulation()
    
    @property
    def mcp(self) -> dict:
        """Return MCP declaration with live tools added."""
        base_mcp = self._base_mcp.mcp
        
        # Add live connection tools
        base_mcp["tools"] = list(base_mcp["tools"]) + [
            self.connect_live,
            self.disconnect_live,
            self.get_live_status,
            self.pause_simulation,
            self.resume_simulation,
        ]
        
        # Update instructions
        base_mcp["instructions"] += """

== LIVE SIMULATION MONITORING ==

You can connect to running Catalyst-enabled simulations:

- connect_live(host, port) - Connect to simulation
- disconnect_live() - Disconnect
- get_live_status() - Get current timestep/time
- pause_simulation() - Pause for detailed analysis
- resume_simulation() - Continue simulation

Once connected, live data appears as a source. Use show_* tools normally.
"""
        
        return base_mcp
