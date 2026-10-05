"""Validation and accounting rules, independent of the graphical interface."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from accounting.database import AccountingRepository
from accounting.models import (
    CategoryTotal,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    MonthlyTrend,
    PeriodSummary,
    Transaction,
    TransactionType,
)

INCOME_CATEGORIES = DEFAULT_INCOME_CATEGORIES
EXPENSE_CATEGORIES = DEFAULT_EXPENSE_CATEGORIES


class AccountingService:
    MIN_SELECTABLE_YEAR = 1900
    MAX_SELECTABLE_YEAR = 2100
    MAX_AMOUNT_CENTS = 999_999_999_999_99

    def __init__(self, repository: AccountingRepository) -> None:
        self.repository = repository

    @classmethod
    def parse_amount(cls, amount: str) -> int:
        if not isinstance(amount, str):
            raise ValueError("金额须为数字文本，例如 12 或 12.50。")
        normalized = amount.strip()
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", normalized):
            raise ValueError("金额须为正数，可带 1 至 2 位小数，例如 12 或 12.50。")
        try:
            value = Decimal(normalized)
        except (InvalidOperation, AttributeError) as exc:
            raise ValueError("金额必须是有效数字。") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError("金额必须大于 0。")
        if len(normalized.partition(".")[0]) > 12:
            raise ValueError("金额整数部分最多 12 位。")
        amount_cents = int(value * 100)
        if amount_cents > cls.MAX_AMOUNT_CENTS:
            raise ValueError("金额过大，超出数据库可保存的最大值。")
        return amount_cents

    @classmethod
    def _validate_year(cls, year: int) -> None:
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not cls.MIN_SELECTABLE_YEAR <= year <= cls.MAX_SELECTABLE_YEAR
        ):
            raise ValueError(
                f"年份须在 {cls.MIN_SELECTABLE_YEAR} 至 {cls.MAX_SELECTABLE_YEAR} 之间。"
            )

    @classmethod
    def normalize_date(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("日期格式无效，请使用 YYYY-MM-DD。")
        normalized_value = value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized_value):
            raise ValueError("日期格式无效，请使用 YYYY-MM-DD。")
        try:
            normalized = date.fromisoformat(normalized_value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("日期格式无效，请使用 YYYY-MM-DD。") from exc
        cls._validate_year(normalized.year)
        return normalized.isoformat()

    @classmethod
    def normalize_month(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("月份格式无效，请使用 YYYY-MM。")
        normalized_value = value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}", normalized_value):
            raise ValueError("月份格式无效，请使用 YYYY-MM。")
        try:
            parsed = date.fromisoformat(f"{normalized_value}-01")
        except (ValueError, AttributeError) as exc:
            raise ValueError("月份格式无效，请使用 YYYY-MM。") from exc
        cls._validate_year(parsed.year)
        return parsed.strftime("%Y-%m")

    def _validate_category(self, transaction_type: TransactionType, category: str) -> str:
        if not isinstance(category, str):
            raise ValueError("请选择有效分类。")
        normalized = category.strip()
        if normalized not in self.repository.list_categories(transaction_type):
            raise ValueError("请选择与收支类型匹配的有效分类。")
        return normalized

    def save_transaction(
        self,
        transaction_date: str,
        transaction_type: TransactionType,
        category: str,
        amount: str,
        note: str = "",
        transaction_id: int | None = None,
    ) -> Transaction:
        if not isinstance(transaction_type, TransactionType):
            raise ValueError("收支类型无效。")
        if not isinstance(note, str):
            raise ValueError("备注须为文本，最多 100 个字符。")
        normalized_note = note.strip()
        if len(normalized_note) > 100:
            raise ValueError("备注最多只能输入 100 个字符。")
        transaction = Transaction(
            transaction_id=transaction_id,
            date=self.normalize_date(transaction_date),
            transaction_type=transaction_type,
            category=self._validate_category(transaction_type, category),
            amount_cents=self.parse_amount(amount),
            note=normalized_note,
        )
        if transaction_id is None:
            return self.repository.add_transaction(transaction)
        if not self.repository.update_transaction(transaction):
            raise ValueError("这条记录已不存在，请刷新记录列表后重试。")
        return transaction

    def delete_transaction(self, transaction_id: int) -> None:
        if not self.repository.delete_transaction(transaction_id):
            raise ValueError("这条记录已不存在，请刷新记录列表后重试。")

    def summary(self, start_date: str, end_date: str) -> PeriodSummary:
        start = self.normalize_date(start_date)
        end = self.normalize_date(end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期。")
        transactions = self.repository.list_transactions(start, end)
        income = sum(
            item.amount_cents
            for item in transactions
            if item.transaction_type is TransactionType.INCOME
        )
        expense = sum(
            item.amount_cents
            for item in transactions
            if item.transaction_type is TransactionType.EXPENSE
        )
        return PeriodSummary(income, expense)

    def monthly_summary(self, month: str) -> PeriodSummary:
        normalized_month = self.normalize_month(month)
        return self.summary(
            f"{normalized_month}-01",
            f"{normalized_month}-{self._days_in_month(normalized_month)}",
        )

    @staticmethod
    def _days_in_month(month: str) -> int:
        first = date.fromisoformat(f"{month}-01")
        next_month = (
            date(first.year + 1, 1, 1)
            if first.month == 12
            else date(first.year, first.month + 1, 1)
        )
        return (next_month - timedelta(days=1)).day

    def budget_usage(self, month: str) -> tuple[int | None, PeriodSummary]:
        normalized_month = self.normalize_month(month)
        return (
            self.repository.get_budget(normalized_month),
            self.monthly_summary(normalized_month),
        )

    def set_budget(self, month: str, amount: str) -> int:
        normalized_month = self.normalize_month(month)
        amount_cents = self.parse_amount(amount)
        self.repository.set_budget(normalized_month, amount_cents)
        return amount_cents

    def period_bounds(self, period: str, selected_date: str) -> tuple[str, str]:
        selected = date.fromisoformat(self.normalize_date(selected_date))
        if period == "日":
            start = end = selected
        elif period == "周":
            start = selected - timedelta(days=selected.weekday())
            end = start + timedelta(days=6)
            start = max(start, date(self.MIN_SELECTABLE_YEAR, 1, 1))
            end = min(end, date(self.MAX_SELECTABLE_YEAR, 12, 31))
        elif period == "月":
            start = selected.replace(day=1)
            end = selected.replace(day=self._days_in_month(start.strftime("%Y-%m")))
        elif period == "年":
            start = date(selected.year, 1, 1)
            end = date(selected.year, 12, 31)
        else:
            raise ValueError("统计周期无效。")
        return start.isoformat(), end.isoformat()

    def list_transactions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        category: str | None = None,
        transaction_type: TransactionType | None = None,
    ) -> list[Transaction]:
        start = self.normalize_date(start_date) if start_date else None
        end = self.normalize_date(end_date) if end_date else None
        if start and end and start > end:
            raise ValueError("开始日期不能晚于结束日期。")
        if category and transaction_type is None:
            raise ValueError("选择分类筛选前，请先选择收支类型。")
        if category and category not in self.repository.list_categories(transaction_type):
            raise ValueError("所选分类不属于当前收支类型。")
        return self.repository.list_transactions(start, end, category, transaction_type)

    def categories(self, transaction_type: TransactionType) -> list[str]:
        if not isinstance(transaction_type, TransactionType):
            raise ValueError("收支类型无效。")
        return self.repository.list_categories(transaction_type)

    def add_category(self, transaction_type: TransactionType, name: str) -> str:
        if not isinstance(transaction_type, TransactionType):
            raise ValueError("收支类型无效。")
        if not isinstance(name, str):
            raise ValueError("分类名称须为文本。")
        normalized = name.strip()
        if not normalized or len(normalized) > 20:
            raise ValueError("分类名称为必填项，最多只能输入 20 个字符。")
        if normalized in self.repository.list_categories(transaction_type):
            raise ValueError("该收支类型下已存在同名分类。")
        if not self.repository.add_category(transaction_type, normalized):
            raise ValueError("该收支类型下已存在同名分类。")
        return normalized

    def delete_category(self, transaction_type: TransactionType, name: str) -> None:
        if not isinstance(transaction_type, TransactionType):
            raise ValueError("收支类型无效。")
        result = self.repository.delete_category(transaction_type, name)
        if result == "in_use":
            raise ValueError("该分类已有收支记录，请先修改或删除相关记录后再删除分类。")
        if result != "deleted":
            raise ValueError("内置分类或不存在的分类不能删除。")

    def category_totals(self, month: str) -> list[CategoryTotal]:
        return self.repository.get_category_totals(self.normalize_month(month))

    def monthly_trend(self, year: int) -> list[MonthlyTrend]:
        self._validate_year(year)
        return self.repository.get_monthly_trend(year)
