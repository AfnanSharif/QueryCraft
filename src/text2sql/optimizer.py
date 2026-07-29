from __future__ import annotations

from typing import Protocol

from .models import GeneratedQuery, Schema


class QueryOptimizer(Protocol):
    def optimize(self, question: str, generated: GeneratedQuery, schema: Schema, plan: tuple[str, ...]) -> GeneratedQuery: ...


def plan_cost(plan: tuple[str, ...]) -> int:
    """Small cross-engine plan heuristic; lower is preferred."""
    text = " ".join(plan).lower()
    return (
        8 * text.count("temp b-tree")
        + 6 * text.count("table scan")
        + 4 * text.count(" scan ")
        + 2 * text.count("sort")
        + text.count("search")
    )
