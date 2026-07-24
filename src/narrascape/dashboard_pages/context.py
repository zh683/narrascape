from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DashboardPageContext:
    project_dir: Path | None
    config: Any
    stage_meta: dict[str, dict[str, Any]]
    get_pipeline_dir: Callable[[], Path | None]
    get_stage_dashboard: Callable[[], dict[str, Any]]
    start_command: Callable[[str, list[str]], None]
    fmt_size: Callable[[Path], str]
    fmt_bytes: Callable[[int], str]
