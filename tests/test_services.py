"""Unit and persistence tests for accounting rules."""

from tempfile import TemporaryDirectory
import unittest

from accounting.database import AccountingRepository
from accounting.models import TransactionType
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
            "2026-03-02", "2026-03-03", "交通"
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
