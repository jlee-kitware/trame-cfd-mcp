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
        self.tool_calls = []
        self.truncate_console = truncate_console
        self._current_test = None
        self._tests = {}  # test_name -> {tool_calls, results, screenshots}
    
    def start_test(self, name: str, prompt: str):
        """Start tracking a new test."""
        self._current_test = name
        self._tests[name] = {
            "prompt": prompt,
            "tool_calls": [],
            "results": [],
            "screenshots": [],
            "llm_responses": []
        }
    
    def progress_callback(self, ptype, msg):
        """Progress callback that collects results and prints to console."""
        if ptype == ProgressType.MCP_SELECTION:
            # Extract tool name from "Calling: tool_name"
            if msg.startswith("Calling: "):
                tool_name = msg.replace("Calling: ", "").strip()
                self.tool_calls.append(tool_name)
                if self._current_test:
                    self._tests[self._current_test]["tool_calls"].append(tool_name)
            print(f"[call] {msg}")
        elif ptype == ProgressType.MCP:
            # Save full result
            try:
                result = json.loads(msg)
                self.results.append(result)
                if self._current_test:
                    self._tests[self._current_test]["results"].append(result)
                    # Track screenshots
                    if result.get("status") == "saved" and "filename" in result:
                        self._tests[self._current_test]["screenshots"].append(result["filename"])
            except json.JSONDecodeError:
                self.results.append({"raw": msg})
                if self._current_test:
                    self._tests[self._current_test]["results"].append({"raw": msg})
            
            # Print truncated
            if self.truncate_console and len(msg) > self.truncate_console:
                msg = msg[:self.truncate_console] + "..."
            print(f"[result] {msg}")
        elif ptype == ProgressType.MCP_ERROR:
            print(f"[ERROR] {msg}")
        elif ptype == ProgressType.LLM_RESPONSE:
            # Save LLM responses (the explanations/interpretations)
            if self._current_test:
                self._tests[self._current_test]["llm_responses"].append(msg)
            print(f"[llm] {msg}")
        elif ptype == ProgressType.MAX_ITERATION:
            print(f"[LIMIT] {msg}")
        elif ptype == ProgressType.ERROR:
            print(f"[ERROR] {msg}")
    
    def get_tool_names(self) -> list:
        """Return list of tool names called in current test."""
        if self._current_test:
            return self._tests[self._current_test]["tool_calls"]
        return self.tool_calls
    
    def get_screenshots(self) -> list:
        """Return list of screenshots saved in current test."""
        if self._current_test:
            return self._tests[self._current_test]["screenshots"]
        return []
    
    def save_json(self, filename: str):
        """Save collected results to JSON file."""
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({
                "tests": self._tests,
                "summary": {
                    "total_tool_calls": len(self.tool_calls),
                    "total_results": len(self.results)
                }
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(self._tests)} test results to {filename}")
    
    def clear(self):
        """Clear current test tracking (for legacy compatibility)."""
        self._current_test = None


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
