"""Knowledge base hybrid retrieval package (C07)."""

from knowledge_base.retrieval.embeddings import (
    DEFAULT_MULTILINGUAL_MODEL,
    EMBEDDING_DIMENSION,
    MultilingualDenseEmbedder,
)
from knowledge_base.retrieval.engine import RetrievalEngine
from knowledge_base.retrieval.models import (
    AppliedFilters,
    Citation,
    RetrievalRequest,
    RetrievalResult,
)
from knowledge_base.retrieval.prefilter import StrictPreFilter
from knowledge_base.retrieval.service import RetrievalService

__all__ = [
    "DEFAULT_MULTILINGUAL_MODEL",
    "EMBEDDING_DIMENSION",
    "MultilingualDenseEmbedder",
    "AppliedFilters",
    "Citation",
    "RetrievalEngine",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalService",
    "StrictPreFilter",
]

