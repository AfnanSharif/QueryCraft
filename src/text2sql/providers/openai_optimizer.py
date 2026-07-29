from __future__ import annotations

import json

from ..models import GeneratedQuery, Schema


class OpenAIQueryOptimizer:
    """One bounded optimization pass; service-side plan comparison decides acceptance."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4.1-mini", dialect: str = "sqlite") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install OpenAI mode with `pip install -r requirements-ai.txt`") from exc
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dialect = dialect

    def optimize(self, question: str, generated: GeneratedQuery, schema: Schema, plan: tuple[str, ...]) -> GeneratedQuery:
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                f"Optimize one read-only {self.dialect} SELECT/CTE without changing its answer. Use only the schema. "
                "Never emit DDL/DML, comments, multiple statements, optimizer hints, or invented indexes. "
                "Return JSON with sql, explanation, assumptions. Keep the original when no safe improvement exists."
            ),
            input=json.dumps({"question": question, "schema": schema.prompt_text(), "sql": generated.sql, "query_plan": plan}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "optimized_query", "strict": True, "schema": {
                "type": "object", "properties": {"sql": {"type": "string"}, "explanation": {"type": "string"}, "assumptions": {"type": "array", "items": {"type": "string"}}},
                "required": ["sql", "explanation", "assumptions"], "additionalProperties": False
            }}},
        )
        data = json.loads(response.output_text)
        return GeneratedQuery(data["sql"], data["explanation"], tuple(data["assumptions"]), f"openai-optimized:{self.model}")
