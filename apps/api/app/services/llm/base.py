"""
LLM service — base interface + mock implementation.

Provider pattern: Claude for production, mock for offline/tests.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("llm")


class LLMBase(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        images: list[bytes] | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """
        Send a completion request to the LLM.
        
        Args:
            prompt: User prompt text
            system: System prompt
            images: Optional list of image bytes for vision
            json_schema: Optional JSON schema for structured output
            max_tokens: Maximum tokens in response
            
        Returns:
            dict with at least {"text": str, "usage": dict}
        """
    async def generate_json(self, prompt: str, image_bytes: bytes | None = None) -> dict[str, Any]:
        """Convenience helper for structured JSON generation."""
        resp = await self.complete(prompt, images=[image_bytes] if image_bytes else None, json_schema={})
        return resp.get("parsed") or {}


class MockLLM(LLMBase):
    """
    Mock LLM for offline development and testing.
    Returns deterministic responses based on the prompt.
    """

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        images: list[bytes] | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        logger.debug(f"MockLLM: processing prompt ({len(prompt)} chars)")

        # Default mock garment classification if asked
        parsed = {}
        if "category" in prompt.lower():
            parsed = {
                "category": "top",
                "subcategory": "shirt",
                "pattern": "solid",
                "sleeve": "short_sleeve",
                "neckline": "collared",
                "fit": "regular",
                "formality": 1,
            }

        return {
            "text": str(parsed),
            "parsed": parsed,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


def get_llm_client() -> LLMBase:
    return get_llm()


def get_llm() -> LLMBase:
    """Factory for LLM provider based on config."""
    settings = get_settings()
    if settings.llm_provider == "mock":
        return MockLLM()
    elif settings.llm_provider == "claude":
        from app.services.llm.claude import ClaudeLLM
        return ClaudeLLM()
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
