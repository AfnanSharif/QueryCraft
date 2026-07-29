from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True)
class ForeignKey:
    column: str
    target_table: str
    target_column: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()


@dataclass(frozen=True)
class Schema:
    tables: tuple[Table, ...]

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(table.name for table in self.tables)

    def prompt_text(self) -> str:
        lines = []
        for table in self.tables:
            columns = ", ".join(f"{column.name} {column.data_type}{' PRIMARY KEY' if column.primary_key else ''}" for column in table.columns)
            lines.append(f"{table.name}({columns})")
            for key in table.foreign_keys:
                lines.append(f"  FK {table.name}.{key.column} -> {key.target_table}.{key.target_column}")
        return "\n".join(lines)


@dataclass(frozen=True)
class GeneratedQuery:
    sql: str
    explanation: str
    assumptions: tuple[str, ...] = ()
    provider: str = "local-rules"


@dataclass(frozen=True)
class QueryResult:
    question: str
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    explanation: str
    assumptions: tuple[str, ...]
    provider: str
    elapsed_ms: float
    query_plan: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
