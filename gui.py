"""
Payroll WhatsApp Sender — Tkinter GUI Application.

Provides a modern dark-themed interface for sending wage slips
via WhatsApp. All network operations run in a background thread
so the GUI stays responsive.

The GUI now acts as the configuration editor — all API settings
are editable in the UI and persisted back to the ``.env`` file.
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

from config_manager import read_env, update_env, validate_settings, reload_env
from logger_config import setup_logger, get_project_root
from send_payslips import PayslipSender

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = get_project_root()

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
SAVE_GREEN = "#27ae60"


def generate_month_options() -> list[str]:
    """Generate a list of month options in ``MMM-YYYY`` format.

    Produces 25 entries: the previous 12 months, the current month,
    and the next 12 months — all in chronological order.

    Uses only the Python standard library (no external dependencies).

    Returns:
        A list of strings like ``['Jun-2025', 'Jul-2025', ..., 'Jun-2027']``.
    """
    import calendar

    today = datetime.now()
    current_month: int = today.month
    current_year: int = today.year

    options: list[str] = []
    for offset in range(-12, 13):
        # Compute target month/year with wraparound
        total_months = (current_year * 12 + current_month - 1) + offset
        year = total_months // 12
        month = (total_months % 12) + 1
        abbr = calendar.month_abbr[month]
        options.append(f"{abbr}-{year}")
    return options


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
        self.minsize(750, 920)
        self.configure(bg=BG)
        self.resizable(True, True)

        # State
        self._sender: Optional[PayslipSender] = None
        self._send_thread: Optional[threading.Thread] = None
        self._total: int = 0
        self._success: int = 0
        self._failed: int = 0
        self._skipped: int = 0
        self._record_count: int = 0

        # Build UI
        self._configure_styles()
        self._build_header()
        self._build_api_settings()
        self._build_send_settings()
        self._build_actions()
        self._build_progress()
        self._build_log()
        self._build_summary()
        self._build_footer()

        # Keyboard shortcuts & context menus
        self._bind_shortcuts()

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
            "Save.TButton",
            background=SAVE_GREEN,
            foreground=TEXT,
            font=("Segoe UI", 11, "bold"),
            padding=(18, 8),
        )
        style.map(
            "Save.TButton",
            background=[("active", "#219a52"), ("disabled", "#555555")],
            foreground=[("disabled", "#999999")],
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

        # Combobox (for Month/Year dropdown)
        style.configure(
            "TCombobox",
            fieldbackground=ACCENT,
            foreground=TEXT,
            selectbackground=ACCENT,
            selectforeground=TEXT,
            arrowcolor=TEXT,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ACCENT)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", ACCENT)],
            selectforeground=[("readonly", TEXT)],
        )
        # Style the dropdown listbox via option_add (Tk limitation)
        self.option_add("*TCombobox*Listbox.background", CARD_BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT)
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        # Progressbar
        style.configure(
            "green.Horizontal.TProgressbar",
            troughcolor=ACCENT,
            background=SUCCESS,
            thickness=22,
        )

    # ------------------------------------------------------------------ #
    # Keyboard shortcuts & context menus
    # ------------------------------------------------------------------ #
    def _bind_shortcuts(self) -> None:
        """Bind standard text-editing shortcuts to all Entry widgets.

        Tk's default binding for Ctrl+A in Entry widgets is inherited from
        Emacs — it moves the cursor to the start of the line (like Home).
        This method overrides that binding to perform Select All instead.

        Ctrl+C/V/X are already handled by Tk's built-in clipboard bindings
        on all platforms, but we rebind them explicitly to guarantee
        consistent behaviour on all Linux desktop environments.

        Ctrl+Z (undo) and Ctrl+Y (redo) are not natively supported by
        Tk Entry widgets, so they are not bound here.
        """
        # Bind Ctrl+A → Select All on ALL Entry widgets (ttk.Entry and tk.Entry)
        self.bind_class("TEntry", "<Control-a>", self._on_select_all)
        self.bind_class("TEntry", "<Control-A>", self._on_select_all)
        self.bind_class("Entry", "<Control-a>", self._on_select_all)
        self.bind_class("Entry", "<Control-A>", self._on_select_all)

        # Ensure Ctrl+C/V/X work explicitly (some Linux DEs intercept these)
        for widget_class in ("TEntry", "Entry"):
            self.bind_class(widget_class, "<Control-c>", self._on_copy)
            self.bind_class(widget_class, "<Control-C>", self._on_copy)
            self.bind_class(widget_class, "<Control-v>", self._on_paste)
            self.bind_class(widget_class, "<Control-V>", self._on_paste)
            self.bind_class(widget_class, "<Control-x>", self._on_cut)
            self.bind_class(widget_class, "<Control-X>", self._on_cut)

        # Right-click context menu on all Entry widgets
        self.bind_class("TEntry", "<Button-3>", self._show_context_menu)
        self.bind_class("Entry", "<Button-3>", self._show_context_menu)

        # Also bind on the Text widget (Activity Log) for copy support
        self.bind_class("Text", "<Control-a>", self._on_text_select_all)
        self.bind_class("Text", "<Control-A>", self._on_text_select_all)
        self.bind_class("Text", "<Button-3>", self._show_text_context_menu)

    @staticmethod
    def _on_select_all(event: tk.Event) -> str:
        """Handle Ctrl+A — select all text in an Entry widget."""
        widget = event.widget
        widget.select_range(0, tk.END)
        widget.icursor(tk.END)
        return "break"  # Prevent Tk's default Emacs-style Ctrl+A binding

    @staticmethod
    def _on_copy(event: tk.Event) -> str:
        """Handle Ctrl+C — copy selected text to clipboard."""
        widget = event.widget
        try:
            if widget.selection_present():
                widget.event_generate("<<Copy>>")
        except (tk.TclError, AttributeError):
            pass
        return "break"

    @staticmethod
    def _on_paste(event: tk.Event) -> str:
        """Handle Ctrl+V — paste text from clipboard."""
        widget = event.widget
        try:
            # Delete selected text first (if any), then insert clipboard
            if widget.selection_present():
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            clipboard = widget.clipboard_get()
            widget.insert(tk.INSERT, clipboard)
        except (tk.TclError, AttributeError):
            pass
        return "break"

    @staticmethod
    def _on_cut(event: tk.Event) -> str:
        """Handle Ctrl+X — cut selected text to clipboard."""
        widget = event.widget
        try:
            if widget.selection_present():
                widget.event_generate("<<Cut>>")
        except (tk.TclError, AttributeError):
            pass
        return "break"

    @staticmethod
    def _on_text_select_all(event: tk.Event) -> str:
        """Handle Ctrl+A — select all text in a Text widget."""
        widget = event.widget
        widget.tag_add(tk.SEL, "1.0", tk.END)
        widget.mark_set(tk.INSERT, tk.END)
        return "break"

    def _show_context_menu(self, event: tk.Event) -> None:
        """Show a right-click context menu for Entry widgets."""
        widget = event.widget
        menu = tk.Menu(self, tearoff=0, bg=CARD_BG, fg=TEXT,
                       activebackground=ACCENT, activeforeground=TEXT,
                       font=("Segoe UI", 10))

        has_selection = False
        try:
            has_selection = widget.selection_present()
        except (tk.TclError, AttributeError):
            pass

        has_clipboard = False
        try:
            widget.clipboard_get()
            has_clipboard = True
        except tk.TclError:
            pass

        is_readonly = False
        try:
            state = str(widget.cget("state"))
            is_readonly = state in ("readonly", "disabled")
        except tk.TclError:
            pass

        menu.add_command(
            label="Cut",
            accelerator="Ctrl+X",
            command=lambda: widget.event_generate("<<Cut>>"),
            state=tk.NORMAL if (has_selection and not is_readonly) else tk.DISABLED,
        )
        menu.add_command(
            label="Copy",
            accelerator="Ctrl+C",
            command=lambda: widget.event_generate("<<Copy>>"),
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_command(
            label="Paste",
            accelerator="Ctrl+V",
            command=lambda: self._context_paste(widget),
            state=tk.NORMAL if (has_clipboard and not is_readonly) else tk.DISABLED,
        )
        menu.add_separator()
        menu.add_command(
            label="Select All",
            accelerator="Ctrl+A",
            command=lambda: (widget.select_range(0, tk.END), widget.icursor(tk.END)),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_text_context_menu(self, event: tk.Event) -> None:
        """Show a right-click context menu for the Text (log) widget."""
        widget = event.widget
        menu = tk.Menu(self, tearoff=0, bg=CARD_BG, fg=TEXT,
                       activebackground=ACCENT, activeforeground=TEXT,
                       font=("Segoe UI", 10))

        has_selection = False
        try:
            widget.index(tk.SEL_FIRST)
            has_selection = True
        except tk.TclError:
            pass

        menu.add_command(
            label="Copy",
            accelerator="Ctrl+C",
            command=lambda: widget.event_generate("<<Copy>>"),
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_separator()
        menu.add_command(
            label="Select All",
            accelerator="Ctrl+A",
            command=lambda: (widget.tag_add(tk.SEL, "1.0", tk.END), widget.mark_set(tk.INSERT, tk.END)),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _context_paste(widget: tk.Widget) -> None:
        """Paste clipboard text into a widget, replacing any selection."""
        try:
            if hasattr(widget, "selection_present") and widget.selection_present():
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            clipboard = widget.clipboard_get()
            widget.insert(tk.INSERT, clipboard)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    # UI builder helpers
    # ------------------------------------------------------------------ #
    def _build_header(self) -> None:
        """Build the header frame with title and subtitle."""
        frame = ttk.Frame(self, style="TFrame")
        frame.pack(fill=tk.X, padx=20, pady=(18, 4))

        ttk.Label(frame, text="Payroll WhatsApp Sender", style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text="Send wage slips via WhatsApp", style="Sub.TLabel").pack(anchor=tk.W, pady=(2, 0))

    def _build_api_settings(self) -> None:
        """Build the WhatsApp API Configuration panel.

        Contains editable fields for all API credentials and template
        settings.  Values are loaded from the ``.env`` file on startup.
        A "Save Settings" button persists changes back to ``.env``.
        """
        lf = ttk.LabelFrame(self, text="  WhatsApp API Configuration  ", style="TLabelframe")
        lf.pack(fill=tk.X, padx=20, pady=(10, 4))
        inner = ttk.Frame(lf, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=12, pady=10)

        # Read current values from .env
        env_data: dict[str, str] = read_env()

        # --- Row 0: Phone Number ID ---
        ttk.Label(inner, text="Phone Number ID:", style="Card.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8), pady=5
        )
        self._phone_id_var = tk.StringVar(value=env_data.get("PHONE_NUMBER_ID", ""))
        ttk.Entry(inner, textvariable=self._phone_id_var, width=52).grid(
            row=0, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=5
        )

        # --- Row 1: API Version ---
        ttk.Label(inner, text="API Version:", style="Card.TLabel").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=5
        )
        self._api_version_var = tk.StringVar(value=env_data.get("API_VERSION", "v25.0"))
        ttk.Entry(inner, textvariable=self._api_version_var, width=52).grid(
            row=1, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=5
        )

        # --- Row 2: Template Name ---
        ttk.Label(inner, text="Template Name:", style="Card.TLabel").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=5
        )
        self._template_var = tk.StringVar(value=env_data.get("TEMPLATE_NAME", ""))
        ttk.Entry(inner, textvariable=self._template_var, width=52).grid(
            row=2, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=5
        )

        # --- Row 3: Template Language ---
        ttk.Label(inner, text="Template Language:", style="Card.TLabel").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 8), pady=5
        )
        self._template_lang_var = tk.StringVar(value=env_data.get("TEMPLATE_LANGUAGE", "en"))
        ttk.Entry(inner, textvariable=self._template_lang_var, width=52).grid(
            row=3, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=5
        )

        # --- Row 4: Access Token (masked) ---
        ttk.Label(inner, text="Access Token:", style="Card.TLabel").grid(
            row=4, column=0, sticky=tk.W, padx=(0, 8), pady=5
        )
        self._access_token_var = tk.StringVar(value=env_data.get("ACCESS_TOKEN", ""))
        self._token_entry = tk.Entry(
            inner,
            textvariable=self._access_token_var,
            width=52,
            show="•",
            bg=ACCENT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
        )
        self._token_entry.grid(row=4, column=1, sticky=tk.EW, padx=4, pady=5)

        # Toggle visibility button
        self._token_visible = False
        self._toggle_btn = ttk.Button(
            inner, text="👁", style="Secondary.TButton", command=self._toggle_token_visibility, width=3
        )
        self._toggle_btn.grid(row=4, column=2, padx=(4, 0), pady=5)

        # --- Row 5: Save Settings button ---
        btn_frame = ttk.Frame(inner, style="Card.TFrame")
        btn_frame.grid(row=5, column=0, columnspan=3, pady=(10, 2))

        ttk.Button(
            btn_frame, text="💾  Save Settings", style="Save.TButton", command=self.save_settings
        ).pack(side=tk.LEFT, padx=(0, 10))

        # Status label for save feedback
        self._save_status_var = tk.StringVar(value="")
        self._save_status_label = ttk.Label(
            btn_frame, textvariable=self._save_status_var, style="Card.TLabel"
        )
        self._save_status_label.pack(side=tk.LEFT, padx=(8, 0))

        inner.columnconfigure(1, weight=1)

    def _build_send_settings(self) -> None:
        """Build the Send Settings panel with Excel file and Month/Year fields."""
        lf = ttk.LabelFrame(self, text="  Send Settings  ", style="TLabelframe")
        lf.pack(fill=tk.X, padx=20, pady=4)
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

        # Row 1 — Month / Year (read-only dropdown)
        ttk.Label(inner, text="Payroll Month/Year:", style="Card.TLabel").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=6
        )
        self._month_options: list[str] = generate_month_options()
        current_month: str = datetime.now().strftime("%b-%Y")
        self._month_var = tk.StringVar(value=current_month)
        self._month_combo = ttk.Combobox(
            inner,
            textvariable=self._month_var,
            values=self._month_options,
            state="readonly",
            width=46,
        )
        self._month_combo.grid(row=1, column=1, columnspan=2, sticky=tk.EW, padx=4, pady=6)

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
            height=10,
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
    # Settings actions
    # ------------------------------------------------------------------ #
    def _get_gui_settings(self) -> dict[str, str]:
        """Collect all API settings from the GUI fields.

        Returns:
            A dict mapping .env key names to their current GUI values.
        """
        return {
            "ACCESS_TOKEN": self._access_token_var.get().strip(),
            "PHONE_NUMBER_ID": self._phone_id_var.get().strip(),
            "TEMPLATE_NAME": self._template_var.get().strip(),
            "TEMPLATE_LANGUAGE": self._template_lang_var.get().strip(),
            "API_VERSION": self._api_version_var.get().strip(),
        }

    def save_settings(self) -> None:
        """Validate and persist the current GUI settings to ``.env``.

        After a successful save the environment is reloaded so that
        subsequent operations (including ``PayslipSender`` initialisation)
        pick up the new values automatically.
        """
        settings = self._get_gui_settings()

        # Validate
        is_valid, msg = validate_settings(settings)
        if not is_valid:
            messagebox.showerror("Validation Error", msg)
            return

        # Write to .env
        success, msg = update_env(settings)
        if not success:
            messagebox.showerror("Save Error", msg)
            self._save_status_var.set("❌ Save failed")
            return

        # Reload env vars into os.environ
        reload_env()

        # Visual feedback
        self._save_status_var.set("✅ Settings saved")
        self.log_message("Settings saved to .env successfully.", tag="success")
        self._logger.info("Settings saved to .env via GUI.")

        # Clear the status label after 4 seconds
        self.after(4000, lambda: self._save_status_var.set(""))

    def _toggle_token_visibility(self) -> None:
        """Toggle the Access Token field between masked and visible."""
        self._token_visible = not self._token_visible
        if self._token_visible:
            self._token_entry.configure(show="")
            self._toggle_btn.configure(text="🙈")
        else:
            self._token_entry.configure(show="•")
            self._toggle_btn.configure(text="👁")

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
        """Validate inputs, save settings, create a PayslipSender and start sending."""
        # --- Save current GUI settings to .env first ---
        settings = self._get_gui_settings()
        is_valid, msg = validate_settings(settings)
        if not is_valid:
            messagebox.showerror("Missing Configuration", msg)
            return

        # Persist settings before sending
        success, msg = update_env(settings)
        if not success:
            messagebox.showerror("Save Error", f"Could not save settings before sending:\n{msg}")
            return
        reload_env()

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
        if not month_year:
            messagebox.showerror("Missing Month/Year", "Please select a payroll month from the dropdown.")
            return
        if month_year not in self._month_options:
            messagebox.showerror(
                "Invalid Month/Year",
                f"'{month_year}' is not a valid option.\n\n"
                "Please select a month from the dropdown list.",
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

        self.log_message("Settings saved. Initialising sender…", tag="info")

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
