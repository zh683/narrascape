from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


class OptionalRuntimeError(RuntimeError):
    """Raised when an optional UI runtime is not installed or built."""


def launch_streamlit_diagnostics(
    project_dir: Path,
    *,
    dashboard_path: Path,
    host: str,
    port: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if not dashboard_path.is_file():
        raise OptionalRuntimeError(f"Dashboard file not found: {dashboard_path}")
    if importlib.util.find_spec("streamlit") is None:
        raise OptionalRuntimeError('Streamlit is not installed; run pip install -e ".[dashboard]"')
    env = os.environ.copy()
    env["NARRASCAPE_DASHBOARD_PROJECT"] = str(project_dir.resolve())
    runner(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_path),
            "--server.port",
            str(port),
            "--server.address",
            host,
            "--browser.serverAddress",
            host,
            "--theme.base",
            "dark",
        ],
        check=True,
        env=env,
    )


def launch_native_workbench(project_dir: Path, *, host: str, port: int) -> None:
    if importlib.util.find_spec("fastapi") is None:
        raise OptionalRuntimeError(
            'Workbench dependencies are missing; run pip install -e ".[workbench]"'
        )
    from narrascape.workbench_api import serve

    serve(project_dir.resolve(), host=host, port=port)
