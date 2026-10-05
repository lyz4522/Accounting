"""Tkinter user interface for records, analysis, and budget reminders."""

from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from accounting.database import AccountingRepository
from accounting.models import Transaction, TransactionType
from accounting.services import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    AccountingService,
)


def _money(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    return f"￥{sign}{whole:,}.{fraction:02d}"


def _amount_text(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


class AccountingApp:
    def __init__(self, root: tk.Tk, database_path: str | Path) -> None:
        self.root = root
        self.repository = AccountingRepository(database_path)
        self.service = AccountingService(self.repository)
        self.editing_id: int | None = None
        self._configure_window()
        self._build_interface()
        self.refresh_records()
        self.refresh_summary()
        self.refresh_charts()
        self.load_budget()

    def _configure_window(self) -> None:
        self.root.title("个人消费记账")
        self.root.geometry("1180x780")
        self.root.minsize(920, 650)
        self.root.configure(bg="#f4f6f8")
        rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Metric.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Treeview", rowheight=29)

    def _build_interface(self) -> None:
        container = ttk.Frame(self.root, padding=(18, 14))
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="个人消费记账", style="Title.TLabel").pack(
            anchor="w", pady=(0, 12)
        )

        self.tabs = ttk.Notebook(container)
        self.tabs.pack(fill="both", expand=True)
        self.records_tab = ttk.Frame(self.tabs, padding=14)
        self.statistics_tab = ttk.Frame(self.tabs, padding=14)
        self.budget_tab = ttk.Frame(self.tabs, padding=22)
        self.tabs.add(self.records_tab, text="收支记录")
        self.tabs.add(self.statistics_tab, text="统计分析")
        self.tabs.add(self.budget_tab, text="预算提醒")
        self._build_records_tab()
        self._build_statistics_tab()
        self._build_budget_tab()
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_records_tab(self) -> None:
        form = ttk.LabelFrame(self.records_tab, text="记录收支", padding=12)
        form.pack(fill="x", pady=(0, 12))
        self.record_date = tk.StringVar(value=date.today().isoformat())
        self.record_type = tk.StringVar(value=TransactionType.EXPENSE.value)
        self.record_category = tk.StringVar(value=EXPENSE_CATEGORIES[0])
        self.record_amount = tk.StringVar()
        self.record_note = tk.StringVar()
        fields = (
            ("日期", ttk.Entry(form, textvariable=self.record_date, width=14)),
            (
                "收支类型",
                ttk.Combobox(
                    form,
                    textvariable=self.record_type,
                    values=[kind.value for kind in TransactionType],
                    state="readonly",
                    width=10,
                ),
            ),
            (
                "分类",
                ttk.Combobox(
                    form,
                    textvariable=self.record_category,
                    values=EXPENSE_CATEGORIES,
                    state="readonly",
                    width=12,
                ),
            ),
            ("金额（元）", ttk.Entry(form, textvariable=self.record_amount, width=14)),
            ("备注", ttk.Entry(form, textvariable=self.record_note, width=30)),
        )
        for column, (label, widget) in enumerate(fields):
            ttk.Label(form, text=label).grid(
                row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 5)
            )
            widget.grid(row=1, column=column, sticky="ew", padx=(0, 10))
        form.columnconfigure(4, weight=1)
        self.record_type.trace_add("write", self._update_category_choices)
        buttons = ttk.Frame(form)
        buttons.grid(row=1, column=5, sticky="e")
        self.save_record_button = ttk.Button(
            buttons, text="添加记录", command=self.save_record
        )
        self.save_record_button.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="清空", command=self.clear_record_form).pack(
            side="left"
        )

        filters = ttk.LabelFrame(self.records_tab, text="筛选记录", padding=10)
        filters.pack(fill="x", pady=(0, 10))
        self.filter_start = tk.StringVar()
        self.filter_end = tk.StringVar()
        self.filter_category = tk.StringVar(value="全部")
        ttk.Label(filters, text="开始日期").pack(side="left")
        ttk.Entry(filters, textvariable=self.filter_start, width=13).pack(
            side="left", padx=(6, 14)
        )
        ttk.Label(filters, text="结束日期").pack(side="left")
        ttk.Entry(filters, textvariable=self.filter_end, width=13).pack(
            side="left", padx=(6, 14)
        )
        ttk.Label(filters, text="分类").pack(side="left")
        ttk.Combobox(
            filters,
            textvariable=self.filter_category,
            values=["全部", *INCOME_CATEGORIES, *EXPENSE_CATEGORIES],
            state="readonly",
            width=14,
        ).pack(side="left", padx=(6, 12))
        ttk.Button(filters, text="应用筛选", command=self.refresh_records).pack(
            side="left"
        )
        ttk.Button(filters, text="重置", command=self.reset_filters).pack(
            side="left", padx=(6, 0)
        )

        table_frame = ttk.Frame(self.records_tab)
        table_frame.pack(fill="both", expand=True)
        columns = ("date", "type", "category", "amount", "note")
        self.record_table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        for column, title, width in (
            ("date", "日期", 130),
            ("type", "收支", 85),
            ("category", "分类", 120),
            ("amount", "金额", 130),
            ("note", "备注", 400),
        ):
            self.record_table.heading(column, text=title)
            self.record_table.column(
                column,
                width=width,
                anchor="w" if column == "note" else "center",
                stretch=column == "note",
            )
        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.record_table.yview
        )
        self.record_table.configure(yscrollcommand=scrollbar.set)
        self.record_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.record_table.bind("<<TreeviewSelect>>", self.select_record)
        actions = ttk.Frame(self.records_tab)
        actions.pack(fill="x", pady=(9, 0))
        ttk.Label(
            actions, text="选择列表中的记录后可修改或删除。", foreground="#64748b"
        ).pack(side="left")
        ttk.Button(actions, text="删除所选记录", command=self.delete_selected).pack(
            side="right"
        )

    def _build_statistics_tab(self) -> None:
        summary_box = ttk.LabelFrame(
            self.statistics_tab, text="收支汇总", padding=(12, 10)
        )
        summary_box.pack(fill="x", pady=(0, 12))
        self.summary_period = tk.StringVar(value="月")
        self.summary_date = tk.StringVar(value=date.today().isoformat())
        ttk.Label(summary_box, text="统计周期").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            summary_box,
            textvariable=self.summary_period,
            values=["日", "周", "月", "年"],
            state="readonly",
            width=8,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0), padx=(0, 12))
        ttk.Label(summary_box, text="日期（周/月/年按此日期所在周期统计）").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Entry(summary_box, textvariable=self.summary_date, width=16).grid(
            row=1, column=1, sticky="w", pady=(4, 0)
        )
        ttk.Button(
            summary_box, text="查询汇总", command=self.refresh_summary
        ).grid(row=1, column=2, padx=12, sticky="w")
        self.summary_income = tk.StringVar(value="￥0.00")
        self.summary_expense = tk.StringVar(value="￥0.00")
        self.summary_balance = tk.StringVar(value="￥0.00")
        for column, (label, variable, color) in enumerate(
            (
                ("收入", self.summary_income, "#15966b"),
                ("支出", self.summary_expense, "#e05b5b"),
                ("收支结余", self.summary_balance, "#2563eb"),
            ),
            start=3,
        ):
            card = ttk.Frame(summary_box, padding=(12, 0))
            card.grid(row=0, column=column, rowspan=2, sticky="nsew")
            ttk.Label(card, text=label, foreground="#64748b").pack(anchor="w")
            ttk.Label(card, textvariable=variable, style="Metric.TLabel", foreground=color).pack(
                anchor="w", pady=(4, 0)
            )
            summary_box.columnconfigure(column, weight=1)
        charts_box = ttk.LabelFrame(
            self.statistics_tab, text="月度分类占比与收支趋势", padding=6
        )
        charts_box.pack(fill="both", expand=True)
        controls = ttk.Frame(charts_box)
        controls.pack(fill="x", padx=5, pady=(2, 5))
        self.chart_month = tk.StringVar(value=date.today().strftime("%Y-%m"))
        self.chart_year = tk.StringVar(value=str(date.today().year))
        ttk.Label(controls, text="分类占比月份").pack(side="left")
        ttk.Entry(controls, textvariable=self.chart_month, width=10).pack(
            side="left", padx=(6, 16)
        )
        ttk.Label(controls, text="趋势年份").pack(side="left")
        ttk.Entry(controls, textvariable=self.chart_year, width=7).pack(
            side="left", padx=(6, 12)
        )
        ttk.Button(controls, text="更新图表", command=self.refresh_charts).pack(
            side="left"
        )
        self.figure = Figure(figsize=(11, 4.7), dpi=100, tight_layout=True)
        self.expense_axis, self.income_axis, self.trend_axis = self.figure.subplots(
            1, 3
        )
        self.chart_canvas = FigureCanvasTkAgg(self.figure, master=charts_box)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _build_budget_tab(self) -> None:
        ttk.Label(
            self.budget_tab, text="月度生活费预算", style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.budget_tab,
            text="为每个月单独设置预算；当月净消费超过预算时，保存记录或预算后会弹窗提醒。",
            foreground="#64748b",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 22))
        settings = ttk.LabelFrame(self.budget_tab, text="预算设置", padding=16)
        settings.pack(fill="x", anchor="n")
        self.budget_month = tk.StringVar(value=date.today().strftime("%Y-%m"))
        self.budget_amount = tk.StringVar()
        ttk.Label(settings, text="月份（YYYY-MM）").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.budget_month, width=14).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Button(settings, text="加载月份", command=self.load_budget).grid(
            row=1, column=1, padx=(8, 24), pady=(5, 0)
        )
        ttk.Label(settings, text="生活费预算（元）").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.budget_amount, width=18).grid(
            row=1, column=2, sticky="w", pady=(5, 0)
        )
        ttk.Button(settings, text="保存预算", command=self.save_budget).grid(
            row=1, column=3, padx=(8, 0), pady=(5, 0)
        )
        usage = ttk.LabelFrame(self.budget_tab, text="本月预算使用情况", padding=20)
        usage.pack(fill="x", pady=(20, 0))
        self.budget_status = tk.StringVar(value="请设置或加载月度预算。")
        ttk.Label(usage, textvariable=self.budget_status, style="Section.TLabel").pack(
            anchor="w", pady=(0, 14)
        )
        self.budget_progress = ttk.Progressbar(
            usage, maximum=100, mode="determinate", length=700
        )
        self.budget_progress.pack(fill="x", pady=(0, 8))
        self.budget_percent = tk.StringVar(value="0%")
        ttk.Label(
            usage,
            textvariable=self.budget_percent,
            style="Metric.TLabel",
            foreground="#2563eb",
        ).pack(anchor="w")
        self.budget_details = tk.StringVar()
        ttk.Label(
            usage, textvariable=self.budget_details, foreground="#64748b"
        ).pack(anchor="w", pady=(10, 0))

    def _update_category_choices(self, *_: object) -> None:
        categories = (
            INCOME_CATEGORIES
            if self.record_type.get() == TransactionType.INCOME.value
            else EXPENSE_CATEGORIES
        )
        current = self.record_category.get()
        self.record_category.set(current if current in categories else categories[0])
        for child in self.records_tab.winfo_children():
            if isinstance(child, ttk.LabelFrame) and child.cget("text") == "记录收支":
                for widget in child.winfo_children():
                    if isinstance(widget, ttk.Combobox) and widget.cget("textvariable") == str(
                        self.record_category
                    ):
                        widget.configure(values=categories)
                        return

    def save_record(self) -> None:
        try:
            transaction_type = TransactionType(self.record_type.get())
            transaction = self.service.save_transaction(
                self.record_date.get(),
                transaction_type,
                self.record_category.get(),
                self.record_amount.get(),
                self.record_note.get(),
                self.editing_id,
            )
        except ValueError as exc:
            messagebox.showerror("无法保存记录", str(exc), parent=self.root)
            return
        self.clear_record_form()
        self.refresh_records()
        self.refresh_budget()
        self.refresh_charts()
        self._warn_if_over_budget(transaction)

    def _warn_if_over_budget(self, transaction: Transaction) -> None:
        if transaction.transaction_type is not TransactionType.EXPENSE:
            return
        self._warn_for_month(transaction.date[:7])

    def _warn_for_month(self, month: str) -> None:
        budget, summary = self.service.budget_usage(month)
        if budget is not None and summary.net_spending_cents > budget:
            messagebox.showwarning(
                "预算超支提醒",
                f"{month} 净消费已达到 {_money(summary.net_spending_cents)}，"
                f"超过预算 {_money(budget)}。",
                parent=self.root,
            )

    def clear_record_form(self) -> None:
        self.editing_id = None
        self.record_date.set(date.today().isoformat())
        self.record_type.set(TransactionType.EXPENSE.value)
        self.record_category.set(EXPENSE_CATEGORIES[0])
        self.record_amount.set("")
        self.record_note.set("")
        self.save_record_button.configure(text="添加记录")
        for selected in self.record_table.selection():
            self.record_table.selection_remove(selected)

    def refresh_records(self) -> None:
        try:
            start = self.filter_start.get().strip() or None
            end = self.filter_end.get().strip() or None
            if start:
                self.service.normalize_date(start)
            if end:
                self.service.normalize_date(end)
            if start and end and start > end:
                raise ValueError("开始日期不能晚于结束日期。")
            transactions = self.service.list_transactions(
                start,
                end,
                self.filter_category.get()
                if self.filter_category.get() != "全部"
                else None,
            )
        except ValueError as exc:
            messagebox.showerror("筛选条件无效", str(exc), parent=self.root)
            return
        self.record_table.delete(*self.record_table.get_children())
        for item in transactions:
            self.record_table.insert(
                "",
                "end",
                iid=str(item.transaction_id),
                values=(
                    item.date,
                    item.transaction_type.value,
                    item.category,
                    _money(item.amount_cents),
                    item.note,
                ),
            )

    def reset_filters(self) -> None:
        self.filter_start.set("")
        self.filter_end.set("")
        self.filter_category.set("全部")
        self.refresh_records()

    def select_record(self, _event: tk.Event) -> None:
        selected = self.record_table.selection()
        if not selected:
            return
        transaction_id = int(selected[0])
        transaction = next(
            (
                item
                for item in self.service.list_transactions()
                if item.transaction_id == transaction_id
            ),
            None,
        )
        if transaction is None:
            messagebox.showerror("记录不存在", "所选记录已被删除，请刷新列表。", parent=self.root)
            self.refresh_records()
            return
        self.editing_id = transaction_id
        self.record_date.set(transaction.date)
        self.record_type.set(transaction.transaction_type.value)
        self.record_category.set(transaction.category)
        self.record_amount.set(_amount_text(transaction.amount_cents))
        self.record_note.set(transaction.note)
        self.save_record_button.configure(text="保存修改")

    def delete_selected(self) -> None:
        selected = self.record_table.selection()
        if not selected:
            messagebox.showinfo("删除记录", "请先选择一条记录。", parent=self.root)
            return
        if not messagebox.askyesno(
            "确认删除", "确定要删除所选记录吗？此操作无法撤销。", parent=self.root
        ):
            return
        try:
            self.service.delete_transaction(int(selected[0]))
        except ValueError as exc:
            messagebox.showerror("无法删除记录", str(exc), parent=self.root)
            self.refresh_records()
            return
        self.clear_record_form()
        self.refresh_records()
        self.refresh_budget()
        self.refresh_charts()

    def refresh_summary(self) -> None:
        try:
            start, end = self.service.period_bounds(
                self.summary_period.get(), self.summary_date.get()
            )
            summary = self.service.summary(start, end)
        except ValueError as exc:
            messagebox.showerror("统计条件无效", str(exc), parent=self.root)
            return
        self.summary_income.set(_money(summary.income_cents))
        self.summary_expense.set(_money(summary.expense_cents))
        self.summary_balance.set(_money(summary.income_cents - summary.expense_cents))

    def refresh_charts(self) -> None:
        try:
            month = self.service.normalize_month(self.chart_month.get())
            year_text = self.chart_year.get().strip()
            if len(year_text) != 4 or not year_text.isdigit():
                raise ValueError("趋势年份必须为四位数字。")
            year = int(year_text)
            if year < 1 or year > 9998:
                raise ValueError("趋势年份超出有效范围。")
        except ValueError as exc:
            messagebox.showerror("图表条件无效", str(exc), parent=self.root)
            return
        category_totals = self.service.category_totals(month)
        for axis, transaction_type, title, color in (
            (
                self.expense_axis,
                TransactionType.EXPENSE,
                f"{month} 支出分类占比",
                "#e76f51",
            ),
            (
                self.income_axis,
                TransactionType.INCOME,
                f"{month} 收入分类占比",
                "#2a9d8f",
            ),
        ):
            axis.clear()
            totals = [
                item
                for item in category_totals
                if item.transaction_type is transaction_type
            ]
            if totals:
                axis.pie(
                    [item.amount_cents for item in totals],
                    labels=[item.category for item in totals],
                    autopct="%1.0f%%",
                    startangle=90,
                    textprops={"fontsize": 8},
                    colors=self._chart_colors(len(totals), color),
                )
                axis.axis("equal")
            else:
                axis.text(0.5, 0.5, "暂无数据", ha="center", va="center")
                axis.set_axis_off()
            axis.set_title(title, fontsize=10)
        trend = self.service.monthly_trend(year)
        months = [item.month[-2:] for item in trend]
        self.trend_axis.clear()
        self.trend_axis.plot(
            months,
            [item.income_cents / 100 for item in trend],
            marker="o",
            label="收入",
            color="#2a9d8f",
        )
        self.trend_axis.plot(
            months,
            [item.expense_cents / 100 for item in trend],
            marker="o",
            label="支出",
            color="#e76f51",
        )
        self.trend_axis.set_title(f"{year} 年月度收支趋势", fontsize=10)
        self.trend_axis.set_xlabel("月份")
        self.trend_axis.set_ylabel("金额（元）")
        self.trend_axis.set_xticks(range(12), months)
        self.trend_axis.grid(True, alpha=0.25)
        self.trend_axis.legend(fontsize=8)
        self.figure.tight_layout()
        self.chart_canvas.draw_idle()

    @staticmethod
    def _chart_colors(count: int, base_color: str) -> list[str]:
        from matplotlib import colormaps

        palette = colormaps["tab20"]
        return [base_color if index == 0 else palette(index % 20) for index in range(count)]

    def load_budget(self) -> None:
        try:
            month = self.service.normalize_month(self.budget_month.get())
        except ValueError as exc:
            messagebox.showerror("月份无效", str(exc), parent=self.root)
            return
        self.budget_month.set(month)
        budget, _summary = self.service.budget_usage(month)
        self.budget_amount.set(_amount_text(budget) if budget is not None else "")
        self.refresh_budget()
        self._warn_for_month(month)

    def save_budget(self) -> None:
        try:
            amount_cents = self.service.set_budget(
                self.budget_month.get(), self.budget_amount.get()
            )
            month = self.service.normalize_month(self.budget_month.get())
        except ValueError as exc:
            messagebox.showerror("预算无效", str(exc), parent=self.root)
            return
        self.budget_month.set(month)
        self.budget_amount.set(_amount_text(amount_cents))
        self.refresh_budget()
        self._warn_for_month(month)

    def refresh_budget(self) -> None:
        month = self.budget_month.get().strip()
        try:
            budget, summary = self.service.budget_usage(month)
        except ValueError:
            self.budget_status.set("请检查月份格式（YYYY-MM）。")
            self.budget_percent.set("—")
            self.budget_progress.configure(value=0)
            self.budget_details.set("")
            return
        if budget is None:
            self.budget_status.set(f"{month} 尚未设置预算。")
            self.budget_percent.set("—")
            self.budget_progress.configure(value=0)
            self.budget_details.set(
                f"本月收入：{_money(summary.income_cents)}    "
                f"本月支出：{_money(summary.expense_cents)}"
            )
            return
        net_spending = summary.net_spending_cents
        ratio = net_spending / budget * 100
        self.budget_progress.configure(value=min(max(ratio, 0), 100))
        self.budget_percent.set(f"{ratio:.1f}%")
        self.budget_status.set(
            f"{month} 净消费：{_money(net_spending)} / 预算：{_money(budget)}"
        )
        self.budget_details.set(
            f"本月收入：{_money(summary.income_cents)}    "
            f"本月支出：{_money(summary.expense_cents)}    "
            f"净消费 = 支出 - 收入    "
            f"{'已超预算 ' + _money(net_spending - budget) if ratio > 100 else '预算剩余 ' + _money(budget - net_spending)}"
        )

    def _on_tab_changed(self, _event: tk.Event) -> None:
        selected = self.tabs.select()
        if selected == str(self.statistics_tab):
            self.refresh_summary()
            self.refresh_charts()
        elif selected == str(self.budget_tab):
            self.refresh_budget()
