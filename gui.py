"""
Payroll WhatsApp Sender — Tkinter GUI Application.

Provides a modern dark-themed interface for sending wage slips
via WhatsApp. All network operations run in a background thread
so the GUI stays responsive.
"""

import os
import platform
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from dotenv import load_dotenv

from logger_config import setup_logger
from send_payslips import PayslipSender

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BG = "#1a1a2e"
CARD_BG = "#16213e"
ACCENT = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT = "#ffffff"
SUCCESS = "#4ecca3"
ERROR = "#e94560"
INFO = "#a8a8b3"


class PayrollApp(tk.Tk):
    """Main application window for the Payroll WhatsApp Sender."""

    # ------------------------------------------------------------------ #
    # Initialisation
    # ------------------------------------------------------------------ #
    def __init__(self) -> None:
        """Set up the entire GUI, load configuration and initialise state."""
        super().__init__()

        # Load .env from project root
        dotenv_path: Path = PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path)

        # Logger
        self._logger = setup_logger("gui")

        # Window basics
        self.title("Payroll WhatsApp Sender")
        self.minsize(700, 800)
        self.configure(bg=BG)
        self.resizable(True, True)

        # State
        self._sender: Optional[PayslipSender] = None
        self._send_thread: Optional[threading.Thread] = None
        self._total: int = 0
        self._success: int = 0
        self._failed: int = 0
        self._skipped: int = 0
        self._record_count: int = 0  # total expected records for progress bar

        # Build UI
        self._configure_styles()
        self._build_header()
        self._build_settings()
        self._build_actions()
        self._build_progress()
        self._build_log()
        self._build_summary()
        self._build_footer()

        self._logger.info("GUI initialised.")

    # ------------------------------------------------------------------ #
    # ttk Style configuration
    # ------------------------------------------------------------------ #
    def _configure_styles(self) -> None:
        """Configure ttk styles for the dark theme."""
        style = ttk.Style(self)
        style.theme_use("clam")

        # General
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD_BG)

        # Frames / LabelFrames
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure(
            "TLabelframe",
            background=CARD_BG,
            foreground=TEXT,
            borderwidth=2,
            relief="groove",
        )
        style.configure(
            "TLabelframe.Label",
            background=CARD_BG,
            foreground=HIGHLIGHT,
            font=("Segoe UI", 11, "bold"),
        )

        # Labels
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=INFO, font=("Segoe UI", 11))
        style.configure("Success.TLabel", background=CARD_BG, foreground=SUCCESS, font=("Segoe UI", 13, "bold"))
        style.configure("Error.TLabel", background=CARD_BG, foreground=ERROR, font=("Segoe UI", 13, "bold"))
        style.configure("Info.TLabel", background=CARD_BG, foreground=INFO, font=("Segoe UI", 13, "bold"))
        style.configure("Count.TLabel", background=CARD_BG, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Progress.TLabel", background=CARD_BG, foreground=INFO, font=("Segoe UI", 10))

        # Entries
        style.configure("TEntry", fieldbackground=ACCENT, foreground=TEXT, insertcolor=TEXT)

        # Buttons
        style.configure(
            "Accent.TButton",
            background=HIGHLIGHT,
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
            padding=(20, 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#c73652"), ("disabled", "#555555")],
            foreground=[("disabled", "#999999")],
        )
        style.configure(
            "Secondary.TButton",
            background=ACCENT,
            foreground=TEXT,
            font=("Segoe UI", 10),
            padding=(14, 6),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#1a4a7a"), ("disabled", "#444444")],
            foreground=[("disabled", "#888888")],
        )
        style.configure(
            "Stop.TButton",
            background="#c0392b",
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
            padding=(20, 10),
        )
        style.map(
            "Stop.TButton",
            background=[("active", "#a93226"), ("disabled", "#555555")],
            foreground=[("disabled", "#999999")],
        )

        # Progressbar
        style.configure(
            "green.Horizontal.TProgressbar",
            troughcolor=ACCENT,
            background=SUCCESS,
            thickness=22,
        )

    # ------------------------------------------------------------------ #
    # UI builder helpers
    # ------------------------------------------------------------------ #
    def _build_header(self) -> None:
        """Build the header frame with title and subtitle."""
        frame = ttk.Frame(self, style="TFrame")
        frame.pack(fill=tk.X, padx=20, pady=(18, 4))

        ttk.Label(frame, text="Payroll WhatsApp Sender", style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text="Send wage slips via WhatsApp", style="Sub.TLabel").pack(anchor=tk.W, pady=(2, 0))

    def _build_settings(self) -> None:
        """Build the settings LabelFrame with Excel file, template and month fields."""
        lf = ttk.LabelFrame(self, text="  Settings  ", style="TLabelframe")
        lf.pack(fill=tk.X, padx=20, pady=10)
        inner = ttk.Frame(lf, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=12, pady=10)

        # Row 0 — Excel file
        ttk.Label(inner, text="Excel File:", style="Card.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8), pady=6
        )
        self._excel_var = tk.StringVar()
        self._excel_entry = ttk.Entry(inner, textvariable=self._excel_var, state="readonly", width=48)
        self._excel_entry.grid(row=0, column=1, sticky=tk.EW, padx=4, pady=6)
        ttk.Button(inner, text="Browse…", style="Secondary.TButton", command=self.browse_file).grid(
            row=0, column=2, padx=(6, 0), pady=6
        )

        # Row 1 — Template name
        ttk.Label(inner, text="Template Name:", style="Card.TLabel").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=6
        )
        self._template_var = tk.StringVar(value=os.getenv("TEMPLATE_NAME", ""))
        ttk.Entry(inner, textvariable=self._template_var, width=48).grid(
            row=1, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=6
        )

        # Row 2 — Month / Year
        current_month_year: str = datetime.now().strftime("%B %Y")
        ttk.Label(inner, text="Month/Year:", style="Card.TLabel").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=6
        )
        self._month_var = tk.StringVar(value=current_month_year)
        ttk.Entry(inner, textvariable=self._month_var, width=48).grid(
            row=2, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=6
        )

        inner.columnconfigure(1, weight=1)

    def _build_actions(self) -> None:
        """Build the action frame with Start and Stop buttons."""
        frame = ttk.Frame(self, style="TFrame")
        frame.pack(fill=tk.X, padx=20, pady=6)

        self._start_btn = ttk.Button(
            frame, text="▶  Start Sending", style="Accent.TButton", command=self.start_sending
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self._stop_btn = ttk.Button(
            frame, text="■  Stop", style="Stop.TButton", command=self.stop_sending, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT)

    def _build_progress(self) -> None:
        """Build the progress LabelFrame with a progress bar and counter label."""
        lf = ttk.LabelFrame(self, text="  Progress  ", style="TLabelframe")
        lf.pack(fill=tk.X, padx=20, pady=6)
        inner = ttk.Frame(lf, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=12, pady=10)

        self._progressbar = ttk.Progressbar(
            inner, orient=tk.HORIZONTAL, mode="determinate", style="green.Horizontal.TProgressbar"
        )
        self._progressbar.pack(fill=tk.X, pady=(0, 6))

        self._progress_label = ttk.Label(inner, text="0 / 0", style="Progress.TLabel")
        self._progress_label.pack(anchor=tk.E)

    def _build_log(self) -> None:
        """Build the activity-log LabelFrame with a scrolled Text widget."""
        lf = ttk.LabelFrame(self, text="  Activity Log  ", style="TLabelframe")
        lf.pack(fill=tk.BOTH, expand=True, padx=20, pady=6)

        container = tk.Frame(lf, bg=CARD_BG)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        scrollbar = tk.Scrollbar(container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._log_text = tk.Text(
            container,
            height=12,
            wrap=tk.WORD,
            bg="#0d1b2a",
            fg=TEXT,
            font=("Consolas", 10),
            insertbackground=TEXT,
            selectbackground=ACCENT,
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            state=tk.DISABLED,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._log_text.yview)

        # Colour tags
        self._log_text.tag_configure("success", foreground=SUCCESS)
        self._log_text.tag_configure("error", foreground=ERROR)
        self._log_text.tag_configure("warning", foreground="#f0c040")
        self._log_text.tag_configure("info", foreground=INFO)

    def _build_summary(self) -> None:
        """Build the summary LabelFrame with counters for Total / Success / Failed / Skipped."""
        lf = ttk.LabelFrame(self, text="  Summary  ", style="TLabelframe")
        lf.pack(fill=tk.X, padx=20, pady=6)
        inner = ttk.Frame(lf, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=12, pady=10)

        labels_config: list[tuple[str, str, str]] = [
            ("Total:", "Count.TLabel", "total"),
            ("Success:", "Success.TLabel", "success"),
            ("Failed:", "Error.TLabel", "failed"),
            ("Skipped:", "Info.TLabel", "skipped"),
        ]

        self._summary_vars: dict[str, tk.StringVar] = {}
        for col, (label_text, style_name, key) in enumerate(labels_config):
            ttk.Label(inner, text=label_text, style="Card.TLabel").grid(
                row=0, column=col * 2, sticky=tk.E, padx=(12, 2), pady=4
            )
            var = tk.StringVar(value="0")
            self._summary_vars[key] = var
            ttk.Label(inner, textvariable=var, style=style_name).grid(
                row=0, column=col * 2 + 1, sticky=tk.W, padx=(0, 12), pady=4
            )

        for col_idx in range(len(labels_config) * 2):
            inner.columnconfigure(col_idx, weight=1)

    def _build_footer(self) -> None:
        """Build the footer frame with utility buttons."""
        frame = ttk.Frame(self, style="TFrame")
        frame.pack(fill=tk.X, padx=20, pady=(6, 18))

        ttk.Button(
            frame, text="📂  Open Reports Folder", style="Secondary.TButton", command=self.open_reports_folder
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            frame, text="📋  View History", style="Secondary.TButton", command=self._view_history
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------ #
    # Public actions
    # ------------------------------------------------------------------ #
    def browse_file(self) -> None:
        """Open a file dialog for Excel files and populate the entry."""
        filepath: str = filedialog.askopenfilename(
            title="Select Payroll Excel File",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All Files", "*.*")],
            initialdir=str(PROJECT_ROOT),
        )
        if filepath:
            self._excel_var.set(filepath)
            self.log_message(f"Selected file: {filepath}", tag="info")

    def start_sending(self) -> None:
        """Validate inputs, create a PayslipSender and start the send process in a background thread."""
        # --- Input validation ---
        excel_path: str = self._excel_var.get().strip()
        template_name: str = self._template_var.get().strip()
        month_year: str = self._month_var.get().strip()

        if not excel_path:
            messagebox.showerror("Missing File", "Please select an Excel file before starting.")
            return
        if not Path(excel_path).is_file():
            messagebox.showerror("File Not Found", f"The selected file does not exist:\n{excel_path}")
            return
        if not template_name:
            messagebox.showerror("Missing Template", "Please enter a WhatsApp template name.")
            return
        if not month_year:
            messagebox.showerror("Missing Month/Year", "Please enter the month and year.")
            return

        # Check .env credentials (ACCESS_TOKEN and PHONE_NUMBER_ID)
        access_token: str = os.getenv("ACCESS_TOKEN", "").strip()
        phone_number_id: str = os.getenv("PHONE_NUMBER_ID", "").strip()
        if not access_token or not phone_number_id:
            messagebox.showerror(
                "Missing Credentials",
                "ACCESS_TOKEN and/or PHONE_NUMBER_ID are not set.\n\n"
                "Please update the .env file in the project root with:\n"
                "  ACCESS_TOKEN=<your-access-token>\n"
                "  PHONE_NUMBER_ID=<your-phone-number-id>",
            )
            return

        # --- Reset state ---
        self._total = 0
        self._success = 0
        self._failed = 0
        self._skipped = 0
        self._record_count = 0
        self._update_summary()
        self._progressbar["value"] = 0
        self._progress_label.configure(text="0 / 0")
        self._clear_log()

        # --- UI state ---
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)

        self.log_message("Initialising sender…", tag="info")

        # --- Create sender & launch thread ---
        try:
            self._sender = PayslipSender(
                excel_path=excel_path,
                template_name=template_name,
                month_year=month_year,
            )
            # Register callbacks
            self._sender.set_progress_callback(self.on_progress)
            self._sender.set_completion_callback(self.on_completion)
        except Exception as exc:
            messagebox.showerror("Initialisation Error", str(exc))
            self._start_btn.configure(state=tk.NORMAL)
            self._stop_btn.configure(state=tk.DISABLED)
            self._logger.exception("Failed to create PayslipSender.")
            return

        self._send_thread = threading.Thread(target=self._run_sender, daemon=True)
        self._send_thread.start()
        self.log_message("Sending started.", tag="info")

    def stop_sending(self) -> None:
        """Signal the background sender to stop and re-enable the Start button."""
        if self._sender is not None:
            try:
                self._sender.stop()
            except Exception:
                pass
        self.log_message("Stop requested — finishing current message…", tag="warning")
        self._stop_btn.configure(state=tk.DISABLED)

    def on_progress(self, employee_name: str, phone: str, status: str) -> None:
        """Handle a progress update from the sender thread.

        Schedules a GUI update on the main thread via ``self.after()``.

        Args:
            employee_name: Name of the employee just processed.
            phone: Phone number used.
            status: One of 'Success', 'Failed', 'Skipped', 'Already Sent', etc.
        """
        self.after(0, self._handle_progress, employee_name, phone, status)

    def on_completion(self, summary: dict) -> None:
        """Handle completion of the send process.

        Schedules a GUI update on the main thread via ``self.after()``.

        Args:
            summary: Dictionary with keys like ``total``, ``success``, ``failed``, ``skipped``.
        """
        self.after(0, self._handle_completion, summary)

    def log_message(self, message: str, tag: str = "info") -> None:
        """Append a timestamped message to the log text widget.

        Args:
            message: The text to display.
            tag: Colour tag — ``'info'``, ``'success'``, ``'error'``, or ``'warning'``.
        """
        timestamp: str = datetime.now().strftime("%H:%M:%S")
        line: str = f"[{timestamp}]  {message}\n"
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, line, tag)
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def open_reports_folder(self) -> None:
        """Open the ``reports/`` directory in the system file manager."""
        reports_dir: Path = PROJECT_ROOT / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path_str: str = str(reports_dir)

        system: str = platform.system()
        try:
            if system == "Windows":
                os.startfile(path_str)  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.Popen(["open", path_str])
            else:
                subprocess.Popen(["xdg-open", path_str])
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open reports folder:\n{exc}")
            self._logger.exception("Failed to open reports folder.")

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    def _run_sender(self) -> None:
        """Target for the background sending thread."""
        try:
            if self._sender is not None:
                self._sender.process_all()
        except Exception as exc:
            self.after(0, self._handle_thread_error, str(exc))

    def _handle_progress(self, employee_name: str, phone: str, status: str) -> None:
        """Process a progress callback on the main thread.

        Args:
            employee_name: Name of the employee just processed.
            phone: Phone number used.
            status: Result status string.
        """
        status_lower: str = status.lower()

        if "success" in status_lower:
            self._success += 1
            tag = "success"
        elif "fail" in status_lower or "error" in status_lower:
            self._failed += 1
            tag = "error"
        else:
            self._skipped += 1
            tag = "warning"

        self._total = self._success + self._failed + self._skipped
        self._update_summary()

        # Update progress bar — use sender's total record count if available
        if self._sender is not None and self._sender.total > 0:
            max_val = self._sender.total
        else:
            max_val = max(self._total, 1)

        self._progressbar.configure(maximum=max_val)
        self._progressbar["value"] = self._total
        self._progress_label.configure(text=f"{self._total} / {max_val}")

        self.log_message(f"{employee_name} ({phone}) — {status}", tag=tag)

    def _handle_completion(self, summary: dict) -> None:
        """Process completion on the main thread.

        Args:
            summary: Dictionary with result counts.
        """
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)

        total: int = summary.get("total", self._total)
        success: int = summary.get("success", self._success)
        failed: int = summary.get("failed", self._failed)
        skipped: int = summary.get("skipped", self._skipped)

        self._total = total
        self._success = success
        self._failed = failed
        self._skipped = skipped
        self._update_summary()

        processed = success + failed + skipped
        self._progressbar.configure(maximum=total if total > 0 else 1)
        self._progressbar["value"] = processed
        self._progress_label.configure(text=f"{processed} / {total}")

        self.log_message("— Sending complete —", tag="info")

        report_path: str = summary.get("report_path", "")
        report_info: str = f"\nReport: {report_path}" if report_path else ""

        messagebox.showinfo(
            "Sending Complete",
            f"Total:    {total}\n"
            f"Success:  {success}\n"
            f"Failed:   {failed}\n"
            f"Skipped:  {skipped}"
            f"{report_info}",
        )

    def _handle_thread_error(self, error_msg: str) -> None:
        """Handle an unhandled exception from the sender thread.

        Args:
            error_msg: The stringified exception.
        """
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self.log_message(f"ERROR: {error_msg}", tag="error")
        messagebox.showerror("Sending Error", error_msg)

    def _update_summary(self) -> None:
        """Refresh the summary counter labels."""
        self._summary_vars["total"].set(str(self._total))
        self._summary_vars["success"].set(str(self._success))
        self._summary_vars["failed"].set(str(self._failed))
        self._summary_vars["skipped"].set(str(self._skipped))

    def _clear_log(self) -> None:
        """Remove all text from the log widget."""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _view_history(self) -> None:
        """Open a dialog listing recent CSV reports."""
        reports_dir: Path = PROJECT_ROOT / "reports"
        if not reports_dir.exists():
            messagebox.showinfo("No History", "No reports have been generated yet.")
            return

        csv_files: list[Path] = sorted(reports_dir.glob("*.csv"), reverse=True)
        if not csv_files:
            messagebox.showinfo("No History", "No CSV report files found in the reports folder.")
            return

        # Build a simple list dialog
        dialog = tk.Toplevel(self)
        dialog.title("Report History")
        dialog.configure(bg=CARD_BG)
        dialog.geometry("520x370")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(
            dialog, text="Recent Reports", font=("Segoe UI", 14, "bold"), background=CARD_BG, foreground=TEXT
        ).pack(padx=14, pady=(14, 6), anchor=tk.W)

        listbox_frame = tk.Frame(dialog, bg=CARD_BG)
        listbox_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        scrollbar = tk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(
            listbox_frame,
            bg="#0d1b2a",
            fg=TEXT,
            font=("Consolas", 10),
            selectbackground=ACCENT,
            highlightthickness=0,
            borderwidth=0,
            yscrollcommand=scrollbar.set,
        )
        listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        for csv_file in csv_files[:50]:
            listbox.insert(tk.END, csv_file.name)

        def _open_selected() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            selected_file: Path = reports_dir / listbox.get(selection[0])
            system: str = platform.system()
            try:
                if system == "Windows":
                    os.startfile(str(selected_file))  # type: ignore[attr-defined]
                elif system == "Darwin":
                    subprocess.Popen(["open", str(selected_file)])
                else:
                    subprocess.Popen(["xdg-open", str(selected_file)])
            except Exception as exc:
                messagebox.showerror("Error", f"Could not open file:\n{exc}")

        btn_frame = tk.Frame(dialog, bg=CARD_BG)
        btn_frame.pack(fill=tk.X, padx=14, pady=(0, 14))
        ttk.Button(btn_frame, text="Open Selected", style="Secondary.TButton", command=_open_selected).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(btn_frame, text="Close", style="Secondary.TButton", command=dialog.destroy).pack(side=tk.LEFT)


# ---------------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    app = PayrollApp()
    app.mainloop()
