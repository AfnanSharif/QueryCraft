from __future__ import annotations

from ..models import GeneratedQuery, Schema


class LangChainGenerator:
    """Optional LCEL structured-output generator for the requested LangChain path."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4.1-mini", dialect: str = "sqlite") -> None:
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_openai import ChatOpenAI
            from pydantic import BaseModel, ConfigDict, Field
        except ImportError as exc:
            raise RuntimeError("Install LangChain mode with `pip install -r requirements-ai.txt`") from exc

        class QueryPayload(BaseModel):
            model_config = ConfigDict(extra="forbid")
            sql: str
            explanation: str
            assumptions: list[str] = Field(default_factory=list)

        self.model = model
        self.dialect = dialect
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Generate exactly one read-only SELECT/CTE query in {dialect} SQL. Use only the supplied schema. "
                    "Never emit DDL, DML, comments, multiple statements, or invented identifiers.",
                ),
                ("human", "Schema:\n{schema}\n\nQuestion:\n{question}"),
            ]
        )
        self.chain = prompt | ChatOpenAI(model=model, api_key=api_key, temperature=0).with_structured_output(QueryPayload)

    def generate(self, question: str, schema: Schema) -> GeneratedQuery:
        payload = self.chain.invoke({"dialect": self.dialect, "schema": schema.prompt_text(), "question": question})
        return GeneratedQuery(payload.sql, payload.explanation, tuple(payload.assumptions), f"langchain:{self.model}")
