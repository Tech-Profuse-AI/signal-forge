"""
SignalForge LLM Provider Abstraction.

Provides a swappable, environment-driven LLM layer so the rest of the
codebase never imports a specific SDK directly.

Architecture (inspired by social-media-agent prompt organisation):
  - BaseLLMProvider  — abstract interface
  - GeminiProvider   — production implementation
  - OpenAIProvider   — placeholder
  - AnthropicProvider — placeholder
  - get_llm_provider — factory function
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("signalforge.llm")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Abstract Base
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    Every provider must implement ``generate(prompt)`` and return
    a plain-text string response. Subclasses handle their own
    authentication, model selection, and retry logic.
    """

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate a text completion for the given prompt.

        Args:
            prompt: The input prompt string.
            **kwargs: Provider-specific overrides (temperature, max_tokens, …).

        Returns:
            The generated text response.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini Provider (production)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini provider using the ``google-generativeai`` SDK.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_output_tokens: int = 2048,
    ) -> None:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai is required for GeminiProvider. "
                "Install it with: pip install google-generativeai"
            ) from exc

        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiProvider.")

        genai.configure(api_key=api_key)

        self._model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
        self._model_name = model_name
        logger.info("GeminiProvider initialised — model: %s", model_name)

    def generate(self, prompt: str, **kwargs) -> str:
        """Call the Gemini API and return the text response."""
        try:
            response = self._model.generate_content(prompt)
            text = response.text.strip()
            logger.debug(
                "Gemini response (%d chars) for prompt starting with '%s…'",
                len(text),
                prompt[:60],
            )
            return text

        except Exception as exc:
            logger.error("Gemini generation failed: %s", exc)
            raise

    def __repr__(self) -> str:
        return f"<GeminiProvider model='{self._model_name}'>"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OpenAI Provider (placeholder)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class OpenAIProvider(BaseLLMProvider):
    """
    Placeholder for OpenAI GPT provider.

    Will be fully implemented in a later phase when multi-provider
    evaluation is needed.
    """

    def __init__(self, api_key: str, model_name: str = "gpt-4o") -> None:
        self._api_key = api_key
        self._model_name = model_name
        logger.info(
            "OpenAIProvider initialised (placeholder) — model: %s",
            model_name,
        )

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError(
            "OpenAIProvider is a placeholder. "
            "Full implementation coming in a future phase."
        )

    def __repr__(self) -> str:
        return f"<OpenAIProvider model='{self._model_name}' [placeholder]>"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Anthropic Provider (placeholder)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AnthropicProvider(BaseLLMProvider):
    """
    Placeholder for Anthropic Claude provider.

    Will be fully implemented in a later phase when multi-provider
    evaluation is needed.
    """

    def __init__(
        self, api_key: str, model_name: str = "claude-sonnet-4-20250514"
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        logger.info(
            "AnthropicProvider initialised (placeholder) — model: %s",
            model_name,
        )

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError(
            "AnthropicProvider is a placeholder. "
            "Full implementation coming in a future phase."
        )

    def __repr__(self) -> str:
        return f"<AnthropicProvider model='{self._model_name}' [placeholder]>"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_llm_provider(
    provider_name: str,
    api_key: str,
    **kwargs,
) -> BaseLLMProvider:
    """
    Factory function — instantiate an LLM provider by name.

    Args:
        provider_name: One of 'gemini', 'openai', 'anthropic'.
        api_key:       The API key for the chosen provider.
        **kwargs:      Forwarded to the provider constructor
                       (model_name, temperature, etc.).

    Returns:
        An initialised BaseLLMProvider subclass instance.

    Raises:
        ValueError: If provider_name is not recognised.
    """
    name = provider_name.lower().strip()
    cls = _PROVIDER_REGISTRY.get(name)

    if cls is None:
        available = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise ValueError(
            f"Unknown LLM provider '{provider_name}'. "
            f"Available: {available}"
        )

    logger.info("Creating LLM provider: %s", name)
    return cls(api_key=api_key, **kwargs)
