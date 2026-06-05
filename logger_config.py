"""Logging configuration module for the Payroll WhatsApp Automation System.

Provides a centralized logger setup with rotating file output and console
streaming, ensuring consistent log formatting across all modules.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_project_root() -> Path:
    """Return the project root directory.
    
    Works for both standard Python execution and PyInstaller compiled executables.
    When frozen, the executable is run from a temp folder, so we use sys.executable
    to find the directory containing the actual .exe file.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent


def setup_logger(name: str = 'PayrollWhatsApp') -> logging.Logger:
    """Create and configure a logger with file and console handlers.

    Sets up a logger that writes DEBUG-level messages to a rotating log file
    and INFO-level messages to the console. The log directory is created
    automatically if it does not exist.

    Args:
        name: The name of the logger instance. Defaults to ``'PayrollWhatsApp'``.

    Returns:
        A fully configured :class:`logging.Logger` instance.
    """
    project_root: Path = get_project_root()
    log_dir: Path = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file: Path = log_dir / "payroll_whatsapp.log"

    logger: logging.Logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers when the function is called multiple times
    if logger.handlers:
        return logger

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

    # Console handler — INFO level
    console_handler: logging.StreamHandler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
