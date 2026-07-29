from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import Column, GeneratedQuery, QueryResult, Schema, Table
from .security import enforce_limit


def _portable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class WarehouseAnalyticsDatabase:
    """Read-only DB-API boundary shared by Databricks SQL and Snowflake."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        backend: str,
        explain_prefix: str,
        timeout_ms: int = 10_000,
        max_rows: int = 200,
    ) -> None:
        if backend not in {"databricks", "snowflake"}:
            raise ValueError("unsupported warehouse backend")
        if not 1 <= timeout_ms <= 300_000 or not 1 <= max_rows <= 10_000:
            raise ValueError("invalid timeout or row limit")
        self.connection_factory = connection_factory
        self.backend = backend
        self.explain_prefix = explain_prefix
        self.timeout_ms = timeout_ms
        self.max_rows = max_rows

    def _query(self, sql: str, fetch_limit: int | None = None) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
        connection = self.connection_factory()
        cursor = connection.cursor()
        try:
            cursor.execute(sql)
            raw_rows = cursor.fetchmany(fetch_limit) if fetch_limit is not None else cursor.fetchall()
            columns = tuple(str(item[0]) for item in (cursor.description or ()))
            rows = tuple(tuple(_portable(value) for value in row) for row in raw_rows)
            return columns, rows
        finally:
            try:
                cursor.close()
            finally:
                connection.close()

    def schema(self) -> Schema:
        _, rows = self._query(
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_schema = current_schema() "
            "ORDER BY table_name, ordinal_position"
        )
        grouped: dict[str, list[Column]] = {}
        for table_name, column_name, data_type, is_nullable in rows:
            grouped.setdefault(str(table_name), []).append(
                Column(str(column_name), str(data_type), str(is_nullable).upper() == "YES", False)
            )
        if not grouped:
            raise RuntimeError(f"{self.backend} current schema contains no visible tables")
        return Schema(tuple(Table(name, tuple(columns)) for name, columns in sorted(grouped.items())))

    def explain(self, sql: str) -> tuple[str, ...]:
        safe = enforce_limit(sql, self.max_rows)
        _, rows = self._query(self.explain_prefix + safe)
        return tuple(" | ".join(str(value) for value in row) for row in rows)

    def execute(self, question: str, generated: GeneratedQuery, include_plan: bool = True) -> QueryResult:
        sql = enforce_limit(generated.sql, self.max_rows)
        started = time.perf_counter()
        plan = self.explain(sql) if include_plan else ()
        columns, rows = self._query(sql, self.max_rows + 1)
        elapsed = (time.perf_counter() - started) * 1000
        return QueryResult(
            question,
            sql,
            columns,
            rows[: self.max_rows],
            generated.explanation,
            generated.assumptions,
            generated.provider,
            round(elapsed, 2),
            plan,
        )


def databricks_database(timeout_ms: int = 10_000, max_rows: int = 200) -> WarehouseAnalyticsDatabase:
    required = {
        "DATABRICKS_SERVER_HOSTNAME": os.getenv("DATABRICKS_SERVER_HOSTNAME", "").strip(),
        "DATABRICKS_HTTP_PATH": os.getenv("DATABRICKS_HTTP_PATH", "").strip(),
        "DATABRICKS_TOKEN": os.getenv("DATABRICKS_TOKEN", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing Databricks configuration: " + ", ".join(missing))

    def connect() -> Any:
        try:
            from databricks import sql
        except ImportError as exc:
            raise RuntimeError("Install warehouse adapters with `pip install -r requirements-warehouses.txt`") from exc
        options: dict[str, Any] = {
            "server_hostname": required["DATABRICKS_SERVER_HOSTNAME"],
            "http_path": required["DATABRICKS_HTTP_PATH"],
            "access_token": required["DATABRICKS_TOKEN"],
        }
        if os.getenv("DATABRICKS_CATALOG", "").strip():
            options["catalog"] = os.environ["DATABRICKS_CATALOG"].strip()
        if os.getenv("DATABRICKS_SCHEMA", "").strip():
            options["schema"] = os.environ["DATABRICKS_SCHEMA"].strip()
        return sql.connect(**options)

    return WarehouseAnalyticsDatabase(connect, "databricks", "EXPLAIN FORMATTED ", timeout_ms, max_rows)


def snowflake_database(timeout_ms: int = 10_000, max_rows: int = 200) -> WarehouseAnalyticsDatabase:
    names = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA", "SNOWFLAKE_ROLE")
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError("Missing Snowflake configuration: " + ", ".join(missing))

    def connect() -> Any:
        try:
            import snowflake.connector
        except ImportError as exc:
            raise RuntimeError("Install warehouse adapters with `pip install -r requirements-warehouses.txt`") from exc
        return snowflake.connector.connect(
            account=values["SNOWFLAKE_ACCOUNT"],
            user=values["SNOWFLAKE_USER"],
            password=values["SNOWFLAKE_PASSWORD"],
            warehouse=values["SNOWFLAKE_WAREHOUSE"],
            database=values["SNOWFLAKE_DATABASE"],
            schema=values["SNOWFLAKE_SCHEMA"],
            role=values["SNOWFLAKE_ROLE"],
            session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": max(1, timeout_ms // 1000)},
        )

    return WarehouseAnalyticsDatabase(connect, "snowflake", "EXPLAIN USING TEXT ", timeout_ms, max_rows)
