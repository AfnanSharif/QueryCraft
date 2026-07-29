import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2sql.database import SQLiteAnalyticsDatabase
from text2sql.generator import RuleBasedGenerator
from text2sql.models import GeneratedQuery
from text2sql.security import UnsafeQueryError, enforce_limit, validate_read_only
from text2sql.service import TextToSQLService
from text2sql.warehouse import WarehouseAnalyticsDatabase


class RecordingOptimizer:
    def __init__(self):
        self.plans = []

    def optimize(self, question, generated, schema, plan):
        self.plans.append(plan)
        return GeneratedQuery(generated.sql, "Plan-aware rewrite", generated.assumptions, "fake-optimizer")


class FakeCursor:
    def __init__(self, statements):
        self.statements = statements
        self.rows = []
        self.description = ()

    def execute(self, sql):
        self.statements.append(sql)
        if "information_schema.columns" in sql:
            self.rows = [("orders", "id", "NUMBER", "NO"), ("orders", "total", "NUMBER", "YES")]
            self.description = (("table_name",), ("column_name",), ("data_type",), ("is_nullable",))
        elif sql.startswith("EXPLAIN"):
            self.rows = [("search orders using approved index",)]
            self.description = (("plan",),)
        else:
            self.rows = [(1, 42.5)]
            self.description = (("id",), ("total",))

    def fetchall(self):
        return self.rows

    def fetchmany(self, count):
        return self.rows[:count]

    def close(self):
        return None


class FakeConnection:
    def __init__(self, statements):
        self.statements = statements

    def cursor(self):
        return FakeCursor(self.statements)

    def close(self):
        return None


class TextToSQLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        project = Path(__file__).resolve().parents[1]
        self.db = SQLiteAnalyticsDatabase(Path(self.temp.name) / "food.db", max_rows=20)
        self.db.initialize(project / "data" / "food_delivery.sql")
        self.service = TextToSQLService(self.db, RuleBasedGenerator())

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_introspection(self):
        schema = self.db.schema()
        self.assertIn("orders", schema.table_names)
        orders = next(table for table in schema.tables if table.name == "orders")
        self.assertTrue(any(key.target_table == "users" for key in orders.foreign_keys))

    def test_top_revenue_end_to_end(self):
        result = self.service.ask("Top 3 restaurants by revenue")
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(result.columns, ("restaurant", "revenue"))
        self.assertIn("LIMIT 3", result.sql)
        json.dumps(result.to_dict())

    def test_generic_count(self):
        result = self.service.ask("How many reviews are there?")
        self.assertEqual(result.rows[0][0], 11)

    def test_top_customer_spend_wording_from_readme(self):
        result = self.service.ask("Who are the top 3 customers by spend?")
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(result.columns, ("customer", "total_spend", "orders"))

    def test_dangerous_queries_rejected(self):
        for sql in ["DROP TABLE users", "SELECT * FROM users; DELETE FROM users", "PRAGMA table_info(users)", "SELECT * FROM sqlite_master", "SELECT 1 -- bypass"]:
            with self.subTest(sql=sql), self.assertRaises(UnsafeQueryError):
                validate_read_only(sql)

    def test_keyword_inside_literal_is_safe(self):
        self.assertEqual(validate_read_only("SELECT 'drop table' AS phrase"), "SELECT 'drop table' AS phrase")

    def test_limit_is_added_and_clamped(self):
        self.assertTrue(enforce_limit("SELECT * FROM users", 10).endswith("LIMIT 10"))
        self.assertTrue(enforce_limit("SELECT * FROM users LIMIT 999", 10).endswith("LIMIT 10"))

    def test_plan_aware_optimizer_is_wired_and_bounded(self):
        optimizer = RecordingOptimizer()
        result = TextToSQLService(self.db, RuleBasedGenerator(), optimizer).ask("How many users are there?")
        self.assertTrue(optimizer.plans)
        self.assertEqual(result.provider, "fake-optimizer")
        self.assertIn("accepted", result.assumptions[-1])

    def test_warehouse_schema_and_execution_share_safety_contract(self):
        statements = []
        warehouse = WarehouseAnalyticsDatabase(
            lambda: FakeConnection(statements),
            "snowflake",
            "EXPLAIN USING TEXT ",
            max_rows=10,
        )
        schema = warehouse.schema()
        self.assertEqual(schema.table_names, ("orders",))
        generated = GeneratedQuery("SELECT id, total FROM orders", "Read approved order facts")
        result = warehouse.execute("show orders", generated)
        self.assertEqual(result.columns, ("id", "total"))
        self.assertTrue(result.sql.endswith("LIMIT 10"))
        with self.assertRaises(UnsafeQueryError):
            warehouse.execute("bad", GeneratedQuery("DELETE FROM orders", "bad"))
        self.assertFalse(any(statement.startswith("DELETE") for statement in statements))


if __name__ == "__main__":
    unittest.main()
