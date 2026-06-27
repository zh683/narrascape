from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Narrascape color theme
NARRASCAPE_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "stage": "bold blue",
        "cache": "dim cyan",
    }
)

console = Console(theme=NARRASCAPE_THEME)


def setup_logging(
    level: int | str = logging.INFO,
    log_file: str | None = None,
    verbose: bool = False,
) -> logging.Logger:
    """Configure structured logging for narrascape pipeline.

    Args:
        level: Minimum log level (int or str: "DEBUG", "INFO", "WARNING", "ERROR")
        log_file: Optional file path to also log to
        verbose: If True, set DEBUG level and show module names
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    if verbose:
        level = logging.DEBUG

    # Root logger
    root = logging.getLogger("narrascape")
    root.setLevel(level)
    root.handlers = []  # Clear existing

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=verbose,
        rich_tracebacks=True,
        tracebacks_show_locals=verbose,
    )
    rich_handler.setLevel(level)
    formatter = logging.Formatter(
        "%(message)s",
        datefmt="[%X]",
    )
    rich_handler.setFormatter(formatter)
    root.addHandler(rich_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        root.addHandler(file_handler)

    # Suppress noisy third-party logs
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root


def log_stage(name: str, status: str, message: str = "") -> None:
    """Log a stage execution event with rich formatting."""
    logger = logging.getLogger("narrascape.pipeline")
    emoji = {"running": "▶️", "completed": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "•")
    logger.info(f"{emoji} [{name}] {status.upper()} {message}")
