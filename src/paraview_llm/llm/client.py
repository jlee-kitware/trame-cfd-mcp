"""
LLM Client - supports OpenAI and Anthropic

Default: OpenAI (consistent with trame-llm)
"""

import json
import os
from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """Abstract base for LLM clients"""
    
    @abstractmethod
    def complete(self, prompt: str, schema: dict | None = None) -> dict:
        """
        Send prompt to LLM and get structured response.
        
        Args:
            prompt: The full prompt text
            schema: Optional JSON schema for structured output
            
        Returns:
            Parsed JSON response from LLM
        """
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI-compatible client (works with OpenAI, Llama, etc.)"""
    
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        from openai import OpenAI
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASEURL", "https://api.openai.com/v1")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o")
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
    
    def complete(self, prompt: str, schema: dict | None = None) -> dict | str:
        messages = [{"role": "user", "content": prompt}]
        
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        
        # Use JSON mode if schema provided
        if schema:
            kwargs["response_format"] = {"type": "json_object"}
        
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        
        if schema:
            return json.loads(content)
        return content


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude client"""
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        from anthropic import Anthropic
        
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        
        self.client = Anthropic(api_key=self.api_key)
    
    def complete(self, prompt: str, schema: dict | None = None) -> dict | str:
        # Add JSON instruction if schema provided
        if schema:
            prompt = f"{prompt}\n\nRespond with valid JSON only, no other text."
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        
        content = response.content[0].text
        
        if schema:
            # Extract JSON if wrapped in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content)
        
        return content


class MockClient(BaseLLMClient):
    """Mock client for testing without API keys"""
    
    def complete(self, prompt: str, schema: dict | None = None) -> dict:
        print("[LLM] Using mock response (no API key set)")
        # Return a reasonable mock response for CFD queries
        return {
            "methods": ["Q_isosurface", "velocity_slice"],
            "reasoning": "Q-criterion isosurfaces reveal vortical structures, velocity slices show flow patterns",
            "outputs": [
                {
                    "type": "screenshot",
                    "after_method": "Q_isosurface",
                    "filename": "output/vortices.png",
                    "view_direction": "isometric"
                },
                {
                    "type": "screenshot",
                    "after_method": "velocity_slice",
                    "filename": "output/velocity_slice.png",
                    "view_direction": "-X"
                },
                {
                    "type": "screenshot",
                    "after_method": "final",
                    "filename": "output/combined.png",
                    "view_direction": "isometric"
                }
            ],
            "presentation": {
                "camera": {
                    "view_direction": "isometric",
                    "zoom": 1.0
                },
                "visibility": {
                    "hide_original_data": True,
                    "show_filters": ["Contour1", "Slice1"]
                },
                "colormap": "Cool to Warm"
            }
        }


def create_llm_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> BaseLLMClient:
    """
    Factory function to create appropriate LLM client.
    
    Args:
        provider: "openai", "anthropic", or "mock". 
                  If None, auto-detects from available API keys.
        api_key: Override API key
        model: Override model name
        base_url: Override base URL (OpenAI-compatible only)
    
    Returns:
        Configured LLM client
    """
    # Explicit provider
    if provider:
        provider = provider.lower()
        if provider == "openai":
            return OpenAIClient(api_key=api_key, base_url=base_url, model=model)
        elif provider == "anthropic":
            return AnthropicClient(api_key=api_key, model=model)
        elif provider == "mock":
            return MockClient()
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    # Auto-detect from env vars (prefer OpenAI for trame-llm consistency)
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIClient(api_key=api_key, base_url=base_url, model=model)
    
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicClient(api_key=api_key, model=model)
    
    # Fallback to mock
    return MockClient()


# Convenience function matching old interface
def call_llm(prompt: str, client: BaseLLMClient | None = None, json_mode: bool = False) -> dict | str:
    """
    Call LLM with prompt and return response.
    
    Args:
        prompt: The prompt text
        client: Optional pre-configured client. If None, creates one.
        json_mode: If True, expect JSON response. If False, return raw text.
        
    Returns:
        Parsed JSON dict if json_mode=True, else string response
    """
    if client is None:
        client = create_llm_client()
    
    if json_mode:
        # Ensure prompt mentions JSON for OpenAI compliance
        if "json" not in prompt.lower():
            prompt = prompt + "\n\nRespond in JSON format."
        return client.complete(prompt, schema={"type": "object"})
    else:
        # Text mode - no JSON parsing
        return client.complete(prompt, schema=None)
