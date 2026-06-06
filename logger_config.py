"""Logging configuration module for the Payroll WhatsApp Automation System.

Provides a centralized logger setup with rotating file output and console
streaming, ensuring consistent log formatting across all modules.

Also defines the canonical path helpers (:func:`get_app_dir` and
:func:`get_data_dir`) used throughout the application to locate bundled
assets and user-writable data, respectively.
"""

import logging
import os
import platform
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------

def get_app_dir() -> Path:
    """Return the directory containing bundled application assets.

    In frozen (PyInstaller) mode, this is the temp extraction directory
    (sys._MEIPASS). In development, it's the directory containing this file.

    Use for: templates/, .env.example, and other read-only bundled files.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller extracts bundled data to a temp folder
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    """Return the directory for user-writable application data.

    In production (frozen .exe), data is stored in the platform-appropriate
    user data directory. In development, it defaults to the project root
    for backward compatibility.

    Use for: .env, database/, logs/, reports/

    The directory is created automatically if it does not exist.
    Override with the PAYROLL_DATA_DIR environment variable.
    """
    override = os.environ.get('PAYROLL_DATA_DIR')
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    if getattr(sys, 'frozen', False):
        if platform.system() == 'Windows':
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        else:
            base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        data_dir = base / 'PayrollWhatsApp'
    else:
        # Development: use project directory for backward compatibility
        data_dir = Path(__file__).resolve().parent

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_project_root() -> Path:
    """Return the project root directory.

    .. deprecated:: 2.0
        Use :func:`get_app_dir` for bundled assets or
        :func:`get_data_dir` for user-writable data.
    """
    return get_data_dir()


# ------------------------------------------------------------------
# Privacy / PII masking
# ------------------------------------------------------------------

def mask_pii(text: str) -> str:
    """Mask personally identifiable information in log text.

    Masks:
    - Phone numbers (sequences of 10+ digits)
    - Values that look like account numbers
    - Common PII patterns
    """
    # Mask phone-like sequences (10+ digits, optionally with + prefix)
    text = re.sub(r'\+?\d{10,}', lambda m: m.group()[:3] + '****' + m.group()[-3:], text)
    # Mask values after sensitive keywords (case insensitive)
    for keyword in ('bank_account', 'uan', 'account', 'net_wages', 'basic',
                    'gross_wages', 'da', 'allowances', 'pf', 'esi', 'salary', 'other_deductions'):
        # Standard JSON format
        text = re.sub(
            rf'("{keyword}"\s*:\s*")([^"]+)(")',
            rf'\1***MASKED***\3',
            text,
            flags=re.IGNORECASE,
        )
        # WhatsApp API template parameter format
        text = re.sub(
            rf'("parameter_name"\s*:\s*"{keyword}"\s*,\s*"text"\s*:\s*")([^"]+)(")',
            rf'\1***MASKED***\3',
            text,
            flags=re.IGNORECASE,
        )
    return text


class PrivacyFilter(logging.Filter):
    """Logging filter that masks PII in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii(record.msg)
        # Also mask args if they're strings
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: mask_pii(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    mask_pii(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True


# ------------------------------------------------------------------
# Logger setup
# ------------------------------------------------------------------

def setup_logger(name: str = 'PayrollWhatsApp') -> logging.Logger:
    """Create and configure a logger with file and console handlers.

    Sets up a logger that writes DEBUG-level messages to a rotating log file
    and INFO-level messages to the console. The log directory is created
    automatically if it does not exist.

    A :class:`PrivacyFilter` is attached to both handlers so that
    personally identifiable information is masked before it reaches
    any output sink.

    Args:
        name: The name of the logger instance. Defaults to ``'PayrollWhatsApp'``.

    Returns:
        A fully configured :class:`logging.Logger` instance.
    """
    data_dir: Path = get_data_dir()
    log_dir: Path = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file: Path = log_dir / "payroll_whatsapp.log"

    logger: logging.Logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers when the function is called multiple times
    if logger.handlers:
        return logger

    # Shared privacy filter
    privacy_filter = PrivacyFilter()

    # Formatter shared by both handlers
    formatter: logging.Formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — DEBUG level, 5 MB per file, 10 backups
    file_handler: RotatingFileHandler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(privacy_filter)

    # Console handler — INFO level
    console_handler: logging.StreamHandler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(privacy_filter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
