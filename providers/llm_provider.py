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
import re
import threading
import time
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

    Rate-limit protection:
      - A class-level threading.Semaphore(1) serializes all API calls.
      - Exponential backoff retry (max 2 retries, 2s → 4s) on 429 errors.
    """

    _semaphore = threading.Semaphore(1)
    _cooldown_lock = threading.Lock()
    _cooldown_until = 0.0

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.5-flash",
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
        """Call the Gemini API with serialization and retry on 429."""
        with self._semaphore:
            self._raise_if_in_cooldown()
            return self._generate_with_retry(prompt, **kwargs)

    def _generate_with_retry(self, prompt: str, **kwargs) -> str:
        """Retry up to 2 times with exponential backoff on rate-limit errors."""
        max_retries = 2
        for attempt in range(max_retries + 1):
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
                if self._is_rate_limit_error(exc) and attempt < max_retries:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(
                        "Gemini rate limited",
                    )
                    logger.warning(
                        "Retrying in %d seconds (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                    continue
                if self._is_rate_limit_error(exc):
                    cooldown_seconds = self._set_rate_limit_cooldown(exc)
                    logger.warning("Gemini rate limited")
                    logger.warning(
                        "Gemini cooldown active for %d seconds; skipping new Gemini calls",
                        cooldown_seconds,
                    )
                    raise
                logger.error("Gemini generation failed: %s", exc)
                raise

    @classmethod
    def _raise_if_in_cooldown(cls) -> None:
        with cls._cooldown_lock:
            remaining = cls._cooldown_until - time.time()
        if remaining > 0:
            seconds = max(1, int(remaining))
            logger.warning(
                "Gemini rate limited; skipping call during cooldown (%d seconds remaining)",
                seconds,
            )
            raise RuntimeError("Gemini rate limited; cooldown active")

    @classmethod
    def _set_rate_limit_cooldown(cls, exc: Exception) -> int:
        seconds = cls._retry_delay_seconds(exc) or 30
        seconds = max(5, min(60, seconds))
        with cls._cooldown_lock:
            cls._cooldown_until = max(cls._cooldown_until, time.time() + seconds)
        return seconds

    @staticmethod
    def _retry_delay_seconds(exc: Exception) -> Optional[int]:
        match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", str(exc))
        if match:
            return int(match.group(1))
        match = re.search(r"retry in\s+(\d+)", str(exc), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        """Check if an exception is a 429 / resource-exhausted error."""
        exc_str = str(exc).lower()
        if "429" in exc_str or "resource" in exc_str and "exhausted" in exc_str:
            return True
        if "quota" in exc_str or "rate" in exc_str and "limit" in exc_str:
            return True
        # google.api_core.exceptions.ResourceExhausted
        exc_type = type(exc).__name__
        if exc_type in ("ResourceExhausted", "TooManyRequests"):
            return True
        return False

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
