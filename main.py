"""Launch the personal accounting desktop application."""

from pathlib import Path
import tkinter as tk

from accounting.gui import AccountingApp


def main() -> None:
    root = tk.Tk()
    database_path = Path(__file__).resolve().parent / "data" / "accounting.db"
    AccountingApp(root, database_path)
    root.mainloop()


if __name__ == "__main__":
    main()

