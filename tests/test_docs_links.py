from __future__ import annotations

import re
from pathlib import Path

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def test_markdown_relative_links_resolve():
    roots = [Path("README.md"), Path("AGENTS.md"), Path("docs")]
    files = [roots[0], *sorted(roots[1].rglob("*.md"))]
    missing: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = match.group(1).split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{path.as_posix()} -> {target}")

    assert missing == []
