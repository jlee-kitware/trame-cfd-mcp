"""
Shared test utilities for CFD assistant tests.
"""
import json
import os
from trame_llm.core import ProgressType


class ResultCollector:
    """Collects tool results and provides progress callback."""
    
    def __init__(self, truncate_console: int = 400):
        self.results = []
        self.truncate_console = truncate_console
    
    def progress_callback(self, ptype, msg):
        """Progress callback that collects results and prints to console."""
        if ptype == ProgressType.MCP_SELECTION:
            print(f"[call] {msg}")
        elif ptype == ProgressType.MCP:
            # Save full result
            try:
                result = json.loads(msg)
                self.results.append(result)
            except json.JSONDecodeError:
                self.results.append({"raw": msg})
            
            # Print truncated
            if self.truncate_console and len(msg) > self.truncate_console:
                msg = msg[:self.truncate_console] + "..."
            print(f"[result] {msg}")
        elif ptype == ProgressType.MCP_ERROR:
            print(f"[ERROR] {msg}")
        elif ptype == ProgressType.LLM_RESPONSE:
            print(f"[llm] {msg}")
        elif ptype == ProgressType.MAX_ITERATION:
            print(f"[LIMIT] {msg}")
        elif ptype == ProgressType.ERROR:
            print(f"[ERROR] {msg}")
    
    def save_json(self, filename: str):
        """Save collected results to JSON file."""
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(self.results)} tool results to {filename}")
    
    def clear(self):
        """Clear collected results."""
        self.results = []


class MinimalApp:
    """Minimal app interface for ParaViewMCP."""
    
    def update(self):
        from paraview import simple
        simple.Render()
    
    def reset_camera(self):
        from paraview import simple
        simple.ResetCamera()
    
    class ctrl:
        class on_active_proxy_change:
            @staticmethod
            def exists(): return False
        class on_data_change:
            @staticmethod
            def exists(): return False
