from __future__ import annotations

import json

from ..models import GeneratedQuery, Schema


class OpenAIGenerator:
    """Opt-in schema-grounded OpenAI generator; safety validation runs downstream."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4.1-mini", dialect: str = "sqlite") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install openai to enable the OpenAI generator") from exc
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dialect = dialect

    def generate(self, question: str, schema: Schema) -> GeneratedQuery:
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                f"You convert questions to one {self.dialect} read-only SELECT query. Use only the supplied schema. "
                "Never use DDL/DML, PRAGMA, comments, or multiple statements. Return JSON with sql, explanation, assumptions. "
                "If ambiguous, choose a conservative interpretation and state it. Never invent tables or columns."
            ),
            input=json.dumps({"schema": schema.prompt_text(), "question": question}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "generated_query", "strict": True, "schema": {
                "type": "object", "properties": {"sql": {"type": "string"}, "explanation": {"type": "string"}, "assumptions": {"type": "array", "items": {"type": "string"}}},
                "required": ["sql", "explanation", "assumptions"], "additionalProperties": False
            }}},
        )
        data = json.loads(response.output_text)
        return GeneratedQuery(data["sql"], data["explanation"], tuple(data["assumptions"]), f"openai:{self.model}")
