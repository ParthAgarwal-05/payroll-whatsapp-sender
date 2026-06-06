"""SQLite database module for the Payroll WhatsApp Automation System.

Provides persistent storage for message sending history, enabling
duplicate detection and audit trails for payroll slip delivery.
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from types import TracebackType

from logger_config import setup_logger


class MessageDatabase:
    """Manages SQLite storage for WhatsApp message history.

    Tracks every message attempt (success or failure) and provides
    duplicate-detection so the same payslip is never sent twice for
    a given phone + month + template combination.

    All public methods are thread-safe — a :class:`threading.Lock`
    serialises access to the underlying SQLite connection.

    Usage::

        with MessageDatabase() as db:
            if not db.is_already_sent("919999999999", "May-2026", "payslip"):
                db.record_message(
                    employee_name="Jane Doe",
                    phone="919999999999",
                    month_year="May-2026",
                    template_name="payslip",
                    message_id="wamid.abc123",
                    status="Success",
                )
    """

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            month_year TEXT NOT NULL,
            template_name TEXT NOT NULL,
            message_id TEXT,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            error_details TEXT
        )
    """

    _CREATE_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_phone_month_template
        ON message_history (phone, month_year, template_name)
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialise the database connection and ensure tables exist.

        Args:
            db_path: Optional explicit path to the SQLite database file.
                     When *None*, the database is created at
                     ``<data_dir>/database/history.db``.
        """
        if db_path is None:
            from logger_config import get_data_dir
            data_dir = get_data_dir()
            db_file = data_dir / "database" / "history.db"
        else:
            db_file = Path(db_path)

        # Ensure the parent directory exists.
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self._db_path: Path = db_file
        self._lock = threading.Lock()
        self._logger: logging.Logger = setup_logger(__name__)
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        # Enable WAL mode for concurrent read/write and set a busy
        # timeout so threads retry instead of raising immediately.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_schema()

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "MessageDatabase":
        """Return *self* so the instance can be used in a ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the database connection when leaving the context."""
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_already_sent(
        self,
        phone: str,
        month_year: str,
        template_name: str,
    ) -> bool:
        """Check whether a successful message already exists.

        Only rows whose ``status`` equals ``'Success'`` are considered.

        Args:
            phone: Recipient phone number (e.g. ``"919999999999"``).
            month_year: Target month-year string (e.g. ``"May-2026"``).
            template_name: Name of the WhatsApp template used.

        Returns:
            ``True`` if a matching success record is found, ``False``
            otherwise.
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT 1
                  FROM message_history
                 WHERE phone         = ?
                   AND month_year    = ?
                   AND template_name = ?
                   AND status        = 'Success'
                 LIMIT 1
                """,
                (phone, month_year, template_name),
            )
            return cursor.fetchone() is not None

    def record_message(
        self,
        employee_name: str,
        phone: str,
        month_year: str,
        template_name: str,
        message_id: str,
        status: str,
        error_details: str = "",
    ) -> None:
        """Insert a message-history record.

        Every attempt (success **and** failure) is recorded as a separate
        row to maintain a complete audit trail.

        Args:
            employee_name: Full name of the employee.
            phone: Recipient phone number.
            month_year: Target month-year string.
            template_name: WhatsApp template name.
            message_id: WhatsApp-assigned message ID (may be empty on
                failure).
            status: Outcome string, typically ``"Success"`` or
                ``"Failed"``.
            error_details: Human-readable error description (optional).
        """
        timestamp = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO message_history
                    (employee_name, phone, month_year, template_name,
                     message_id, status, timestamp, error_details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_name,
                    phone,
                    month_year,
                    template_name,
                    message_id,
                    status,
                    timestamp,
                    error_details,
                ),
            )
            self._conn.commit()

    def get_history(
        self,
        month_year: str | None = None,
    ) -> list[dict]:
        """Retrieve message-history records as a list of dictionaries.

        Args:
            month_year: If provided, only rows matching this value are
                returned.  When *None*, all rows are returned.

        Returns:
            A list of ``dict`` objects, one per row, keyed by column
            name.
        """
        with self._lock:
            if month_year is not None:
                cursor = self._conn.execute(
                    """
                    SELECT *
                      FROM message_history
                     WHERE month_year = ?
                     ORDER BY id DESC
                    """,
                    (month_year,),
                )
            else:
                cursor = self._conn.execute(
                    """
                    SELECT *
                      FROM message_history
                     ORDER BY id DESC
                    """
                )

            return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the underlying SQLite connection. Safe to call multiple times."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create the schema objects if they do not already exist."""
        self._conn.execute(self._CREATE_TABLE_SQL)
        self._conn.execute(self._CREATE_INDEX_SQL)
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """Migrate database schema from older versions.

        Drops the old UNIQUE index (if present) and replaces it with a
        non-unique index so that multiple audit-trail rows can exist for
        the same (phone, month_year, template_name) combination.
        """
        try:
            self._conn.execute("DROP INDEX IF EXISTS idx_phone_month_template")
            self._conn.execute(self._CREATE_INDEX_SQL)
            self._conn.commit()
        except Exception:
            # DROP INDEX IF EXISTS handles the "doesn't exist" case,
            # so any exception here indicates a real problem (locked
            # DB, corruption, disk full, etc.).  Log it.
            self._logger.warning(
                "Schema migration failed — the application will continue "
                "but queries may be slower.",
                exc_info=True,
            )
