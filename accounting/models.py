"""Typed domain models for the accounting application."""

from dataclasses import dataclass
from enum import Enum


class TransactionType(str, Enum):
    INCOME = "收入"
    EXPENSE = "支出"


DEFAULT_INCOME_CATEGORIES = ("工资", "奖金", "理财", "兼职", "其他收入")
DEFAULT_EXPENSE_CATEGORIES = (
    "餐饮",
    "交通",
    "住房",
    "购物",
    "医疗",
    "娱乐",
    "教育",
    "通讯",
    "其他支出",
)


@dataclass(frozen=True)
class Transaction:
    date: str
    transaction_type: TransactionType
    category: str
    amount_cents: int
    note: str = ""
    transaction_id: int | None = None


@dataclass(frozen=True)
class PeriodSummary:
    income_cents: int
    expense_cents: int

    @property
    def net_spending_cents(self) -> int:
        return self.expense_cents - self.income_cents


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    transaction_type: TransactionType
    amount_cents: int


@dataclass(frozen=True)
class MonthlyTrend:
    month: str
    income_cents: int
    expense_cents: int
