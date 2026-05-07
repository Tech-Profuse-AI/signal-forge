"""
SignalForge Configuration Module.

Provides centralized configuration management, environment variable loading,
and brand guideline access for the SignalForge pipeline.
"""

from config.settings import Settings
from config.brand_guidelines import BrandGuidelinesManager

__all__ = ["Settings", "BrandGuidelinesManager"]
