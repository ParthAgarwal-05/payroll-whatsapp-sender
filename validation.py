"""Validation utilities for template mappings in the Payroll WhatsApp System.

Provides functions to validate the structure, format, and data
compatibility of template parameter mappings before they are used to
send WhatsApp messages.

Validation rules
-----------------
* **Keys** must be valid identifier-like strings matching
  ``^[a-zA-Z_][a-zA-Z0-9_]{0,63}$``.
* **Values** (column name references) must be non-empty, at most 128
  characters, and free of control characters.
* Mappings can be cross-checked against a sample data row to detect
  missing columns early.
"""

import re
from typing import Optional

# -------------------------------------------------------------------- #
#  Compiled patterns
# -------------------------------------------------------------------- #

_KEY_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_CONTROL_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f]")

_MAX_VALUE_LENGTH: int = 128


# -------------------------------------------------------------------- #
#  Key / value validators
# -------------------------------------------------------------------- #


def validate_mapping_key(key: str) -> tuple[bool, str]:
    """Validate a single mapping key.

    A valid key must:

    * Start with a letter or underscore.
    * Contain only ASCII letters, digits, or underscores.
    * Be between 1 and 64 characters long.

    Args:
        key: The mapping key to validate.

    Returns:
        A tuple ``(is_valid, error_message)``.  *error_message* is
        empty when the key is valid.
    """
    if not key:
        return False, "Mapping key must not be empty"

    if not _KEY_PATTERN.match(key):
        return (
            False,
            f"Mapping key '{key}' is invalid. Keys must start with a letter "
            f"or underscore, contain only alphanumeric characters or "
            f"underscores, and be at most 64 characters long.",
        )

    return True, ""


def validate_mapping_value(value: str) -> tuple[bool, str]:
    """Validate a single mapping value (column name reference).

    A valid value must:

    * Be non-empty.
    * Be at most 128 characters long.
    * Contain no ASCII control characters.

    Args:
        value: The mapping value to validate.

    Returns:
        A tuple ``(is_valid, error_message)``.
    """
    if not value or not value.strip():
        return False, "Mapping value must not be empty"

    if len(value) > _MAX_VALUE_LENGTH:
        return (
            False,
            f"Mapping value is too long ({len(value)} chars). "
            f"Maximum allowed length is {_MAX_VALUE_LENGTH} characters.",
        )

    if _CONTROL_CHAR_PATTERN.search(value):
        return False, "Mapping value must not contain control characters"

    return True, ""


# -------------------------------------------------------------------- #
#  Mapping-level validators
# -------------------------------------------------------------------- #


def validate_template_mapping(mapping: dict) -> tuple[bool, str]:
    """Validate an entire template parameter mapping.

    Checks that:

    * The mapping is not empty.
    * Every key passes :func:`validate_mapping_key`.
    * Every value passes :func:`validate_mapping_value`.

    Args:
        mapping: Dictionary mapping template parameter names to
            spreadsheet column names.

    Returns:
        A tuple ``(is_valid, error_message)``.  On the first failure
        the corresponding error message is returned immediately.
    """
    if not mapping:
        return False, "Template mapping must not be empty"

    for key, value in mapping.items():
        key_valid, key_error = validate_mapping_key(str(key))
        if not key_valid:
            return False, key_error

        value_valid, value_error = validate_mapping_value(str(value))
        if not value_valid:
            return False, f"Invalid value for key '{key}': {value_error}"

    return True, ""


def extract_template_parameters(
    mapping: dict,
    row_data: dict,
) -> tuple[list[dict[str, str]], list[str]]:
    """Extract template parameters from row data, using a case-insensitive mapping.
    
    Returns:
        A tuple ``(parameters, missing_columns)``.
    """
    parameters: list[dict[str, str]] = []
    missing: list[str] = []

    # One normalization path
    data_columns_lower: dict[str, any] = {
        str(k).lower(): v for k, v in row_data.items()
    }

    for param_key, column_name in mapping.items():
        col_lower = str(column_name).lower()
        if col_lower not in data_columns_lower:
            missing.append(str(column_name))
            continue
            
        value = data_columns_lower[col_lower]
        # No empty payroll fields
        if value is None or str(value).strip() == "":
            missing.append(str(column_name))
            continue
            
        parameters.append({
            "type": "text",
            "parameter_name": str(param_key),
            "text": str(value).strip()
        })

    return parameters, missing


def validate_mapping_against_data(
    mapping: dict,
    sample_row: dict,
) -> tuple[bool, list[str]]:
    """Check that every mapped column exists in the data and is not empty.

    Performs a **case-insensitive** comparison between the mapping
    values (expected column names) and the keys present in
    *sample_row*.

    Args:
        mapping: Template parameter mapping (key → column name).
        sample_row: A representative row from the data source,
            typically ``dict`` with column names as keys.

    Returns:
        A tuple ``(all_present, missing_columns)`` where
        *all_present* is ``True`` when every mapped column is found
        and *missing_columns* lists any that are absent.
    """
    _, missing = extract_template_parameters(mapping, sample_row)
    return len(missing) == 0, missing


def validate_parameter_count(
    mapping: dict,
    expected_count: Optional[int] = None,
) -> tuple[bool, str]:
    """Validate that the mapping has the expected number of parameters.

    If *expected_count* is ``None`` (template metadata unavailable)
    the check is skipped and the mapping is considered valid.

    Args:
        mapping: Template parameter mapping.
        expected_count: The number of parameters the WhatsApp template
            expects, or ``None`` if unknown.

    Returns:
        A tuple ``(is_valid, error_message)``.
    """
    if expected_count is None:
        return True, ""

    actual = len(mapping)
    if actual != expected_count:
        return (
            False,
            f"Template expects {expected_count} parameter(s) but mapping "
            f"contains {actual}.",
        )

    return True, ""
