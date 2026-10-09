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
        ...


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
        
        # Return structured JSON if schema provided
        if json_schema:
            return {
                "text": "{}",
                "parsed": {},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        return {
            "text": "This is a mock LLM response for development.",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


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
