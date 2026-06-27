from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

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
    """Configure structured logging for narrascape pipeline."""
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    if verbose:
        level = logging.DEBUG

    root = logging.getLogger("narrascape")
    root.setLevel(level)
    root.handlers = []

    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=verbose,
        rich_tracebacks=True,
        tracebacks_show_locals=verbose,
    )
    rich_handler.setLevel(level)
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    root.addHandler(rich_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root


def log_stage(name: str, status: str, message: str = "") -> None:
    """Log a stage execution event with rich formatting."""
    logger = logging.getLogger("narrascape.pipeline")
    marker = {"running": ">", "completed": "OK", "failed": "FAIL", "skipped": "SKIP"}.get(
        status, "-"
    )
    logger.info("%s [%s] %s %s", marker, name, status.upper(), message)
