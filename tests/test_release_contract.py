from __future__ import annotations

import json
from pathlib import Path

import narrascape

ROOT = Path(__file__).parents[1]


def test_beta_release_version_and_readiness_contract_are_published():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")
    web_package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))

    assert narrascape.__version__ == "0.2.0-beta.1"
    assert web_package["version"] == "0.2.0-beta.1"
    assert "0.2.0-beta.1" in changelog
    assert "10" in readiness
    assert "not production-ready" in readiness.lower()
    assert "narrascape benchmark report" in readiness
