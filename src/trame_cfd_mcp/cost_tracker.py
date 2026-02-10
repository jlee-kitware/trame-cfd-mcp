# -*- coding: utf-8 -*-
"""
Cost tracking for LLM usage.

Provides TrackedLLMClient that extends trame-llm's LLMClient with cost tracking.
"""

from dataclasses import dataclass
from typing import Optional
import json

# Pricing per 1M tokens (as of early 2025, update as needed)
MODEL_PRICING = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-5-mini": {"input": 0.15, "output": 0.60},  # Assuming same as 4o-mini
    # Anthropic
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    # Default fallback
    "default": {"input": 1.00, "output": 3.00},
}


@dataclass
class UsageStats:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    
    def add(self, input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0):
        """Add usage from a single request."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.tool_calls += tool_calls
        self.llm_calls += 1
    
    def cost(self, model: str) -> float:
        """Calculate cost in USD for given model."""
        # Normalize model name
        model_key = model.lower() if model else "default"
        for key in MODEL_PRICING:
            if key in model_key:
                pricing = MODEL_PRICING[key]
                break
        else:
            pricing = MODEL_PRICING["default"]
        
        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
    
    def reset(self):
        """Reset all counters."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.tool_calls = 0
        self.llm_calls = 0


class TrackedLLMClient:
    """
    LLMClient wrapper with cost tracking.
    
    Usage:
        from paraview_llm import TrackedLLMClient
        
        llm = TrackedLLMClient(max_iteractions=10)
        llm.set_progress_handler(callback)
        llm.register_mcp(mcp)
        await llm.initialize()
        
        await llm.process_prompt("...")
        
        llm.print_report()
    """
    
    def __init__(self, **kwargs):
        from trame_llm.core import LLMClient
        self._llm = LLMClient(**kwargs)
        self.stats = UsageStats()
        self._user_handler = None
    
    @property
    def tools(self):
        return self._llm.tools
    
    @property
    def config(self):
        return self._llm.config
    
    def set_progress_handler(self, handler):
        """Set progress handler (will be wrapped for tracking)."""
        from trame_llm.core import ProgressType
        self._user_handler = handler
        
        def tracking_handler(ptype, msg):
            # Count tool calls
            if ptype == ProgressType.MCP_SELECTION:
                self.stats.tool_calls += 1
            # Forward to user handler
            if self._user_handler:
                self._user_handler(ptype, msg)
        
        self._llm.set_progress_handler(tracking_handler)
    
    def register_mcp(self, mcp):
        """Register MCP controller."""
        self._llm.register_mcp(mcp)
    
    async def initialize(self):
        """Initialize the client."""
        await self._llm.initialize()
    
    async def process_prompt(self, prompt: str):
        """Process a prompt and track usage."""
        # Monkey-patch log_response to capture usage
        original_log = self._llm.log_response
        
        def tracking_log(response):
            # Extract usage if available
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                input_tokens = getattr(usage, 'input_tokens', 0) or getattr(usage, 'prompt_tokens', 0) or 0
                output_tokens = getattr(usage, 'output_tokens', 0) or getattr(usage, 'completion_tokens', 0) or 0
                self.stats.add(input_tokens, output_tokens)
            original_log(response)
        
        self._llm.log_response = tracking_log
        
        try:
            result = await self._llm.process_prompt(prompt)
            return result
        finally:
            self._llm.log_response = original_log
    
    def report(self) -> str:
        """Generate a cost report string."""
        model = self.config.model if self.config else "unknown"
        cost = self.stats.cost(model)
        
        lines = [
            "",
            "=" * 50,
            "COST REPORT",
            "=" * 50,
            f"Model: {model}",
            f"LLM calls: {self.stats.llm_calls}",
            f"Tool calls: {self.stats.tool_calls}",
            f"Input tokens: {self.stats.input_tokens:,}",
            f"Output tokens: {self.stats.output_tokens:,}",
            f"Total tokens: {self.stats.total_tokens:,}",
            f"Estimated cost: ${cost:.6f}",
            "=" * 50,
        ]
        return "\n".join(lines)
    
    def print_report(self):
        """Print cost report to stdout."""
        print(self.report())
    
    def summary(self) -> dict:
        """Return summary as dict."""
        model = self.config.model if self.config else "unknown"
        return {
            "model": model,
            "llm_calls": self.stats.llm_calls,
            "tool_calls": self.stats.tool_calls,
            "input_tokens": self.stats.input_tokens,
            "output_tokens": self.stats.output_tokens,
            "total_tokens": self.stats.total_tokens,
            "cost_usd": self.stats.cost(model),
        }
