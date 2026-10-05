"""Tkinter user interface for records, analysis, and budget reminders."""

import calendar
import re
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from accounting.database import AccountingRepository
from accounting.models import Transaction, TransactionType
from accounting.services import AccountingService


def _money(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    return f"￥{sign}{whole:,}.{fraction:02d}"


def _amount_text(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def _validated_entry(
    master: tk.Misc,
    variable: tk.StringVar,
    *,
    max_length: int,
    amount: bool = False,
    width: int,
) -> ttk.Entry:
    def accepts(value: str) -> bool:
        if len(value) > max_length:
            return False
        if amount:
            return bool(re.fullmatch(r"[0-9]{0,12}(?:\.[0-9]{0,2})?", value))
        return "\n" not in value and "\r" not in value

    validator = master.register(accepts)
    return ttk.Entry(
        master,
        textvariable=variable,
        width=width,
        validate="key",
        validatecommand=(validator, "%P"),
    )


class DateSelector(ttk.Frame):
    def __init__(self, master: tk.Misc, selected_date: date | None = None) -> None:
        super().__init__(master)
        initial = selected_date or date.today()
        years = tuple(str(year) for year in range(1900, 2101))
        self.year = tk.StringVar(value=str(initial.year))
        self.month = tk.StringVar(value=f"{initial.month:02d}")
        self.day = tk.StringVar(value=f"{initial.day:02d}")
        self.year_box = ttk.Combobox(
            self, textvariable=self.year, values=years, state="readonly", width=6
        )
        self.month_box = ttk.Combobox(
            self,
            textvariable=self.month,
            values=tuple(f"{month:02d}" for month in range(1, 13)),
            state="readonly",
            width=3,
        )
        self.day_box = ttk.Combobox(self, textvariable=self.day, state="readonly", width=3)
        self.year_box.pack(side="left")
        ttk.Label(self, text="年").pack(side="left")
        self.month_box.pack(side="left")
        ttk.Label(self, text="月").pack(side="left")
        self.day_box.pack(side="left")
        ttk.Label(self, text="日").pack(side="left")
        self.year.trace_add("write", self._update_days)
        self.month.trace_add("write", self._update_days)
        self._update_days()

    def _update_days(self, *_: object) -> None:
        try:
            year, month = int(self.year.get()), int(self.month.get())
            days = calendar.monthrange(year, month)[1]
        except ValueError:
            return
        self.day_box.configure(values=tuple(f"{day:02d}" for day in range(1, days + 1)))
        if self.day.get() and int(self.day.get()) > days:
            self.day.set(f"{days:02d}")

    def get_date(self) -> str:
        return date(
            int(self.year.get()), int(self.month.get()), int(self.day.get())
        ).isoformat()

    def set_date(self, value: str) -> None:
        selected = date.fromisoformat(value)
        self.year.set(str(selected.year))
        self.month.set(f"{selected.month:02d}")
        self.day.set(f"{selected.day:02d}")

    def set_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self.year_box.configure(state=state)
        self.month_box.configure(state=state)
        self.day_box.configure(state=state)


class MonthSelector(ttk.Frame):
    def __init__(self, master: tk.Misc, selected_month: str | None = None) -> None:
        super().__init__(master)
        initial = date.today() if selected_month is None else date.fromisoformat(
            f"{selected_month}-01"
        )
        self.year = tk.StringVar(value=str(initial.year))
        self.month = tk.StringVar(value=f"{initial.month:02d}")
        ttk.Combobox(
            self,
            textvariable=self.year,
            values=tuple(str(year) for year in range(1900, 2101)),
            state="readonly",
            width=6,
        ).pack(side="left")
        ttk.Label(self, text="年").pack(side="left")
        ttk.Combobox(
            self,
            textvariable=self.month,
            values=tuple(f"{month:02d}" for month in range(1, 13)),
            state="readonly",
            width=3,
        ).pack(side="left")
        ttk.Label(self, text="月").pack(side="left")

    def get_month(self) -> str:
        return f"{self.year.get()}-{self.month.get()}"

    def set_month(self, value: str) -> None:
        selected = date.fromisoformat(f"{value}-01")
        self.year.set(str(selected.year))
        self.month.set(f"{selected.month:02d}")


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
        self.root.geometry("1180x820")
        self.root.minsize(1080, 760)
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
        style.configure(
            "Income.Horizontal.TProgressbar",
            background="#15966b",
            troughcolor="#dcefe8",
        )
        style.configure(
            "Expense.Horizontal.TProgressbar",
            background="#e05b5b",
            troughcolor="#f8e1e1",
        )

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
        self.record_date = DateSelector(form)
        self.record_type = tk.StringVar(value=TransactionType.EXPENSE.value)
        self.record_category = tk.StringVar()
        self.record_amount = tk.StringVar()
        self.record_note = tk.StringVar()
        ttk.Label(form, text="日期（下拉选择）").grid(row=0, column=0, sticky="w")
        self.record_date.grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Label(form, text="收支类型").grid(row=0, column=1, sticky="w")
        ttk.Combobox(
            form,
            textvariable=self.record_type,
            values=[kind.value for kind in TransactionType],
            state="readonly",
            width=9,
        ).grid(row=1, column=1, sticky="w", padx=(0, 10))
        ttk.Label(form, text="分类").grid(row=0, column=2, sticky="w")
        self.record_category_box = ttk.Combobox(
            form, textvariable=self.record_category, state="readonly", width=12
        )
        self.record_category_box.grid(row=1, column=2, sticky="w", padx=(0, 10))
        ttk.Label(form, text="金额（元，必填）").grid(
            row=0, column=3, sticky="w"
        )
        _validated_entry(
            form, self.record_amount, max_length=15, amount=True, width=17
        ).grid(
            row=1, column=3, sticky="ew", padx=(0, 10)
        )
        ttk.Label(form, text="备注（选填）").grid(
            row=0, column=4, sticky="w"
        )
        _validated_entry(
            form, self.record_note, max_length=100, width=25
        ).grid(
            row=1, column=4, sticky="ew", padx=(0, 10)
        )
        ttk.Label(
            form,
            text="金额：0 < 金额 ≤ 999,999,999,999.99；最多 12 位整数、2 位小数。备注：最多 100 字符。",
            foreground="#64748b",
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        form.columnconfigure(4, weight=1)
        self.record_type.trace_add("write", self._update_category_choices)
        self._update_category_choices()
        buttons = ttk.Frame(form)
        buttons.grid(row=1, column=5, sticky="e")
        self.save_record_button = ttk.Button(
            buttons, text="添加记录", command=self.save_record
        )
        self.save_record_button.pack(side="left", padx=(0, 6))
        self.reset_record_button = ttk.Button(
            buttons, text="重置", command=self.clear_record_form
        )
        self.reset_record_button.pack(side="left")

        ttk.Button(
            self.records_tab, text="管理分类", command=self.manage_categories
        ).pack(anchor="e", pady=(0, 8))

        filters = ttk.LabelFrame(self.records_tab, text="筛选记录", padding=10)
        filters.pack(fill="x", pady=(0, 10))
        self.filter_start_enabled = tk.BooleanVar(value=False)
        self.filter_end_enabled = tk.BooleanVar(value=False)
        date_filters = ttk.Frame(filters)
        date_filters.grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Checkbutton(
            date_filters,
            text="启用开始日期",
            variable=self.filter_start_enabled,
            command=self._update_filter_date_states,
        ).grid(row=0, column=0, sticky="w")
        self.filter_start = DateSelector(date_filters)
        self.filter_start.grid(row=0, column=1, sticky="w", padx=(5, 18))
        ttk.Checkbutton(
            date_filters,
            text="启用结束日期",
            variable=self.filter_end_enabled,
            command=self._update_filter_date_states,
        ).grid(row=0, column=2, sticky="w")
        self.filter_end = DateSelector(date_filters)
        self.filter_end.grid(row=0, column=3, sticky="w", padx=(5, 0))
        self.filter_type = tk.StringVar(value="全部")
        self.filter_category = tk.StringVar(value="全部")
        ttk.Label(filters, text="收支类型").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.filter_type_box = ttk.Combobox(
            filters,
            textvariable=self.filter_type,
            values=["全部", *[kind.value for kind in TransactionType]],
            state="readonly",
            width=8,
        )
        self.filter_type_box.grid(row=1, column=1, sticky="w", padx=(5, 16), pady=(8, 0))
        self.filter_type.trace_add("write", self._update_filter_categories)
        ttk.Label(filters, text="分类").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.filter_category_box = ttk.Combobox(
            filters,
            textvariable=self.filter_category,
            values=["全部"],
            state="disabled",
            width=12,
        )
        self.filter_category_box.grid(
            row=1, column=3, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        ttk.Button(filters, text="应用筛选", command=self.refresh_records).grid(
            row=1, column=4, sticky="w", pady=(8, 0)
        )
        ttk.Button(filters, text="重置", command=self.reset_filters).grid(
            row=1, column=5, sticky="w", padx=(6, 0), pady=(8, 0)
        )
        ttk.Label(
            filters,
            text="日期范围：勾选后生效；分类筛选需先选择收支类型。",
            foreground="#64748b",
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self._update_filter_date_states()

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
        controls = ttk.Frame(summary_box)
        controls.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(controls, text="统计周期").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.summary_period,
            values=["日", "周", "月", "年"],
            state="readonly",
            width=8,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0), padx=(0, 16))
        ttk.Label(controls, text="统计日期").grid(row=0, column=1, sticky="w")
        self.summary_date = DateSelector(controls)
        self.summary_date.grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(
            controls,
            text="日按所选日统计；周、月、年按所选日期所在周期统计。",
            foreground="#64748b",
        ).grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Button(
            controls, text="查询汇总", command=self.refresh_summary
        ).grid(row=1, column=3, padx=(12, 0), sticky="w")
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
            card.grid(row=1, column=column - 3, sticky="nsew", padx=8, pady=4)
            ttk.Label(card, text=label, foreground="#64748b").pack(anchor="w")
            ttk.Label(card, textvariable=variable, style="Metric.TLabel", foreground=color).pack(
                anchor="w", pady=(4, 0)
            )
            summary_box.columnconfigure(column - 3, weight=1)
        for column in range(3):
            summary_box.columnconfigure(column, weight=1)
        charts_box = ttk.LabelFrame(
            self.statistics_tab, text="月度分类占比与收支趋势", padding=6
        )
        charts_box.pack(fill="both", expand=True)
        controls = ttk.Frame(charts_box)
        controls.pack(fill="x", padx=5, pady=(2, 5))
        ttk.Label(controls, text="分类占比月份").pack(side="left")
        self.chart_month = MonthSelector(controls)
        self.chart_month.pack(side="left", padx=(6, 16))
        ttk.Label(controls, text="趋势年份").pack(side="left")
        self.chart_year = tk.StringVar(value=str(date.today().year))
        ttk.Combobox(
            controls,
            textvariable=self.chart_year,
            values=tuple(str(year) for year in range(1900, 2101)),
            state="readonly",
            width=6,
        ).pack(side="left", padx=(6, 12))
        ttk.Button(controls, text="更新图表", command=self.refresh_charts).pack(
            side="left"
        )
        self.figure = Figure(figsize=(10, 4.2), dpi=100, tight_layout=True)
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
        self.budget_month = MonthSelector(settings)
        self.budget_amount = tk.StringVar()
        ttk.Label(settings, text="预算月份（选择年份和月份）").grid(
            row=0, column=0, sticky="w"
        )
        self.budget_month.grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Button(settings, text="加载月份", command=self.load_budget).grid(
            row=1, column=1, padx=(8, 24), pady=(5, 0)
        )
        ttk.Label(settings, text="生活费预算（元，必填）").grid(
            row=0, column=2, sticky="w"
        )
        _validated_entry(
            settings, self.budget_amount, max_length=15, amount=True, width=18
        ).grid(
            row=1, column=2, sticky="w", pady=(5, 0)
        )
        ttk.Button(settings, text="保存预算", command=self.save_budget).grid(
            row=1, column=3, padx=(8, 0), pady=(5, 0)
        )
        ttk.Label(
            settings,
            text="格式：最多 12 位整数和 2 位小数；范围 0 < 预算 ≤ 999,999,999,999.99。",
            foreground="#64748b",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
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
        self.budget_percent_label = ttk.Label(
            usage,
            textvariable=self.budget_percent,
            style="Metric.TLabel",
            foreground="#2563eb",
        )
        self.budget_percent_label.pack(anchor="w")
        self.budget_notice = tk.StringVar()
        self.budget_notice_label = ttk.Label(
            usage,
            textvariable=self.budget_notice,
            foreground="#64748b",
            style="Section.TLabel",
        )
        self.budget_notice_label.pack(anchor="w", pady=(4, 0))
        self.budget_details = tk.StringVar()
        ttk.Label(
            usage, textvariable=self.budget_details, foreground="#64748b"
        ).pack(anchor="w", pady=(10, 0))

    def _update_category_choices(self, *_: object) -> None:
        transaction_type = TransactionType(self.record_type.get())
        categories = self.service.categories(transaction_type)
        current = self.record_category.get()
        self.record_category_box.configure(values=categories)
        self.record_category.set(
            current if current in categories else categories[0] if categories else ""
        )

    def _update_filter_categories(self, *_: object) -> None:
        selected_type = self.filter_type.get()
        if selected_type == "全部":
            self.filter_category_box.configure(values=["全部"], state="disabled")
            self.filter_category.set("全部")
            return
        transaction_type = TransactionType(selected_type)
        categories = self.service.categories(transaction_type)
        values = ["全部", *categories]
        current = self.filter_category.get()
        self.filter_category_box.configure(values=values, state="readonly")
        self.filter_category.set(current if current in values else "全部")

    def _update_filter_date_states(self) -> None:
        self.filter_start.set_enabled(self.filter_start_enabled.get())
        self.filter_end.set_enabled(self.filter_end_enabled.get())

    def manage_categories(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("管理收支分类")
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        transaction_type = tk.StringVar(value=TransactionType.EXPENSE.value)
        category_name = tk.StringVar()

        ttk.Label(window, text="收支类型").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4)
        )
        type_box = ttk.Combobox(
            window,
            textvariable=transaction_type,
            values=[kind.value for kind in TransactionType],
            state="readonly",
            width=12,
        )
        type_box.grid(row=1, column=0, sticky="w", padx=12)
        ttk.Label(
            window,
            text="分类名称（必填，1–20 个字符，同类型下不可重名）",
        ).grid(row=2, column=0, sticky="w", padx=12, pady=(12, 4))
        _validated_entry(
            window, category_name, max_length=20, width=32
        ).grid(
            row=3, column=0, sticky="ew", padx=12
        )
        ttk.Label(
            window,
            text="内置分类不能删除；已有记录使用中的分类也不能删除。",
            foreground="#64748b",
        ).grid(row=4, column=0, sticky="w", padx=12, pady=(8, 4))
        category_list = tk.Listbox(window, height=9, exportselection=False)
        category_list.grid(row=5, column=0, sticky="ew", padx=12, pady=(4, 8))
        actions = ttk.Frame(window)
        actions.grid(row=6, column=0, sticky="e", padx=12, pady=(0, 12))

        def refresh_category_list(*_args: object) -> None:
            category_list.delete(0, tk.END)
            categories = self.service.categories(TransactionType(transaction_type.get()))
            if categories:
                category_list.insert(tk.END, *categories)

        def add_category() -> None:
            try:
                self.service.add_category(
                    TransactionType(transaction_type.get()), category_name.get()
                )
            except ValueError as exc:
                messagebox.showerror("无法添加分类", str(exc), parent=window)
                return
            category_name.set("")
            refresh_category_list()
            self._update_category_choices()
            self._update_filter_categories()

        def delete_category() -> None:
            selected = category_list.curselection()
            if not selected:
                messagebox.showinfo("删除分类", "请先选择要删除的分类。", parent=window)
                return
            category = category_list.get(selected[0])
            try:
                self.service.delete_category(
                    TransactionType(transaction_type.get()), category
                )
            except ValueError as exc:
                messagebox.showerror("无法删除分类", str(exc), parent=window)
                return
            refresh_category_list()
            self._update_category_choices()
            self._update_filter_categories()

        ttk.Button(actions, text="添加分类", command=add_category).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(actions, text="删除所选", command=delete_category).pack(side="left")
        type_box.bind("<<ComboboxSelected>>", refresh_category_list)
        refresh_category_list()

    def save_record(self) -> None:
        try:
            transaction_type = TransactionType(self.record_type.get())
            transaction = self.service.save_transaction(
                self.record_date.get_date(),
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
        self.record_date.set_date(date.today().isoformat())
        self.record_type.set(TransactionType.EXPENSE.value)
        categories = self.service.categories(TransactionType.EXPENSE)
        self.record_category.set(categories[0] if categories else "")
        self.record_amount.set("")
        self.record_note.set("")
        self.save_record_button.configure(text="添加记录")
        self.reset_record_button.configure(text="重置")
        for selected in self.record_table.selection():
            self.record_table.selection_remove(selected)

    def refresh_records(self) -> None:
        try:
            start = self.filter_start.get_date() if self.filter_start_enabled.get() else None
            end = self.filter_end.get_date() if self.filter_end_enabled.get() else None
            if start and end and start > end:
                raise ValueError("开始日期不能晚于结束日期。")
            selected_type = self.filter_type.get()
            transaction_type = (
                None if selected_type == "全部" else TransactionType(selected_type)
            )
            category = (
                self.filter_category.get()
                if self.filter_category.get() != "全部"
                else None
            )
            transactions = self.service.list_transactions(
                start,
                end,
                category,
                transaction_type,
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
        self.filter_start_enabled.set(False)
        self.filter_end_enabled.set(False)
        self._update_filter_date_states()
        self.filter_category.set("全部")
        self.filter_type.set("全部")
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
        self.record_date.set_date(transaction.date)
        self.record_type.set(transaction.transaction_type.value)
        self.record_category.set(transaction.category)
        self.record_amount.set(_amount_text(transaction.amount_cents))
        self.record_note.set(transaction.note)
        self.save_record_button.configure(text="保存修改")
        self.reset_record_button.configure(text="退出修改")

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
                self.summary_period.get(), self.summary_date.get_date()
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
            month = self.service.normalize_month(self.chart_month.get_month())
            year = int(self.chart_year.get())
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
            month = self.service.normalize_month(self.budget_month.get_month())
        except ValueError as exc:
            messagebox.showerror("月份无效", str(exc), parent=self.root)
            return
        self.budget_month.set_month(month)
        budget, _summary = self.service.budget_usage(month)
        self.budget_amount.set(_amount_text(budget) if budget is not None else "")
        self.refresh_budget()
        self._warn_for_month(month)

    def save_budget(self) -> None:
        try:
            amount_cents = self.service.set_budget(
                self.budget_month.get_month(), self.budget_amount.get()
            )
            month = self.service.normalize_month(self.budget_month.get_month())
        except ValueError as exc:
            messagebox.showerror("预算无效", str(exc), parent=self.root)
            return
        self.budget_month.set_month(month)
        self.budget_amount.set(_amount_text(amount_cents))
        self.refresh_budget()
        self._warn_for_month(month)

    def refresh_budget(self) -> None:
        month = self.budget_month.get_month()
        try:
            budget, summary = self.service.budget_usage(month)
        except ValueError:
            self.budget_status.set("请检查月份格式（YYYY-MM）。")
            self.budget_percent.set("—")
            self.budget_notice.set("")
            self.budget_progress.pack(fill="x", pady=(0, 8))
            self.budget_progress.configure(value=0)
            self.budget_progress.configure(style="Horizontal.TProgressbar")
            self.budget_percent_label.configure(foreground="#2563eb")
            self.budget_details.set("")
            return
        if budget is None:
            self.budget_status.set(f"{month} 尚未设置预算。")
            self.budget_percent.set("—")
            self.budget_notice.set("")
            self.budget_progress.pack(fill="x", pady=(0, 8))
            self.budget_progress.configure(value=0)
            self.budget_progress.configure(style="Horizontal.TProgressbar")
            self.budget_percent_label.configure(foreground="#2563eb")
            self.budget_details.set(
                f"本月收入：{_money(summary.income_cents)}    "
                f"本月支出：{_money(summary.expense_cents)}"
            )
            return
        net_spending = summary.net_spending_cents
        self.budget_details.set(
            f"本月收入：{_money(summary.income_cents)}    "
            f"本月支出：{_money(summary.expense_cents)}"
        )
        if net_spending < 0:
            net_income = -net_spending
            self.budget_status.set(
                f"{month} 净收入：{_money(net_income)} / 预算：{_money(budget)}"
            )
            self.budget_progress.pack_forget()
            self.budget_percent.set(f"恭喜本月赚了 {_money(net_income)}！")
            self.budget_percent_label.configure(foreground="#15966b")
            self.budget_notice.set("")
            return

        ratio = net_spending / budget * 100
        self.budget_status.set(
            f"{month} 净消费：{_money(net_spending)} / 预算：{_money(budget)}"
        )
        self.budget_progress.pack(fill="x", pady=(0, 8))
        over_half_budget = net_spending * 2 > budget
        progress_color = (
            "Expense.Horizontal.TProgressbar" if over_half_budget
            else "Income.Horizontal.TProgressbar"
        )
        self.budget_progress.configure(
            value=min(ratio, 100), style=progress_color
        )
        self.budget_percent.set(f"{ratio:.1f}%")
        self.budget_percent_label.configure(
            foreground="#e05b5b" if over_half_budget else "#15966b"
        )
        remaining = budget - net_spending
        if remaining < 0:
            notice = f"已超预算 {_money(-remaining)}"
            notice_color = "#e05b5b"
        elif over_half_budget:
            notice = f"预算剩余不多：{_money(remaining)}"
            notice_color = "#e05b5b"
        else:
            notice = f"预算剩余：{_money(remaining)}"
            notice_color = "#64748b"
        self.budget_notice.set(notice)
        self.budget_notice_label.configure(foreground=notice_color)
        self.budget_details.set(
            f"本月收入：{_money(summary.income_cents)}    "
            f"本月支出：{_money(summary.expense_cents)}"
        )

    def _on_tab_changed(self, _event: tk.Event) -> None:
        selected = self.tabs.select()
        if selected == str(self.statistics_tab):
            self.refresh_summary()
            self.refresh_charts()
        elif selected == str(self.budget_tab):
            self.refresh_budget()
