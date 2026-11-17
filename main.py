import math
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from fastmcp import FastMCP


mcp = FastMCP("expense-tracker")
DATABASE_PATH = Path(__file__).resolve().with_name("expense.db")


@contextmanager
def _database_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid date in YYYY-MM-DD format") from error


def _date_filters(
    start_date: str | None, end_date: str | None
) -> tuple[list[str], list[str]]:
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must be on or before end_date")

    conditions = []
    parameters = []
    if start is not None:
        conditions.append("date >= ?")
        parameters.append(start)
    if end is not None:
        conditions.append("date <= ?")
        parameters.append(end)
    return conditions, parameters


def _initialize_database() -> None:
    with _database_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                category TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            )
            """
        )


@mcp.tool
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


@mcp.tool
def insert(
    amount: float,
    category: str,
    description: str = "",
    expense_date: str | None = None,
) -> dict[str, int | float | str]:
    """Add an expense. The date is optional and must use YYYY-MM-DD."""
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount must be a finite number greater than zero")
    if not category.strip():
        raise ValueError("category must not be empty")

    entry_date = _validate_date(expense_date, "expense_date")
    if entry_date is None:
        entry_date = date.today().isoformat()

    with _database_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO expenses (date, amount, category, description)
            VALUES (?, ?, ?, ?)
            """,
            (entry_date, amount, category.strip(), description.strip()),
        )
        expense_id = cursor.lastrowid

    if expense_id is None:
        raise RuntimeError("The expense was inserted, but its ID could not be retrieved")
    return {
        "id": expense_id,
        "date": entry_date,
        "amount": amount,
        "category": category.strip(),
        "description": description.strip(),
    }


@mcp.tool
def list_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict[str, int | float | str]]:
    """List expenses, optionally filtered by an inclusive date range."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    conditions, parameters = _date_filters(start_date, end_date)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _database_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, date, amount, category, description
            FROM expenses
            {where_clause}
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool
def summarize(
    start_date: str | None = None, end_date: str | None = None
) -> dict[str, int | float | list[dict[str, int | float | str]]]:
    """Summarize expense totals overall and by category for an optional date range."""
    conditions, parameters = _date_filters(start_date, end_date)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _database_connection() as connection:
        total = connection.execute(
            f"""
            SELECT COUNT(*) AS expense_count, COALESCE(SUM(amount), 0) AS total_amount
            FROM expenses
            {where_clause}
            """,
            parameters,
        ).fetchone()
        categories = connection.execute(
            f"""
            SELECT category, COUNT(*) AS expense_count, SUM(amount) AS total_amount
            FROM expenses
            {where_clause}
            GROUP BY category
            ORDER BY total_amount DESC, category
            """,
            parameters,
        ).fetchall()

    return {
        "expense_count": total["expense_count"],
        "total_amount": total["total_amount"],
        "by_category": [dict(row) for row in categories],
    }


_initialize_database()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
