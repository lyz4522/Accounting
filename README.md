# 个人消费记账 GUI

基于 Python、Tkinter、SQLite 和 Matplotlib 的本地桌面记账应用。收支数据保存在本机 SQLite 数据库中，不需要账号或网络服务。

## 功能

- **收支记录**：添加、修改、删除收入或支出；日期通过年/月/日下拉框选择；按日期范围、收支类型和对应分类筛选；支持增加和删除自定义分类。
- **统计分析**：查看日、周、月、年收入、支出和结余；查看指定月份收入/支出分类占比饼图，以及指定年份逐月收支趋势图。
- **预算提醒**：通过年/月下拉框选择月份并设置生活费预算，以「支出 - 收入」计算净消费及预算使用比例；净消费超过预算时弹窗提醒。
- **本地存储**：数据库自动创建在 `data/accounting.db`。该目录已加入 `.gitignore`，个人账目不会随代码上传 GitHub。

## 环境要求

- Python 3.10 或更新版本
- Windows、macOS 或 Linux 桌面环境（需有 Tk 支持）

## 安装与启动

在项目根目录运行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

macOS 或 Linux 可使用 `python3 -m venv .venv` 创建虚拟环境，并运行 `. .venv/bin/activate` 激活。

## 测试

```powershell
python -m unittest discover -v
```

测试使用临时数据库，不会读取或修改日常使用的账目数据。

## 金额与预算说明

金额必须大于零且最多保留两位小数；备注可选，最多 100 个字符。自定义分类名称必填，最多 20 个字符，同类型分类不能重名。内置分类不能删除；已有记录使用中的分类需先修改或删除相关记录后才能删除。预算按月份分别保存；净消费为当月支出减去当月收入，因此收入大于支出时使用比例为负值，进度条显示为零，但实际数值仍会显示。
