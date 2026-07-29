from __future__ import annotations

from .database import SQLiteAnalyticsDatabase
from .generator import RuleBasedGenerator
from .models import QueryResult
from .models import GeneratedQuery
from .optimizer import plan_cost


class TextToSQLService:
    def __init__(self, database, generator=None, optimizer=None) -> None:
        self.database = database
        self.generator = generator or RuleBasedGenerator()
        self.optimizer = optimizer

    def ask(self, question: str) -> QueryResult:
        schema = self.database.schema()
        generated = self.generator.generate(question, schema)
        if self.optimizer is not None:
            original_plan = self.database.explain(generated.sql)
            candidate = self.optimizer.optimize(question, generated, schema, original_plan)
            candidate_plan = self.database.explain(candidate.sql)
            if plan_cost(candidate_plan) <= plan_cost(original_plan):
                generated = GeneratedQuery(
                    candidate.sql,
                    candidate.explanation,
                    candidate.assumptions + ("Plan-aware rewrite accepted after read-only validation.",),
                    candidate.provider,
                )
            else:
                generated = GeneratedQuery(
                    generated.sql,
                    generated.explanation,
                    generated.assumptions + ("Candidate rewrite was rejected because its query plan scored worse.",),
                    generated.provider,
                )
        return self.database.execute(question, generated)
