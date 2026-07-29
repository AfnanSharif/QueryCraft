from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .database import SQLiteAnalyticsDatabase
from .generator import RuleBasedGenerator
from .providers import LangChainGenerator, OpenAIGenerator, OpenAIQueryOptimizer
from .service import TextToSQLService
from .warehouse import databricks_database, snowflake_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe natural-language analytics for SQLite, Databricks, or Snowflake")
    parser.add_argument("--backend", choices=("sqlite", "databricks", "snowflake"), default=None)
    parser.add_argument("--database", type=Path, default=Path(".local/food_delivery.db"))
    parser.add_argument("--seed", type=Path, default=Path("data/food_delivery.sql"))
    parser.add_argument("--generator", choices=("local", "openai", "langchain"), default="local")
    parser.add_argument("--model", default=None)
    parser.add_argument("--optimize", action="store_true", help="run one OpenAI rewrite and accept it only when the plan is no worse")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    ask = commands.add_parser("ask")
    ask.add_argument("question")
    commands.add_parser("schema")
    return parser


def _database(args):
    backend = args.backend or os.getenv("DATABASE_BACKEND", "sqlite")
    timeout_ms = int(os.getenv("QUERY_TIMEOUT_MS", "1500"))
    max_rows = int(os.getenv("MAX_RESULT_ROWS", "200"))
    if backend == "databricks":
        return databricks_database(timeout_ms, max_rows), backend
    if backend == "snowflake":
        return snowflake_database(timeout_ms, max_rows), backend
    return SQLiteAnalyticsDatabase(args.database, timeout_ms, max_rows), "sqlite"


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()
    args = build_parser().parse_args(argv)
    database, backend = _database(args)
    if args.command == "init-db":
        if backend != "sqlite":
            raise ValueError("init-db is available only for the bundled SQLite demo")
        database.initialize(args.seed)
        print(json.dumps({"database": str(args.database), "tables": database.schema().table_names}, indent=2))
    elif args.command == "schema":
        print(database.schema().prompt_text())
    else:
        if backend == "sqlite" and not args.database.exists():
            database.initialize(args.seed)
        api_key = os.getenv("OPENAI_API_KEY", "")
        model = args.model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        if args.generator == "openai":
            generator = OpenAIGenerator(api_key, model, backend)
        elif args.generator == "langchain":
            generator = LangChainGenerator(api_key, model, backend)
        else:
            generator = RuleBasedGenerator()
        optimizer = OpenAIQueryOptimizer(api_key, model, backend) if args.optimize else None
        result = TextToSQLService(database, generator, optimizer).ask(args.question)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
