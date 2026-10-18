# -*- coding: utf-8 -*-
"""`scripts/runners/paths.py::station()` — trạm của runner Python.

Thứ tự: `MARKETING_STUDIO_DATA` → `studio_paths.resolve_station()` của repo (chỉ nhận khi nơi
đó CÓ `CHANNELS.md`) → DỪNG bằng `StationMissing` nêu tên biến. KHÔNG còn nấc "thư mục
`.marketing` trong nhà": nhà giả (`sandbox_home`) có trạm mồi ở đó và hàm phải phớt lờ nó.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import studio_contract as SC  # noqa: E402


def _nap_paths():
    """Nạp `scripts/runners/paths.py` thành module riêng (tên `paths` quá chung để import thường)."""
    spec = importlib.util.spec_from_file_location(
        "runners_paths_under_test", ROOT / "scripts" / "runners" / "paths.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tram(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "CHANNELS.md").write_text("---\nschema: channels/1\nchannels: []\n---\n",
                                   encoding="utf-8")
    return d


def test_station_theo_MARKETING_STUDIO_DATA(sandbox_home, tmp_path, monkeypatch):
    ws = _tram(tmp_path / "ws")
    monkeypatch.setenv("MARKETING_STUDIO_DATA", str(ws))
    assert _nap_paths().station() == str(ws)


def test_station_theo_resolve_station_cua_repo(sandbox_home, repo_gia):
    ws = _tram(repo_gia / "workspace")
    assert Path(_nap_paths().station()).resolve() == ws.resolve()


def test_station_khong_cau_hinh_nem_StationMissing_khong_doc_home(
        sandbox_home, repo_gia, capsys):
    assert (sandbox_home / ".marketing" / "CHANNELS.md").is_file()      # trạm mồi có thật
    with pytest.raises(SC.StationMissing) as e:
        _nap_paths().station()
    assert "MARKETING_STUDIO_DATA" in str(e.value)
    assert "WARN" not in capsys.readouterr().err                         # không còn đường cũ


@pytest.mark.parametrize("runner", ["append_excel_log.py", "merge_excel_pending.py"])
def test_runner_chay_truc_tiep_thieu_tram_thoat_gon_khong_traceback(
        runner, sandbox_home, repo_gia):
    import os
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "runners" / runner)],
                       capture_output=True, text=True, encoding="utf-8", env=dict(os.environ),
                       timeout=60)
    assert r.returncode != 0
    assert "MARKETING_STUDIO_DATA" in r.stderr
    assert "Traceback" not in r.stderr, r.stderr


def test_station_bien_rong_coi_nhu_khong_dat(sandbox_home, repo_gia, monkeypatch):
    monkeypatch.setenv("MARKETING_STUDIO_DATA", "  ")
    with pytest.raises(SC.StationMissing):
        _nap_paths().station()
