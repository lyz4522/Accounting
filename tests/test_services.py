"""Unit and persistence tests for accounting rules."""

from contextlib import closing
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from accounting.database import AccountingRepository
from accounting.models import DEFAULT_EXPENSE_CATEGORIES, TransactionType
from accounting.services import AccountingService
from accounting.gui import AccountingApp


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
        boundary_week = self.service.period_bounds("周", "2100-12-31")
        self.assertEqual(boundary_week, ("2100-12-27", "2100-12-31"))
        self.service.summary(*boundary_week)

    def test_amount_date_and_category_validation(self) -> None:
        for amount in (
            "0",
            "-1",
            "1.001",
            "not-a-number",
            "1e2",
            "1,000",
            ".25",
            "1.",
            "1234567890123",
            "1000000000000",
        ):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.service.save_transaction(
                    "2026-05-01", TransactionType.EXPENSE, "餐饮", amount
                )
        self.assertEqual(
            self.service.parse_amount("999999999999.99"),
            AccountingService.MAX_AMOUNT_CENTS,
        )
        self.assertEqual(self.service.parse_amount("12.5"), 1250)
        self.service.save_transaction(
            "2026-05-01",
            TransactionType.EXPENSE,
            "餐饮",
            "1",
            "备" * 100,
        )
        with self.assertRaises(ValueError):
            self.service.save_transaction(
                "2026-02-30", TransactionType.EXPENSE, "餐饮", "1"
            )
        for invalid_date in ("2026-5-01", "20260501", "1899-12-31", "2101-01-01"):
            with self.subTest(date=invalid_date), self.assertRaises(ValueError):
                self.service.normalize_date(invalid_date)
        for invalid_month in ("2026-1", "202613", "1899-12", "2101-01"):
            with self.subTest(month=invalid_month), self.assertRaises(ValueError):
                self.service.normalize_month(invalid_month)
        self.assertEqual(self.service.normalize_date("1900-01-01"), "1900-01-01")
        self.assertEqual(self.service.normalize_date("2100-12-31"), "2100-12-31")
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
        self.assertEqual(
            self.service.add_category(TransactionType.EXPENSE, "类" * 20),
            "类" * 20,
        )
        with self.assertRaises(ValueError):
            self.service.add_category(TransactionType.EXPENSE, "类" * 21)

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

    def test_budget_display_distinguishes_net_income_and_spending(self) -> None:
        self.service.set_budget("2026-07", "1000")
        self.service.save_transaction(
            "2026-07-02", TransactionType.INCOME, "工资", "2000"
        )
        self.service.save_transaction(
            "2026-07-03", TransactionType.EXPENSE, "餐饮", "500"
        )
        app = self._budget_display_test_app()

        AccountingApp.refresh_budget(app)

        self.assertIn("净收入：￥1,500.00", app.budget_status.set.call_args.args[0])
        self.assertEqual(
            app.budget_percent.set.call_args.args[0],
            "恭喜本月赚了 ￥1,500.00！",
        )
        app.budget_progress.pack_forget.assert_called_once()
        app.budget_status.set.reset_mock()
        app.budget_percent.set.reset_mock()
        app.budget_progress.configure.reset_mock()

        self.service.save_transaction(
            "2026-07-04", TransactionType.EXPENSE, "交通", "2000"
        )
        AccountingApp.refresh_budget(app)

        self.assertIn("净消费：￥500.00", app.budget_status.set.call_args.args[0])
        self.assertEqual(app.budget_percent.set.call_args.args[0], "50.0%")
        self.assertEqual(app.budget_progress.configure.call_args.kwargs["value"], 50)
        self.assertEqual(
            app.budget_progress.configure.call_args.kwargs["style"],
            "Income.Horizontal.TProgressbar",
        )
        app.budget_progress.configure.reset_mock()
        app.budget_details.set.reset_mock()
        app.budget_notice.set.reset_mock()
        app.budget_notice_label.configure.reset_mock()

        self.service.save_transaction(
            "2026-07-05", TransactionType.EXPENSE, "交通", "1.00"
        )
        AccountingApp.refresh_budget(app)

        self.assertEqual(app.budget_percent.set.call_args.args[0], "50.1%")
        self.assertEqual(
            app.budget_progress.configure.call_args.kwargs["style"],
            "Expense.Horizontal.TProgressbar",
        )
        self.assertEqual(
            app.budget_notice.set.call_args.args[0],
            "预算剩余不多：￥499.00",
        )
        self.assertEqual(
            app.budget_notice_label.configure.call_args.kwargs["foreground"],
            "#e05b5b",
        )

        self.service.save_transaction(
            "2026-07-06", TransactionType.EXPENSE, "交通", "499.00"
        )
        AccountingApp.refresh_budget(app)
        self.assertEqual(app.budget_percent.set.call_args.args[0], "100.0%")
        self.assertEqual(
            app.budget_notice.set.call_args.args[0],
            "预算剩余不多：￥0.00",
        )
        self.service.save_transaction(
            "2026-07-07", TransactionType.EXPENSE, "交通", "0.01"
        )
        AccountingApp.refresh_budget(app)
        self.assertEqual(
            app.budget_notice.set.call_args.args[0],
            "已超预算 ￥0.01",
        )
        self.assertEqual(
            app.budget_notice_label.configure.call_args.kwargs["foreground"],
            "#e05b5b",
        )

    def _budget_display_test_app(self) -> SimpleNamespace:
        return SimpleNamespace(
            budget_month=SimpleNamespace(get_month=lambda: "2026-07"),
            service=self.service,
            budget_status=Mock(),
            budget_percent=Mock(),
            budget_progress=Mock(),
            budget_notice=Mock(),
            budget_notice_label=Mock(),
            budget_details=Mock(),
            budget_percent_label=Mock(),
        )

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
