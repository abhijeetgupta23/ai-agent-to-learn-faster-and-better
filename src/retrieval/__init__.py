"""
Retrieval layer: the stable seam between the tutor and its evidence sources.

This package is introduced ahead of the hybrid-RAG work (see
docs/RAG_ARCHITECTURE.md). Nothing at runtime imports it yet — the agent still
calls `src.graph.retriever.ground_context()` directly. The seam exists so new
retrieval strategies (BM25, dense, hybrid, graph-guided) can be built and
benchmarked behind `StudyMaterialRetriever` and swapped in without touching
the agent loop.
"""

from src.retrieval.schemas import (
    Chunk,
    Citation,
    PedagogicalMetadata,
    RetrievalBundle,
    RetrievalRequest,
    RetrievedPassage,
    SourceDocument,
)
from src.retrieval.service import LexicalStudyMaterialRetriever, StudyMaterialRetriever

__all__ = [
    "Chunk",
    "Citation",
    "PedagogicalMetadata",
    "RetrievalBundle",
    "RetrievalRequest",
    "RetrievedPassage",
    "SourceDocument",
    "StudyMaterialRetriever",
    "LexicalStudyMaterialRetriever",
]
