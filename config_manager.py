"""Configuration manager for the Payroll WhatsApp System.

Provides safe read/write access to the ``.env`` file, preserving comments,
blank lines, and unrelated keys.  The ``.env`` file is treated as the
single source of truth for all API configuration.
"""

import os
from pathlib import Path
from typing import Optional

from logger_config import get_project_root, setup_logger

# Keys managed by the GUI settings panel.
MANAGED_KEYS: list[str] = [
    "ACCESS_TOKEN",
    "PHONE_NUMBER_ID",
    "TEMPLATE_NAME",
    "TEMPLATE_LANGUAGE",
    "API_VERSION",
]

_logger = setup_logger("config_manager")


def _env_path() -> Path:
    """Return the absolute path to the ``.env`` file."""
    return get_project_root() / ".env"


def read_env() -> dict[str, str]:
    """Read all key-value pairs from the ``.env`` file.

    Comment lines (starting with ``#``) and blank lines are ignored.
    Values are stripped of surrounding whitespace and optional quotes.

    Returns:
        A ``dict`` mapping environment-variable names to their values.
        Returns an empty dict if the file does not exist.
    """
    env_file = _env_path()
    result: dict[str, str] = {}

    if not env_file.is_file():
        _logger.warning(".env file not found at %s", env_file)
        return result

    try:
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                # Skip comments and blank lines.
                if not stripped or stripped.startswith("#"):
                    continue
                # Split on the first '=' only.
                if "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove optional surrounding quotes.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                result[key] = value
    except OSError as exc:
        _logger.error("Failed to read .env file: %s", exc)

    return result


def update_env(updates: dict[str, str]) -> tuple[bool, str]:
    """Update specific keys in the ``.env`` file, preserving everything else.

    Performs an **in-place** update: existing lines whose key matches an
    entry in *updates* are replaced with the new value.  Comments, blank
    lines, and keys not present in *updates* are kept verbatim.  If a key
    from *updates* does not already exist in the file, it is appended at
    the end.

    Args:
        updates: A ``dict`` mapping environment-variable names to their
            new values.

    Returns:
        A tuple ``(success, message)`` where *success* is ``True`` when
        the file was written successfully.
    """
    env_file = _env_path()

    # If the .env file doesn't exist yet, create it from scratch.
    if not env_file.is_file():
        try:
            lines = []
            for key, value in updates.items():
                lines.append(f"{key}={value}\n")
            with open(env_file, "w", encoding="utf-8", newline="\n") as fh:
                fh.writelines(lines)
            _logger.info("Created new .env file at %s", env_file)
            return True, "Settings saved successfully."
        except OSError as exc:
            _logger.error("Failed to create .env file: %s", exc)
            return False, f"Could not create .env file:\n{exc}"

    # Read existing content line-by-line.
    try:
        with open(env_file, "r", encoding="utf-8") as fh:
            original_lines = fh.readlines()
    except OSError as exc:
        _logger.error("Failed to read .env file for update: %s", exc)
        return False, f"Could not read .env file:\n{exc}"

    # Track which keys we've already updated (so we know what to append).
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in original_lines:
        stripped = line.strip()

        # Preserve comments and blank lines as-is.
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Check if this line sets a key we want to update.
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()

            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue

        # Unrelated line — keep it.
        new_lines.append(line)

    # Append any keys that weren't found in the existing file.
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"\n{key}={value}\n")

    # Write the updated content back.
    try:
        with open(env_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(new_lines)
        _logger.info(
            "Updated .env file — keys modified: %s",
            list(updates.keys()),
        )
        return True, "Settings saved successfully."
    except OSError as exc:
        _logger.error("Failed to write .env file: %s", exc)
        return False, f"Could not write .env file:\n{exc}"


def validate_settings(settings: dict[str, str]) -> tuple[bool, str]:
    """Validate that all required configuration fields are non-empty.

    Args:
        settings: A ``dict`` mapping config key names to their values.

    Returns:
        A tuple ``(is_valid, message)``.  If invalid, *message* lists
        the missing fields.
    """
    required: dict[str, str] = {
        "ACCESS_TOKEN": "Access Token",
        "PHONE_NUMBER_ID": "Phone Number ID",
        "TEMPLATE_NAME": "Template Name",
        "TEMPLATE_LANGUAGE": "Template Language",
        "API_VERSION": "API Version",
    }

    missing: list[str] = []
    for key, label in required.items():
        value = settings.get(key, "").strip()
        if not value:
            missing.append(label)

    if missing:
        return False, "The following fields are required:\n• " + "\n• ".join(missing)

    return True, "Valid"


def reload_env() -> None:
    """Reload the ``.env`` file into ``os.environ``.

    Reads the current ``.env`` file and updates ``os.environ`` with
    the latest values.  This ensures that modules which read from
    ``os.getenv()`` pick up changes saved by the GUI.
    """
    env_data = read_env()
    for key, value in env_data.items():
        os.environ[key] = value
    _logger.info("Reloaded %d environment variables from .env", len(env_data))
