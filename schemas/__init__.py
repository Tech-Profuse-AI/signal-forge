"""Shared SignalForge response schemas."""

from schemas.opportunity import (
    Opportunity,
    PipelineStatus,
    serialize_opportunity,
    serialize_opportunity_list,
)

__all__ = [
    "Opportunity",
    "PipelineStatus",
    "serialize_opportunity",
    "serialize_opportunity_list",
]
