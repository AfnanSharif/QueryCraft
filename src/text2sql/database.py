from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import Column, ForeignKey, QueryResult, Schema, Table
from .security import enforce_limit


class QueryTimeoutError(RuntimeError):
    pass


class SQLiteAnalyticsDatabase:
    def __init__(self, path: str | Path, timeout_ms: int = 1500, max_rows: int = 200) -> None:
        if not 1 <= timeout_ms <= 60_000:
            raise ValueError("timeout_ms must be between 1 and 60000")
        if not 1 <= max_rows <= 10_000:
            raise ValueError("max_rows must be between 1 and 10000")
        self.path = Path(path)
        self.backend = "sqlite"
        self.timeout_ms = timeout_ms
        self.max_rows = max_rows

    def initialize(self, sql_path: str | Path) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(Path(sql_path).read_text(encoding="utf-8"))
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise FileNotFoundError(f"database not found: {self.path}")
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def schema(self) -> Schema:
        with self._connect() as connection:
            names = [row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            tables = []
            for name in names:
                escaped = name.replace('"', '""')
                columns = tuple(
                    Column(row[1], row[2] or "ANY", not bool(row[3]), bool(row[5]))
                    for row in connection.execute(f'PRAGMA table_info("{escaped}")')
                )
                keys = tuple(
                    ForeignKey(row[3], row[2], row[4])
                    for row in connection.execute(f'PRAGMA foreign_key_list("{escaped}")')
                )
                tables.append(Table(name, columns, keys))
        return Schema(tuple(tables))

    def explain(self, sql: str) -> tuple[str, ...]:
        safe = enforce_limit(sql, self.max_rows)
        deadline = time.perf_counter() + self.timeout_ms / 1000
        with self._connect() as connection:
            connection.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 1000)
            try:
                return tuple(str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + safe))
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise QueryTimeoutError(f"query planning exceeded {self.timeout_ms} ms") from exc
                raise ValueError(f"SQL planning failed: {exc}") from exc
            finally:
                connection.set_progress_handler(None, 0)

    def execute(self, question: str, generated, include_plan: bool = True) -> QueryResult:
        sql = enforce_limit(generated.sql, self.max_rows)
        started = time.perf_counter()
        deadline = started + self.timeout_ms / 1000
        with self._connect() as connection:
            connection.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 1000)
            try:
                plan = tuple(str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql)) if include_plan else ()
                cursor = connection.execute(sql)
                rows = tuple(tuple(row) for row in cursor.fetchmany(self.max_rows + 1))
                columns = tuple(item[0] for item in cursor.description or ())
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise QueryTimeoutError(f"query exceeded {self.timeout_ms} ms") from exc
                raise ValueError(f"SQL execution failed: {exc}") from exc
            finally:
                connection.set_progress_handler(None, 0)
        elapsed = (time.perf_counter() - started) * 1000
        return QueryResult(question, sql, columns, rows[: self.max_rows], generated.explanation, generated.assumptions, generated.provider, round(elapsed, 2), plan)
