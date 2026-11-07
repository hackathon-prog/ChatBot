"""Read-only database access for analytics queries."""

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.sql_guard import validate_select


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        # Open the file in read-only mode so writes fail at the driver level.
        import sqlite3

        path = url.removeprefix("sqlite:///")
        if not Path(path).is_absolute():
            # Serverless working directories differ: resolve relative to the project root.
            path = str(Path(__file__).resolve().parent.parent / path)
        return create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True),
        )
    # Other databases: point DATABASE_URL at a read-only DB user. For Postgres the session is also made
    # read-only and time limited, as a second layer next to the database role.
    if url.startswith("postgresql"):
        options = "-c default_transaction_read_only=on -c statement_timeout=5000"
        return create_engine(url, connect_args={"options": options}, pool_pre_ping=True)
    return create_engine(url)


class AnalyticsDb:
    def __init__(
        self, url: str, blocked_columns: frozenset[str], max_rows: int, schema: str | None = None
    ) -> None:
        self._engine = _make_engine(url)
        self._schema = schema
        self._blocked = blocked_columns
        self._max_rows = max_rows

    def run_select(self, sql: str) -> dict[str, Any]:
        safe = validate_select(sql, self._blocked)
        wrapped = text(f"SELECT * FROM ({safe}) AS q LIMIT :n")
        with self._engine.connect() as conn:
            result = conn.execute(wrapped, {"n": self._max_rows})
            columns = list(result.keys())
            rows = [list(r) for r in result.fetchall()]
        return {"columns": columns, "rows": rows, "row_cap": self._max_rows}

    def describe_schema(self) -> str:
        insp = inspect(self._engine)
        lines: list[str] = []
        names = insp.get_table_names(schema=self._schema) + insp.get_view_names(schema=self._schema)
        for table in sorted(set(names)):
            cols = [
                f"{c['name']} {c['type']}"
                for c in insp.get_columns(table, schema=self._schema)
                if c["name"].lower() not in {b.lower() for b in self._blocked}
            ]
            lines.append(f"{table}({', '.join(cols)})")
        return "\n".join(lines)
