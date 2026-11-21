"""Unverified Postiz backup access must fail without touching supplied paths."""
import builtins
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "postiz_ctl.py"


def test_integrity_backend_does_not_touch_unverified_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("postiz_ctl", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "untrusted-backup"
    manifest = root / "manifest.json"

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not inspect or open any path before backend verification")

    with monkeypatch.context() as patch:
        for name in ("resolve", "stat", "lstat", "read_text", "open"):
            patch.setattr(Path, name, unexpected)
        patch.setattr(os, "open", unexpected)
        patch.setattr(os, "stat", unexpected)
        patch.setattr(os, "lstat", unexpected)
        patch.setattr(builtins, "open", unexpected)
        with pytest.raises(module.IntegrityError):
            module.verify_manifest(root, manifest)


def test_cli_reports_unavailable_without_success(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "verify-manifest", str(tmp_path / "b"), str(tmp_path / "b" / "m")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "passed" not in result.stdout.lower()
    assert "unavailable" in result.stderr.lower()
