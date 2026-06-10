"""Secret management utilities for the Payroll WhatsApp Automation System.

Provides secure handling of sensitive configuration values including:
- Configuration directory resolution using the app/data directory model
- Automatic .env file provisioning and legacy migration
- Secret masking for safe logging
- Environment variable validation

All methods are static and never log actual secret values.
"""

import os
import shutil
from pathlib import Path

from logger_config import get_app_dir, get_data_dir, setup_logger

logger = setup_logger(__name__)

# Required environment variables for the system to function
_REQUIRED_ENV_KEYS: list[str] = ["ACCESS_TOKEN", "PHONE_NUMBER_ID"]


class SecretManager:
    """Centralised secret and configuration management.

    This class provides static utility methods for:

    * Locating the user-writable configuration directory
    * Ensuring a ``.env`` file exists (copying from the bundled example if needed)
    * Migrating legacy ``.env`` files from the old project-root location
    * Masking sensitive values so they can be logged safely
    * Validating that all required environment variables are present

    **Path model**

    The system distinguishes between two directories:

    * **App dir** (`get_app_dir()`): Read-only assets shipped with the
      application (templates, ``.env.example``).
    * **Data dir** (`get_data_dir()`): User-writable location for ``.env``,
      database files, logs, and reports.

    In development mode both resolve to the project root for backward
    compatibility.  In a frozen (PyInstaller) build the data dir is a
    platform-specific user directory.
    """

    # --------------------------------------------------------------------- #
    #  Directory / path helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def get_config_dir() -> Path:
        """Return the user-writable data directory.

        Delegates to :func:`logger_config.get_data_dir`.

        Returns:
            Path to the data directory (e.g. ``~/.config/PayrollWhatsApp/``
            on Linux when frozen, or the project root in development).
        """
        return get_data_dir()

    @staticmethod
    def get_env_path() -> Path:
        """Return the path to the ``.env`` file inside the data directory.

        Returns:
            Absolute path to ``<data_dir>/.env``.
        """
        return SecretManager.get_config_dir() / ".env"

    # --------------------------------------------------------------------- #
    #  .env provisioning & migration
    # --------------------------------------------------------------------- #

    @staticmethod
    def ensure_env_exists() -> None:
        """Ensure a ``.env`` file exists in the data directory.

        If ``.env`` is missing from the data directory the method first
        attempts a legacy migration (see :meth:`migrate_legacy_env`).
        If that does not produce a file either, the bundled
        ``.env.example`` from the app directory is copied as a starting
        point.

        The data directory is created (with parents) if it does not
        already exist.
        """
        data_dir = SecretManager.get_config_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        env_path = data_dir / ".env"

        if env_path.is_file():
            logger.debug(".env already present at %s", env_path)
            return

        # Attempt legacy migration first
        SecretManager.migrate_legacy_env()

        if env_path.is_file():
            # Migration succeeded — nothing more to do
            return

        # Fall back to copying the bundled example
        example_path = get_app_dir() / ".env.example"
        if example_path.is_file():
            shutil.copy2(str(example_path), str(env_path))
            logger.info(
                "Created .env from .env.example at %s", env_path
            )
        else:
            logger.warning(
                ".env.example not found in app directory (%s); "
                "cannot auto-create .env",
                get_app_dir(),
            )

    @staticmethod
    def migrate_legacy_env() -> None:
        """Migrate a legacy ``.env`` from the app/project-root directory.

        If ``.env`` exists in the app directory (old location) but **not**
        in the data directory (new location), the file is copied to the
        data directory and a warning is logged instructing the user to
        update their workflow.

        This provides seamless backward compatibility when upgrading
        from the single-directory layout.
        """
        data_dir = SecretManager.get_config_dir()
        new_env = data_dir / ".env"

        if new_env.is_file():
            # Already migrated or user placed it manually
            return

        legacy_env = get_app_dir() / ".env"
        if not legacy_env.is_file():
            return

        # Avoid copying onto itself when app_dir == data_dir (dev mode)
        if legacy_env.resolve() == new_env.resolve():
            return

        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(legacy_env), str(new_env))
        logger.warning(
            "Migrated legacy .env from %s to %s. "
            "Please update your configuration workflow to use the new "
            "data directory.",
            legacy_env,
            new_env,
        )

    # --------------------------------------------------------------------- #
    #  Masking helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def mask_token(token: str) -> str:
        """Mask an API token for safe logging.

        Shows the first 4 and last 4 characters with ``'...'`` in
        between.  If the token is 10 characters or shorter the entire
        value is replaced with ``'***'``.

        Args:
            token: The raw token string.

        Returns:
            A masked representation of the token.
        """
        if not token or len(token) <= 10:
            return "***"
        return f"{token[:4]}...{token[-4:]}"

    @staticmethod
    def mask_phone(phone: str) -> str:
        """Mask a phone number for safe logging.

        Replaces all but the last 4 digits with ``'****'``.

        Args:
            phone: The raw phone number string.

        Returns:
            A masked phone number (e.g. ``'****3210'``).
        """
        if not phone or len(phone) < 4:
            return "***"
        return f"****{phone[-4:]}"

    @staticmethod
    def mask_sensitive(value: str, visible_chars: int = 4) -> str:
        """Generically mask a sensitive string.

        Shows the first *visible_chars* characters followed by ``'***'``.
        If the value is shorter than or equal to *visible_chars* the
        entire value is replaced with ``'***'``.

        Args:
            value: The sensitive string to mask.
            visible_chars: Number of leading characters to keep visible.

        Returns:
            A masked version of *value*.
        """
        if not value or len(value) <= visible_chars:
            return "***"
        return f"{value[:visible_chars]}***"

    # --------------------------------------------------------------------- #
    #  Environment validation
    # --------------------------------------------------------------------- #

    @staticmethod
    def validate_required_env() -> tuple[bool, list[str]]:
        """Check that all required environment variables are present.

        The following variables are verified:

        * ``ACCESS_TOKEN``
        * ``PHONE_NUMBER_ID``

        Returns:
            A tuple of ``(all_present, missing_keys)`` where
            *all_present* is ``True`` when every required key has a
            non-empty value and *missing_keys* lists any that are
            absent or empty.
        """
        missing: list[str] = []
        for key in _REQUIRED_ENV_KEYS:
            val = os.environ.get(key, "").strip()
            if not val:
                missing.append(key)
                logger.debug("Required env var %s is missing or empty", key)

        all_present = len(missing) == 0
        if all_present:
            logger.debug("All required environment variables are present")
        else:
            logger.warning(
                "Missing required environment variables: %s",
                ", ".join(missing),
            )

        return all_present, missing
