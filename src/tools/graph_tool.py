"""Tool wrapper around the graph extractor — uses the memory store cache."""

from __future__ import annotations

from src.graph.extractor import extract_learning_graph
from src.memory.store import MemoryStore
from src.schemas import LearningGraph


def extract_learning_graph_tool(
    source_text: str,
    domain_title: str,
    store: MemoryStore | None = None,
) -> LearningGraph:
    return extract_learning_graph(source_text, domain_title, store)
