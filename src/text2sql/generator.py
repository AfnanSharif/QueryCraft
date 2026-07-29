from __future__ import annotations

import re

from .models import GeneratedQuery, Schema


def _normalized(question: str) -> str:
    return re.sub(r"\s+", " ", question.lower().strip(" ?."))


class RuleBasedGenerator:
    """Auditable common analytics templates for the included food-delivery schema."""

    def generate(self, question: str, schema: Schema) -> GeneratedQuery:
        q = _normalized(question)
        if not q:
            raise ValueError("question is required")
        tables = set(schema.table_names)
        food_schema = {"users", "restaurants", "menu_items", "orders", "order_items", "payments", "reviews"} <= tables
        if food_schema:
            match = self._food_delivery(q)
            if match:
                return match
        return self._generic(q, schema)

    def _food_delivery(self, q: str) -> GeneratedQuery | None:
        if ("top" in q or "best" in q) and "restaurant" in q and any(word in q for word in ("revenue", "sales", "earning")):
            number = self._number(q, 5)
            return GeneratedQuery(
                """SELECT r.name AS restaurant, ROUND(SUM(p.amount), 2) AS revenue
FROM restaurants r
JOIN orders o ON o.restaurant_id = r.id
JOIN payments p ON p.order_id = o.id
WHERE p.status = 'completed'
GROUP BY r.id, r.name
ORDER BY revenue DESC""" + f"\nLIMIT {number}",
                "Ranks restaurants by completed payment value.",
                ("Revenue means completed payments, not gross order subtotal.",),
            )
        if ("top" in q or "popular" in q) and any(term in q for term in ("dish", "dishes", "item", "items", "menu")):
            number = self._number(q, 5)
            return GeneratedQuery(
                """SELECT mi.name AS menu_item, r.name AS restaurant, SUM(oi.quantity) AS units_ordered
FROM order_items oi
JOIN menu_items mi ON mi.id = oi.menu_item_id
JOIN restaurants r ON r.id = mi.restaurant_id
JOIN orders o ON o.id = oi.order_id
WHERE o.status != 'cancelled'
GROUP BY mi.id, mi.name, r.name
ORDER BY units_ordered DESC""" + f"\nLIMIT {number}",
                "Ranks menu items by non-cancelled units ordered.",
            )
        if "average" in q and "rating" in q and "restaurant" in q:
            return GeneratedQuery(
                """SELECT r.name AS restaurant, ROUND(AVG(rv.rating), 2) AS average_rating, COUNT(rv.id) AS review_count
FROM restaurants r LEFT JOIN reviews rv ON rv.restaurant_id = r.id
GROUP BY r.id, r.name
ORDER BY average_rating DESC, review_count DESC""",
                "Calculates review-weighted average ratings and includes review counts.",
            )
        if any(term in q for term in ("revenue by restaurant", "sales by restaurant")):
            return GeneratedQuery(
                """SELECT r.name AS restaurant, ROUND(SUM(p.amount), 2) AS revenue
FROM restaurants r JOIN orders o ON o.restaurant_id = r.id JOIN payments p ON p.order_id = o.id
WHERE p.status = 'completed' GROUP BY r.id, r.name ORDER BY revenue DESC""",
                "Aggregates completed payment revenue by restaurant.",
            )
        if "order" in q and "status" in q and any(term in q for term in ("count", "many", "breakdown", "distribution")):
            return GeneratedQuery("SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC", "Counts orders in each lifecycle status.")
        if any(term in q for term in ("recent order", "latest order", "newest order")):
            number = self._number(q, 10)
            return GeneratedQuery(
                """SELECT o.id AS order_id, u.name AS customer, r.name AS restaurant, o.status,
       ROUND(o.total_amount, 2) AS total_amount, o.created_at
FROM orders o JOIN users u ON u.id = o.user_id JOIN restaurants r ON r.id = o.restaurant_id
ORDER BY o.created_at DESC""" + f"\nLIMIT {number}",
                "Lists newest orders with customer and restaurant context.",
            )
        if any(term in q for term in ("highest spending", "top customer", "top user", "customer spend")) or (
            any(subject in q for subject in ("customer", "customers", "user", "users"))
            and any(metric in q for metric in ("spend", "spending", "spent"))
        ):
            number = self._number(q, 5)
            return GeneratedQuery(
                """SELECT u.name AS customer, ROUND(SUM(p.amount), 2) AS total_spend, COUNT(DISTINCT o.id) AS orders
FROM users u JOIN orders o ON o.user_id = u.id JOIN payments p ON p.order_id = o.id
WHERE p.status = 'completed' GROUP BY u.id, u.name ORDER BY total_spend DESC""" + f"\nLIMIT {number}",
                "Ranks customers by completed payment spend.",
            )
        if "payment" in q and any(term in q for term in ("method", "type", "breakdown", "distribution")):
            return GeneratedQuery("SELECT method, COUNT(*) AS payments, ROUND(SUM(amount), 2) AS amount FROM payments WHERE status = 'completed' GROUP BY method ORDER BY amount DESC", "Summarizes completed payment count and value by method.")
        if "restaurant" in q and any(term in q for term in ("list", "show", "all", "available")):
            return GeneratedQuery("SELECT name, cuisine, city, rating, delivery_fee FROM restaurants ORDER BY rating DESC, name", "Lists restaurants ordered by rating.")
        if "user" in q and any(term in q for term in ("count", "many", "total")):
            return GeneratedQuery("SELECT COUNT(*) AS users FROM users", "Counts registered users.")
        if "restaurant" in q and any(term in q for term in ("count", "many", "total")):
            return GeneratedQuery("SELECT COUNT(*) AS restaurants FROM restaurants", "Counts restaurants.")
        if "order" in q and any(term in q for term in ("count", "many", "total")):
            return GeneratedQuery("SELECT COUNT(*) AS orders FROM orders", "Counts all orders.")
        return None

    @staticmethod
    def _number(question: str, default: int) -> int:
        match = re.search(r"\b(?:top|last|latest|recent)\s+(\d{1,3})\b", question)
        return min(int(match.group(1)), 100) if match else default

    @staticmethod
    def _generic(q: str, schema: Schema) -> GeneratedQuery:
        table = next((name for name in schema.table_names if name.lower() in q or name.lower().rstrip("s") in q), None)
        if table and any(term in q for term in ("count", "many", "total number")):
            escaped = table.replace('"', '""')
            return GeneratedQuery(f'SELECT COUNT(*) AS row_count FROM "{escaped}"', f"Counts rows in {table}.")
        examples = ", ".join(schema.table_names)
        raise ValueError(
            "The local generator could not map that question safely. "
            f"Try a count/list/top/revenue/rating question about: {examples}; or configure the optional OpenAI provider."
        )
