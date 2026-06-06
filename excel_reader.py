"""
excel_reader.py — Read and validate payroll data from Excel files.

This module provides the ``PayrollExcelReader`` class which handles
reading ``.xlsx`` / ``.xls`` payroll spreadsheets via *pandas* and
*openpyxl*, validating required columns and individual rows, normalising
phone numbers for the WhatsApp API, and splitting records into valid /
invalid buckets.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from logger_config import setup_logger


class PayrollExcelReader:
    """Read, validate, and normalise payroll data from an Excel workbook.

    Typical workflow::

        reader = PayrollExcelReader("payroll.xlsx")
        ok, msg = reader.validate_file()
        if ok:
            valid, invalid = reader.get_valid_records()
    """

    REQUIRED_COLUMNS: set[str] = {"phone", "employee_name", "month_year"}
    """Columns that **must** be present (checked case-insensitively)."""

    def __init__(self, file_path: str) -> None:
        """Initialise the reader with the path to an Excel file.

        Args:
            file_path: Absolute or relative path to the ``.xlsx`` / ``.xls``
                payroll workbook.
        """
        self.file_path: Path = Path(file_path)
        self.logger: logging.Logger = setup_logger(__name__)
        self._cached_df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # File-level validation
    # ------------------------------------------------------------------

    def validate_file(self) -> tuple[bool, str]:
        """Check that the Excel file exists, has a valid extension, can be
        opened, and contains all required columns.

        Returns:
            A ``(is_valid, message)`` tuple.  ``message`` is ``'Valid'`` on
            success, or a human-readable error description on failure.
        """
        # 1. Existence
        if not self.file_path.exists():
            msg = f"File not found: {self.file_path}"
            self.logger.error(msg)
            return False, msg

        # 2. Extension
        if self.file_path.suffix.lower() not in {".xlsx", ".xls"}:
            msg = (
                f"Invalid file extension '{self.file_path.suffix}'. "
                "Expected .xlsx or .xls"
            )
            self.logger.error(msg)
            return False, msg

        # 3. Readability
        try:
            if self._cached_df is not None:
                df = self._cached_df
            else:
                df = pd.read_excel(self.file_path, nrows=0)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unable to open Excel file: {exc}"
            self.logger.error(msg)
            return False, msg

        # 4. Required columns (case-insensitive)
        file_columns: set[str] = {col.strip().lower() for col in df.columns}
        missing: set[str] = self.REQUIRED_COLUMNS - file_columns
        if missing:
            msg = f"Missing required columns: {', '.join(sorted(missing))}"
            self.logger.error(msg)
            return False, msg

        self.logger.info("File validation passed for %s", self.file_path)
        return True, "Valid"

    # ------------------------------------------------------------------
    # Data reading
    # ------------------------------------------------------------------

    def read_data(self) -> list[dict[str, Any]]:
        """Read the entire Excel file and return a list of row dictionaries.

        Processing steps:
        1. Return cached data if available.
        2. Strip whitespace from column names and lower-case them.
        3. Drop rows that are completely empty.
        4. Convert every cell value to a stripped string (NaN → ``""``).
           Whole-number floats are rendered without trailing ``.0``.

        Returns:
            A list of ``dict`` objects, one per non-empty row.
        """
        if self._cached_df is not None:
            records = self._cached_df.to_dict(orient='records')
            self.logger.debug('Returning %d cached row(s)', len(records))
            return records

        df = pd.read_excel(self.file_path)

        # Normalise column names
        df.columns = [str(col).strip().lower() for col in df.columns]

        # Drop fully-empty rows
        df.dropna(how="all", inplace=True)

        # Replace NaN → "" and convert to string intelligently
        df = df.fillna('')

        def smart_str(val):
            """Convert value to string without trailing .0 for whole numbers."""
            if isinstance(val, float):
                if val == '' or pd.isna(val):
                    return ''
                if val == int(val):
                    return str(int(val))
                return str(val)
            return str(val).strip()

        df = df.apply(lambda col: col.map(smart_str))

        self._cached_df = df  # Cache the processed DataFrame
        records: list[dict[str, Any]] = df.to_dict(orient="records")
        self.logger.info("Read %d row(s) from %s", len(records), self.file_path)
        return records

    # ------------------------------------------------------------------
    # Row-level validation
    # ------------------------------------------------------------------

    def validate_row(self, row: dict[str, Any], row_index: int) -> tuple[bool, str]:
        """Validate a single payroll row.

        Checks performed:
        * ``phone`` is present and non-empty.
        * ``phone`` contains only digits (after stripping ``+``, spaces, and
          hyphens).
        * ``employee_name`` is present and non-empty.
        * ``month_year`` is present and non-empty.

        Args:
            row: A dictionary representing one spreadsheet row.
            row_index: The 1-based row number (used for logging context).

        Returns:
            A ``(is_valid, message)`` tuple.
        """
        # --- phone ---
        phone: str = str(row.get("phone", "")).strip()
        if not phone:
            return False, f"Row {row_index}: 'phone' is missing or empty"

        cleaned_phone = re.sub(r"[\+\s\-]", "", phone)
        if not cleaned_phone.isdigit():
            return (
                False,
                f"Row {row_index}: 'phone' contains non-digit characters: '{phone}'",
            )

        # --- employee_name ---
        employee_name: str = str(row.get("employee_name", "")).strip()
        if not employee_name:
            return False, f"Row {row_index}: 'employee_name' is missing or empty"

        # --- month_year ---
        month_year: str = str(row.get("month_year", "")).strip()
        if not month_year:
            return False, f"Row {row_index}: 'month_year' is missing or empty"

        return True, "Valid"

    # ------------------------------------------------------------------
    # Bulk validation
    # ------------------------------------------------------------------

    def get_valid_records(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read all data and split it into valid and invalid record lists.

        Invalid records are augmented with ``'error'`` and ``'row_number'``
        keys so the caller can report problems back to the user.

        Returns:
            A ``(valid_records, invalid_records)`` tuple.
        """
        records = self.read_data()

        valid_records: list[dict[str, Any]] = []
        invalid_records: list[dict[str, Any]] = []

        for idx, row in enumerate(records, start=2):
            # start=2 because row 1 in Excel is the header
            is_valid, message = self.validate_row(row, row_index=idx)

            if is_valid:
                valid_records.append(row)
            else:
                self.logger.warning("Invalid row %d: %s", idx, message)
                invalid_row = {**row, "error": message, "row_number": idx}
                invalid_records.append(invalid_row)

        self.logger.info(
            "Validation complete — valid: %d, invalid: %d",
            len(valid_records),
            len(invalid_records),
        )
        return valid_records, invalid_records

    # ------------------------------------------------------------------
    # Phone normalisation
    # ------------------------------------------------------------------

    def normalize_phone(self, phone: str, default_region: str | None = None) -> str:
        """Normalise a phone number using the phonenumbers library.

        Args:
            phone: Raw phone string from the spreadsheet.
            default_region: ISO 3166-1 alpha-2 region code. Defaults to
                the DEFAULT_REGION environment variable, or 'IN'.

        Returns:
            A digits-only phone string ready for the WhatsApp API.

        Raises:
            ValueError: If the phone number is invalid and cannot be normalised.
        """
        import os
        from phone_utils import normalize_phone as _normalize

        region = default_region or os.getenv('DEFAULT_REGION', 'IN')
        normalized, is_valid, error = _normalize(phone, default_region=region)

        if not is_valid:
            self.logger.warning(
                'Phone number may be invalid (region=%s): %s',
                region, error,
            )

        return normalized

    # ------------------------------------------------------------------
    # Column normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_column_name(name: str) -> str:
        """Normalize a column name for case-insensitive matching."""
        return str(name).strip().lower()
