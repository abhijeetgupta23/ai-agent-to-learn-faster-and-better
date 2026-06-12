"""
Persistence for learning graphs and learner models.

V1 uses a file-backed JSON store keyed by ID. The interface is intentionally
shaped so the backend can be swapped for a vector store (Chroma, FAISS, pgvector)
without touching call sites — the lookups today are by exact key, and embedding-
based retrieval would slot in as an additional `find_similar` method.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from src.schemas import LearnerModel, LearningGraph


def hash_source(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    def __init__(self, root: str | None = None):
        root = root or os.environ.get("ADAPTIVE_LEARNING_STORE_DIR", "./data/store")
        self.root = Path(root)
        (self.root / "graphs").mkdir(parents=True, exist_ok=True)
        (self.root / "learners").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)

    # --- graphs -----------------------------------------------------------

    def get_graph_by_source_hash(self, source_hash: str) -> LearningGraph | None:
        path = self.root / "graphs" / f"{source_hash}.json"
        if not path.exists():
            return None
        return LearningGraph.model_validate_json(path.read_text(encoding="utf-8"))

    def save_graph(self, graph: LearningGraph) -> None:
        path = self.root / "graphs" / f"{graph.source_hash}.json"
        path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")

    def list_graphs(self) -> list[dict]:
        out = []
        for p in sorted((self.root / "graphs").glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "source_hash": data["source_hash"],
                    "domain_id": data["domain_id"],
                    "domain_title": data["domain_title"],
                    "n_nodes": len(data["nodes"]),
                }
            )
        return out

    # --- source material (for grounded generation) ------------------------

    def save_source(self, source_hash: str, source_text: str) -> None:
        """Persist the raw source a graph was extracted from, so generation can
        later retrieve passages from it (grounded generation)."""
        (self.root / "sources" / f"{source_hash}.txt").write_text(source_text, encoding="utf-8")

    def get_source(self, source_hash: str) -> str | None:
        path = self.root / "sources" / f"{source_hash}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    # --- learners ---------------------------------------------------------

    def get_learner(self, user_id: str, domain_id: str) -> LearnerModel | None:
        path = self.root / "learners" / f"{user_id}__{domain_id}.json"
        if not path.exists():
            return None
        return LearnerModel.model_validate_json(path.read_text(encoding="utf-8"))

    def save_learner(self, learner: LearnerModel) -> None:
        path = self.root / "learners" / f"{learner.user_id}__{learner.domain_id}.json"
        path.write_text(learner.model_dump_json(indent=2), encoding="utf-8")
