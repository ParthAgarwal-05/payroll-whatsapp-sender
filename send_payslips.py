"""Main orchestration module for the Payroll WhatsApp System.

Ties together Excel reading, WhatsApp messaging, database tracking,
and logging to send payslips to employees. Supports both CLI and GUI
usage via callbacks and threaded execution.
"""

import argparse
import csv
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from database import MessageDatabase
from excel_reader import PayrollExcelReader
from logger_config import setup_logger
from whatsapp_api import WhatsAppSender

# Type alias for the progress/completion callback signature.
ProgressCallback = Callable[[str, str, str], None]


class PayslipSender:
    """Orchestrates sending payslips via WhatsApp to employees.

    Reads employee data from an Excel file, sends WhatsApp messages
    using pre-approved templates, records results in a database,
    and produces a CSV report.

    Attributes:
        excel_path: Path to the payroll Excel file.
        template_name: WhatsApp template name to use for messages.
        month_year: Pay-period label (e.g. ``"June 2026"``).
        total: Total number of records processed.
        success: Number of messages sent successfully.
        failed: Number of messages that failed to send.
        skipped: Number of duplicate/already-sent records skipped.
        results: List of per-record result dictionaries.
    """

    def __init__(
        self,
        excel_path: str,
        template_name: str | None = None,
        month_year: str | None = None,
    ) -> None:
        """Initialise the PayslipSender.

        Args:
            excel_path: Absolute or relative path to the payroll Excel file.
            template_name: WhatsApp message-template name.  Falls back to
                the ``TEMPLATE_NAME`` environment variable if not provided.
            month_year: Pay-period label such as ``"May 2026"``.  If *None*,
                the value is derived from each row's data in the Excel file.
        """
        self.excel_path: str = excel_path
        self.logger = setup_logger(__name__)

        # Core collaborators
        self.whatsapp_sender: WhatsAppSender = WhatsAppSender()
        self.database: MessageDatabase = MessageDatabase()
        self.excel_reader: PayrollExcelReader = PayrollExcelReader(excel_path)

        # Resolve template name: explicit arg → env var fallback.
        self.template_name: str = (
            template_name
            if template_name
            else (os.getenv("TEMPLATE_NAME") or "")
        )

        if not self.template_name:
            raise ValueError(
                "Template name is required. Provide it explicitly or set "
                "the TEMPLATE_NAME environment variable."
            )

        # Load the parameter mapping for this template from the JSON file.
        self.mapping: dict = self.whatsapp_sender.load_template_mapping(
            self.template_name
        )

        # month_year may be overridden per-row if left as None.
        self.month_year: str | None = month_year

        # Counters
        self.total: int = 0
        self.success: int = 0
        self.failed: int = 0
        self.skipped: int = 0

        # Detailed per-record results for reporting.
        self.results: list[dict[str, Any]] = []

        # Threading / cancellation support.
        self._stop_event: threading.Event = threading.Event()
        self._progress_callback: Optional[ProgressCallback] = None
        self._completion_callback: Optional[Callable] = None

        self.logger.info(
            "PayslipSender initialised — excel=%s, template=%s, month=%s",
            self.excel_path,
            self.template_name,
            self.month_year,
        )

    # ------------------------------------------------------------------
    # Callback setters
    # ------------------------------------------------------------------

    def set_progress_callback(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a callback invoked after each record is processed.

        The callback receives ``(employee_name, phone, status)`` where
        *status* is one of ``"Success"``, ``"Failed"``, or
        ``"Already Sent"``.

        Args:
            callback: A callable with the signature
                ``(employee_name: str, phone: str, status: str) -> None``.
        """
        self._progress_callback = callback

    def set_completion_callback(self, callback: Callable) -> None:
        """Register a callback invoked once all records have been processed.

        The callback receives the summary dict with keys:
        ``total``, ``success``, ``failed``, ``skipped``, ``report_path``.

        Args:
            callback: A callable accepting a summary dict.
        """
        self._completion_callback = callback

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the sending loop to stop after the current record.

        Safe to call from any thread.
        """
        self._stop_event.set()
        self.logger.info("Stop signal received — will halt after current record.")

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _notify_progress(self, name: str, phone: str, status: str) -> None:
        """Invoke the progress callback if one is registered.

        Args:
            name: Employee name.
            phone: Phone number.
            status: Delivery status string.
        """
        if self._progress_callback is not None:
            try:
                self._progress_callback(name, phone, status)
            except Exception:
                self.logger.exception("Progress callback raised an exception.")

    def get_preview(self) -> dict[str, Any]:
        """Generate a preview of the send operation without sending.

        Returns:
            A dict with keys: ``total_records``, ``valid_count``,
            ``invalid_count``, ``template_name``, ``month_year``,
            ``sample_names`` (first 5 employee names),
            ``already_sent_count``, ``new_count``.

        Raises:
            ValueError: If the Excel file fails validation.
        """
        is_valid, msg = self.excel_reader.validate_file()
        if not is_valid:
            raise ValueError(f'Excel validation failed: {msg}')

        valid_records, invalid_records = self.excel_reader.get_valid_records()

        # Count how many are already sent
        already_sent = 0
        for record in valid_records:
            # Phone is already normalised by validate_row() in get_valid_records()
            phone = str(record.get('phone', ''))
            record_month_year = self.month_year or str(record.get('month_year', ''))
            if self.database.is_already_sent(phone, record_month_year, self.template_name):
                already_sent += 1

        sample_names = [str(r.get('employee_name', 'Unknown')) for r in valid_records[:5]]

        return {
            'total_records': len(valid_records) + len(invalid_records),
            'valid_count': len(valid_records),
            'invalid_count': len(invalid_records),
            'template_name': self.template_name,
            'month_year': self.month_year or '(from Excel data)',
            'sample_names': sample_names,
            'already_sent_count': already_sent,
            'new_count': len(valid_records) - already_sent,
        }

    def process_all(self) -> dict[str, Any]:
        """Process every valid record in the Excel file.

        For each record the method:
        1. Checks for a cancellation signal.
        2. Normalises the phone number.
        3. Determines the ``month_year`` label.
        4. Checks the database for duplicates (skips if already sent).
        5. Sends the WhatsApp message (with retries).
        6. Records the outcome in the database and internal counters.
        7. Fires the progress callback.

        After all records are processed a CSV report is generated and the
        completion callback is invoked.

        Returns:
            A summary dictionary with keys ``total``, ``success``,
            ``failed``, ``skipped``, and ``report_path``.
        """
        self.logger.info("Starting payslip distribution for %s", self.excel_path)

        # Reset state for idempotent re-runs.
        self._stop_event.clear()
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.results = []

        try:
            # ----------------------------------------------------------
            # Validate & read Excel
            # ----------------------------------------------------------
            is_valid, validation_msg = self.excel_reader.validate_file()
            if not is_valid:
                error_msg = f"Excel validation failed: {validation_msg}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            valid_records, invalid_records = self.excel_reader.get_valid_records()

            if invalid_records:
                self.logger.warning(
                    "%d invalid records found — these will be skipped.",
                    len(invalid_records),
                )

            # Validate template mapping against sample data
            if valid_records:
                is_mapping_valid, mapping_error = self.whatsapp_sender.validate_template_mapping_data(
                    self.mapping, valid_records[0]
                )
                if not is_mapping_valid:
                    error_msg = f'Template mapping validation failed: {mapping_error}'
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

            self.total = len(valid_records)
            self.logger.info("Processing %d valid records.", self.total)

            # ----------------------------------------------------------
            # Iterate over valid records
            # ----------------------------------------------------------
            for index, record in enumerate(valid_records, start=1):
                # Check for cancellation.
                if self._stop_event.is_set():
                    self.logger.info("Stop event detected at record %d/%d.", index, self.total)
                    break

                employee_name: str = str(record.get("employee_name", "Unknown"))
                raw_phone: str = str(record.get("phone", ""))
                # Phone is already normalised by validate_row() in
                # get_valid_records(), so use it directly.
                phone: str = raw_phone

                # Determine month/year for this record.
                record_month_year: str = (
                    self.month_year
                    if self.month_year
                    else str(record.get("month_year", datetime.now().strftime("%B %Y")))
                )

                self.logger.info(
                    "[%d/%d] Processing %s (%s) for %s",
                    index,
                    self.total,
                    employee_name,
                    phone,
                    record_month_year,
                )

                # Duplicate check.
                if self.database.is_already_sent(phone, record_month_year, self.template_name):
                    self.logger.info(
                        "Already sent to %s for %s — skipping.",
                        phone,
                        record_month_year,
                    )
                    self.skipped += 1
                    self._notify_progress(employee_name, phone, "Already Sent")
                    self.results.append(
                        {
                            "employee_name": employee_name,
                            "phone": phone,
                            "month_year": record_month_year,
                            "status": "Already Sent",
                            "message_id": "",
                            "error": "",
                        }
                    )
                    continue

                # Attempt to send with retry.
                result: dict = self.whatsapp_sender.send_with_retry(
                    phone=phone,
                    template_name=self.template_name,
                    row_data=record,
                    mapping=self.mapping,
                )

                message_id: str = result.get("message_id", "")
                error: str = result.get("error", "")

                if result.get("success"):
                    status = "Success"
                    self.success += 1
                    self.logger.info(
                        "Message sent to %s — message_id=%s", phone, message_id
                    )
                else:
                    status = "Failed"
                    self.failed += 1
                    self.logger.error(
                        "Failed to send to %s: %s", phone, error
                    )

                # Persist result in database.
                try:
                    self.database.record_message(
                        employee_name=employee_name,
                        phone=phone,
                        month_year=record_month_year,
                        template_name=self.template_name,
                        message_id=message_id,
                        status=status,
                        error_details=error,
                    )
                except Exception:
                    self.logger.exception(
                        "CRITICAL: Failed to record result in database for %s. "
                        "Message was sent but NOT recorded — duplicate risk on re-run.",
                        phone,
                    )
                    # Correct the counters: the send succeeded but the
                    # audit trail is broken, so report this as a failure
                    # to the operator so they can investigate.
                    if status == "Success":
                        self.success -= 1
                        self.failed += 1
                    status = "DB Error"
                    error = (
                        f"Message sent (id={message_id}) but database write "
                        f"failed. Check logs for details. Duplicate risk on re-run."
                    )

                self._notify_progress(employee_name, phone, status)

                self.results.append(
                    {
                        "employee_name": employee_name,
                        "phone": phone,
                        "month_year": record_month_year,
                        "status": status,
                        "message_id": message_id,
                        "error": error,
                    }
                )

            # ----------------------------------------------------------
            # Generate report & invoke completion callback
            # ----------------------------------------------------------
            report_path: str = self.generate_report()

            # Clean up old reports to prevent unbounded disk usage
            self.cleanup_old_reports()

            summary: dict[str, Any] = {
                "total": self.total,
                "success": self.success,
                "failed": self.failed,
                "skipped": self.skipped,
                "report_path": report_path,
            }

            self.logger.info(
                "Distribution complete — total=%d, success=%d, failed=%d, skipped=%d, report=%s",
                self.total,
                self.success,
                self.failed,
                self.skipped,
                report_path,
            )

            if self._completion_callback is not None:
                try:
                    self._completion_callback(summary)
                except Exception:
                    self.logger.exception("Completion callback raised an exception.")

            return summary
        finally:
            self.database.close()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_report(self) -> str:
        """Generate a CSV report of all processed records.

        The report is saved under a ``reports/`` directory relative to
        the user data directory.  The directory is created automatically
        if it does not already exist.

        Returns:
            Absolute path to the generated CSV report file.
        """
        from logger_config import get_data_dir
        reports_dir: Path = get_data_dir() / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_template: str = (self.template_name or "unknown").replace(" ", "_")
        filename: str = f"report_{safe_template}_{timestamp}.csv"
        report_path: Path = reports_dir / filename

        fieldnames: list[str] = [
            "employee_name",
            "phone",
            "month_year",
            "status",
            "message_id",
            "error",
        ]

        try:
            with open(report_path, mode="w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in self.results:
                    writer.writerow(
                        {field: row.get(field, "") for field in fieldnames}
                    )
            self.logger.info("CSV report written to %s", report_path)
        except OSError:
            self.logger.exception("Failed to write CSV report.")
            return ""

        return str(report_path)

    # ------------------------------------------------------------------
    # Report retention
    # ------------------------------------------------------------------

    def cleanup_old_reports(self, max_reports: int = 100) -> int:
        """Remove old report files, keeping the most recent ones.

        Args:
            max_reports: Maximum number of report files to retain.

        Returns:
            Number of files deleted.
        """
        from logger_config import get_data_dir
        reports_dir = get_data_dir() / 'reports'
        if not reports_dir.exists():
            return 0

        csv_files = sorted(
            reports_dir.glob('*.csv'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        deleted = 0
        for old_file in csv_files[max_reports:]:
            try:
                old_file.unlink()
                deleted += 1
            except OSError:
                self.logger.warning('Could not delete old report: %s', old_file)

        if deleted:
            self.logger.info('Cleaned up %d old report(s)', deleted)
        return deleted

    # ------------------------------------------------------------------
    # Threaded execution
    # ------------------------------------------------------------------

    def run_in_thread(self) -> threading.Thread:
        """Start :meth:`process_all` in a daemon thread.

        Returns:
            The :class:`threading.Thread` instance running the
            processing loop.  The thread is started before being
            returned.
        """
        thread = threading.Thread(target=self.process_all, daemon=True)
        thread.start()
        self.logger.info("Processing thread started (daemon=%s).", thread.daemon)
        return thread


# ----------------------------------------------------------------------
# CLI entry-point
# ----------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argument parser for CLI usage.

    Returns:
        Configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        description="Send payslips via WhatsApp to employees listed in an Excel file.",
    )
    parser.add_argument(
        "--excel",
        required=True,
        help="Path to the payroll Excel file.",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="WhatsApp template name. Defaults to TEMPLATE_NAME env var.",
    )
    parser.add_argument(
        "--month",
        default=None,
        help='Month/year label, e.g. "June 2026". Defaults to Excel data.',
    )
    return parser


def main() -> None:
    """CLI entry-point — parse arguments, run the sender, print the summary."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    sender = PayslipSender(
        excel_path=args.excel,
        template_name=args.template,
        month_year=args.month,
    )

    summary: dict[str, Any] = sender.process_all()

    print("\n" + "=" * 50)
    print("        Payslip Distribution Summary")
    print("=" * 50)
    print(f"  Total records : {summary['total']}")
    print(f"  Successful    : {summary['success']}")
    print(f"  Failed        : {summary['failed']}")
    print(f"  Skipped (dup) : {summary['skipped']}")
    print(f"  Report file   : {summary['report_path']}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
