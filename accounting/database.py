"""SQLite persistence for transactions and monthly budgets."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from accounting.models import (
    CategoryTotal,
    MonthlyTrend,
    Transaction,
    TransactionType,
)


class AccountingRepository:
    """A small repository that owns all SQL used by the application."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_date TEXT NOT NULL,
                    transaction_type TEXT NOT NULL
                        CHECK (transaction_type IN ('收入', '支出')),
                    category TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transactions_date
                ON transactions(transaction_date)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_budgets (
                    month TEXT PRIMARY KEY,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)
                )
                """
            )

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> Transaction:
        return Transaction(
            transaction_id=row["id"],
            date=row["transaction_date"],
            transaction_type=TransactionType(row["transaction_type"]),
            category=row["category"],
            amount_cents=row["amount_cents"],
            note=row["note"],
        )

    def add_transaction(self, transaction: Transaction) -> Transaction:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transactions
                    (transaction_date, transaction_type, category, amount_cents, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    transaction.date,
                    transaction.transaction_type.value,
                    transaction.category,
                    transaction.amount_cents,
                    transaction.note,
                ),
            )
            transaction_id = cursor.lastrowid
        return Transaction(
            transaction_id=transaction_id,
            date=transaction.date,
            transaction_type=transaction.transaction_type,
            category=transaction.category,
            amount_cents=transaction.amount_cents,
            note=transaction.note,
        )

    def update_transaction(self, transaction: Transaction) -> bool:
        if transaction.transaction_id is None:
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE transactions
                SET transaction_date = ?, transaction_type = ?, category = ?,
                    amount_cents = ?, note = ?
                WHERE id = ?
                """,
                (
                    transaction.date,
                    transaction.transaction_type.value,
                    transaction.category,
                    transaction.amount_cents,
                    transaction.note,
                    transaction.transaction_id,
                ),
            )
        return cursor.rowcount == 1

    def delete_transaction(self, transaction_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM transactions WHERE id = ?", (transaction_id,)
            )
        return cursor.rowcount == 1

    def list_transactions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        category: str | None = None,
    ) -> list[Transaction]:
        conditions: list[str] = []
        parameters: list[str] = []
        if start_date:
            conditions.append("transaction_date >= ?")
            parameters.append(start_date)
        if end_date:
            conditions.append("transaction_date <= ?")
            parameters.append(end_date)
        if category:
            conditions.append("category = ?")
            parameters.append(category)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, transaction_date, transaction_type, category, amount_cents, note
                FROM transactions{where_clause}
                ORDER BY transaction_date DESC, id DESC
                """,
                parameters,
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def get_category_totals(self, month: str) -> list[CategoryTotal]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT category, transaction_type, SUM(amount_cents) AS total_cents
                FROM transactions
                WHERE transaction_date LIKE ?
                GROUP BY category, transaction_type
                ORDER BY transaction_type, total_cents DESC, category
                """,
                (f"{month}-%",),
            ).fetchall()
        return [
            CategoryTotal(
                category=row["category"],
                transaction_type=TransactionType(row["transaction_type"]),
                amount_cents=row["total_cents"],
            )
            for row in rows
        ]

    def get_monthly_trend(self, year: int) -> list[MonthlyTrend]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT substr(transaction_date, 1, 7) AS month,
                    SUM(CASE WHEN transaction_type = '收入' THEN amount_cents ELSE 0 END)
                        AS income_cents,
                    SUM(CASE WHEN transaction_type = '支出' THEN amount_cents ELSE 0 END)
                        AS expense_cents
                FROM transactions
                WHERE transaction_date >= ? AND transaction_date <= ?
                GROUP BY month
                ORDER BY month
                """,
                (f"{year:04d}-01-01", f"{year:04d}-12-31"),
            ).fetchall()
        totals = {
            row["month"]: MonthlyTrend(
                month=row["month"],
                income_cents=row["income_cents"],
                expense_cents=row["expense_cents"],
            )
            for row in rows
        }
        return [
            totals.get(
                f"{year:04d}-{month:02d}",
                MonthlyTrend(f"{year:04d}-{month:02d}", 0, 0),
            )
            for month in range(1, 13)
        ]

    def get_budget(self, month: str) -> int | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT amount_cents FROM monthly_budgets WHERE month = ?", (month,)
            ).fetchone()
        return row["amount_cents"] if row else None

    def set_budget(self, month: str, amount_cents: int) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO monthly_budgets (month, amount_cents) VALUES (?, ?)
                ON CONFLICT(month) DO UPDATE SET amount_cents = excluded.amount_cents
                """,
                (month, amount_cents),
            )
