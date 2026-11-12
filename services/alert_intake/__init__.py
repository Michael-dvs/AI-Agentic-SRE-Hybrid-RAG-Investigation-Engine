"""Authenticated synthetic alert intake and bounded correlation."""
from .correlation import DependencyCorrelator
from .dedup import AlertDeduplicator
from .intake import AlertIntakeService

__all__ = ["AlertIntakeService", "AlertDeduplicator", "DependencyCorrelator"]
