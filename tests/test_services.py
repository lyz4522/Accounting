"""Unit and persistence tests for accounting rules."""

from contextlib import closing
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from accounting.database import AccountingRepository
from accounting.models import DEFAULT_EXPENSE_CATEGORIES, TransactionType
from accounting.services import AccountingService


class AccountingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        repository = AccountingRepository(
            f"{self.temporary_directory.name}/accounting.db"
        )
        self.service = AccountingService(repository)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_update_delete_and_filter_transactions(self) -> None:
        first = self.service.save_transaction(
            "2026-03-01", TransactionType.EXPENSE, "餐饮", "35.50", "午餐"
        )
        second = self.service.save_transaction(
            "2026-03-03", TransactionType.INCOME, "工资", "5000"
        )
        self.assertIsNotNone(first.transaction_id)
        self.assertEqual(first.amount_cents, 3550)

        self.service.save_transaction(
            "2026-03-02",
            TransactionType.EXPENSE,
            "交通",
            "12",
            "地铁",
            first.transaction_id,
        )
        filtered = self.service.list_transactions(
            "2026-03-02",
            "2026-03-03",
            "交通",
            TransactionType.EXPENSE,
        )
        self.assertEqual([entry.transaction_id for entry in filtered], [first.transaction_id])
        self.assertEqual(filtered[0].amount_cents, 1200)

        self.service.delete_transaction(second.transaction_id)
        self.assertEqual(len(self.service.list_transactions()), 1)

    def test_summary_and_budget_use_net_spending(self) -> None:
        self.service.save_transaction(
            "2026-04-02", TransactionType.INCOME, "工资", "1000"
        )
        self.service.save_transaction(
            "2026-04-10", TransactionType.EXPENSE, "餐饮", "300"
        )
        budget = self.service.set_budget("2026-04", "800")
        saved_budget, summary = self.service.budget_usage("2026-04")
        self.assertEqual(budget, 80000)
        self.assertEqual(saved_budget, 80000)
        self.assertEqual(summary.income_cents, 100000)
        self.assertEqual(summary.expense_cents, 30000)
        self.assertEqual(summary.net_spending_cents, -70000)

    def test_period_bounds_cover_day_week_month_and_year(self) -> None:
        sample_date = "2024-02-29"
        self.assertEqual(
            self.service.period_bounds("日", sample_date),
            (sample_date, sample_date),
        )
        self.assertEqual(
            self.service.period_bounds("周", sample_date),
            ("2024-02-26", "2024-03-03"),
        )
        self.assertEqual(
            self.service.period_bounds("月", sample_date),
            ("2024-02-01", "2024-02-29"),
        )
        self.assertEqual(
            self.service.period_bounds("年", sample_date),
            ("2024-01-01", "2024-12-31"),
        )

    def test_amount_date_and_category_validation(self) -> None:
        for amount in ("0", "-1", "1.001", "not-a-number"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.service.save_transaction(
                    "2026-05-01", TransactionType.EXPENSE, "餐饮", amount
                )
        with self.assertRaises(ValueError):
            self.service.save_transaction(
                "2026-02-30", TransactionType.EXPENSE, "餐饮", "1"
            )
        with self.assertRaises(ValueError):
            self.service.save_transaction(
                "2026-05-01", TransactionType.INCOME, "餐饮", "1"
            )
        with self.assertRaises(ValueError):
            self.service.set_budget("2026-05", "0")
        with self.assertRaises(ValueError):
            self.service.save_transaction(
                "2026-05-01",
                TransactionType.EXPENSE,
                "餐饮",
                "1",
                "备注" * 51,
            )

    def test_custom_categories_are_type_scoped_and_protect_existing_records(self) -> None:
        self.assertEqual(
            self.service.add_category(TransactionType.EXPENSE, "宠物"),
            "宠物",
        )
        with self.assertRaisesRegex(ValueError, "同名"):
            self.service.add_category(TransactionType.EXPENSE, "宠物")

        saved = self.service.save_transaction(
            "2026-05-01", TransactionType.EXPENSE, "宠物", "28"
        )
        filtered = self.service.list_transactions(
            category="宠物", transaction_type=TransactionType.EXPENSE
        )
        self.assertEqual([item.transaction_id for item in filtered], [saved.transaction_id])
        with self.assertRaisesRegex(ValueError, "不属于当前收支类型"):
            self.service.list_transactions(
                category="宠物", transaction_type=TransactionType.INCOME
            )
        with self.assertRaisesRegex(ValueError, "先选择收支类型"):
            self.service.list_transactions(category="宠物")
        with self.assertRaisesRegex(ValueError, "已有收支记录"):
            self.service.delete_category(TransactionType.EXPENSE, "宠物")

        self.service.add_category(TransactionType.INCOME, "报销")
        self.service.delete_category(TransactionType.INCOME, "报销")
        self.assertNotIn("报销", self.service.categories(TransactionType.INCOME))
        with self.assertRaisesRegex(ValueError, "内置分类"):
            self.service.delete_category(TransactionType.EXPENSE, "餐饮")

    def test_custom_category_name_validation(self) -> None:
        for name in ("", " " * 2, "分类" * 11):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.service.add_category(TransactionType.EXPENSE, name)

    def test_existing_database_is_migrated_without_losing_records(self) -> None:
        database_path = f"{self.temporary_directory.name}/legacy.db"
        with closing(sqlite3.connect(database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        transaction_date TEXT NOT NULL,
                        transaction_type TEXT NOT NULL,
                        category TEXT NOT NULL,
                        amount_cents INTEGER NOT NULL,
                        note TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO transactions
                        (transaction_date, transaction_type, category, amount_cents, note)
                    VALUES ('2026-01-02', '支出', '餐饮', 1250, '旧记录')
                    """
                )

        repository = AccountingRepository(database_path)
        service = AccountingService(repository)
        self.assertEqual(
            service.categories(TransactionType.EXPENSE),
            list(DEFAULT_EXPENSE_CATEGORIES),
        )
        old_records = service.list_transactions()
        self.assertEqual(len(old_records), 1)
        self.assertEqual(old_records[0].note, "旧记录")

    def test_monthly_charts_return_complete_months_and_totals(self) -> None:
        self.service.save_transaction(
            "2026-06-03", TransactionType.INCOME, "工资", "3000"
        )
        self.service.save_transaction(
            "2026-06-06", TransactionType.EXPENSE, "餐饮", "50"
        )
        trend = self.service.monthly_trend(2026)
        june = next(item for item in trend if item.month == "2026-06")
        self.assertEqual(len(trend), 12)
        self.assertEqual((june.income_cents, june.expense_cents), (300000, 5000))
        categories = self.service.category_totals("2026-06")
        self.assertEqual([(item.category, item.amount_cents) for item in categories], [
            ("餐饮", 5000),
            ("工资", 300000),
        ])


if __name__ == "__main__":
    unittest.main()
