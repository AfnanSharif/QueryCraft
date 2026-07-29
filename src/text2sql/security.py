from __future__ import annotations

import re


class UnsafeQueryError(ValueError):
    pass


BLOCKED = {
    "alter", "analyze", "attach", "create", "delete", "detach", "drop", "insert", "load_extension",
    "pragma", "reindex", "release", "replace", "rollback", "savepoint", "transaction", "truncate", "update", "vacuum"
}


def _without_literals(sql: str) -> str:
    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.extend("  ")
                    index += 2
                    continue
                quote = None
            output.append(" ")
        elif char in {"'", '"', "`"}:
            quote = char
            output.append(" ")
        else:
            output.append(char)
        index += 1
    if quote:
        raise UnsafeQueryError("unclosed quoted value")
    return "".join(output)


def validate_read_only(sql: str) -> str:
    candidate = sql.strip()
    if not candidate:
        raise UnsafeQueryError("generated SQL is empty")
    if "--" in candidate or "/*" in candidate or "*/" in candidate:
        raise UnsafeQueryError("SQL comments are not allowed")
    visible = _without_literals(candidate)
    semicolons = [index for index, char in enumerate(visible) if char == ";"]
    if semicolons:
        if len(semicolons) != 1 or visible[semicolons[0] + 1 :].strip():
            raise UnsafeQueryError("multiple SQL statements are not allowed")
        candidate = candidate[: semicolons[0]].rstrip()
        visible = visible[: semicolons[0]]
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", visible.lower())
    if not tokens or tokens[0] not in {"select", "with"}:
        raise UnsafeQueryError("only SELECT or WITH queries are allowed")
    dangerous = sorted(BLOCKED & set(tokens))
    if dangerous:
        raise UnsafeQueryError(f"blocked SQL keyword: {dangerous[0]}")
    if "sqlite_master" in tokens or "sqlite_schema" in tokens:
        raise UnsafeQueryError("system catalog access is not allowed")
    return candidate


def enforce_limit(sql: str, max_rows: int = 200) -> str:
    safe = validate_read_only(sql)
    visible = _without_literals(safe)
    limits = list(re.finditer(r"\blimit\s+(\d+)\b", visible, re.IGNORECASE))
    if limits:
        match = limits[-1]
        value = min(int(match.group(1)), max_rows)
        return safe[: match.start(1)] + str(value) + safe[match.end(1) :]
    return f"{safe}\nLIMIT {max_rows}"
