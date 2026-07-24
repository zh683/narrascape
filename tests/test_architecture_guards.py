from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path("src") / "narrascape"


def test_dashboard_entrypoint_stays_page_router_thin():
    dashboard_path = SRC_ROOT / "dashboard.py"
    text = dashboard_path.read_text(encoding="utf-8")

    assert len(text.splitlines()) <= 650
    for module_name, renderer in {
        "home": "render_home_page",
        "pipeline": "render_pipeline_page",
        "workbench": "render_workbench_page",
        "timeline": "render_timeline_page",
        "resources": "render_resources_page",
        "ai_director": "render_ai_director_page",
        "system": "render_system_page",
    }.items():
        assert (SRC_ROOT / "dashboard_pages" / f"{module_name}.py").exists()
        assert f"from narrascape.dashboard_pages.{module_name} import {renderer}" in text
        assert f"{renderer}(_dashboard_page_context())" in text


def test_core_artifact_writes_go_through_safe_io_helpers():
    offenders: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            reason = _unsafe_write_call(node)
            if reason:
                offenders.append(f"{path.as_posix()}:{node.lineno} {reason}")

    assert offenders == []


def _production_python_files() -> list[Path]:
    ignored = {
        SRC_ROOT / "utils" / "safe_io.py",
    }
    return [
        path
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if path not in ignored and "__pycache__" not in path.parts
    ]


def _unsafe_write_call(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in {"write_text", "write_bytes"}:
            return f"uses Path.{func.attr}; use narrascape.utils.safe_io"
        if func.attr in {"copy", "copy2", "copyfile"} and _name(func.value) == "shutil":
            return f"uses shutil.{func.attr}; use atomic_copy_file"
        if func.attr == "replace" and _name(func.value) == "os":
            return "uses os.replace; use atomic_promote_file"
        if func.attr == "open" and _write_mode_from_call(node):
            return "uses Path.open write mode; use narrascape.utils.safe_io"
    if isinstance(func, ast.Name) and func.id == "open" and _write_mode_from_call(node):
        return "uses open write mode; use narrascape.utils.safe_io"
    return ""


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else ""


def _write_mode_from_call(node: ast.Call) -> bool:
    mode = _literal_mode(node)
    return mode is not None and any(marker in mode for marker in ("w", "a", "x", "+"))


def _literal_mode(node: ast.Call) -> str | None:
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        value = node.args[1].value
        return value if isinstance(value, str) else None
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None
