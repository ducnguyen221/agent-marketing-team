# -*- coding: utf-8 -*-
"""Tên người duyệt: biến môi trường → studio.local.json → «chủ kênh»."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import approver as AP  # noqa: E402
import studio_paths as SP  # noqa: E402


@pytest.fixture
def repo_gia(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    (repo / "install.ps1").write_text("", encoding="utf-8")
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(repo))
    monkeypatch.delenv("MARKETING_APPROVER", raising=False)
    return repo


def _ghi_local(repo, **kw):
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")


def test_mac_dinh_la_chu_kenh(repo_gia):
    assert AP.ten_nguoi_duyet() == "chủ kênh"
    assert AP.ten_nguoi_duyet("vai khác") == "vai khác"


def test_file_cau_hinh_duoc_dung(repo_gia):
    _ghi_local(repo_gia, approver="  Lan  ")
    assert AP.ten_nguoi_duyet() == "Lan"


def test_bien_moi_truong_thang_file(repo_gia, monkeypatch):
    _ghi_local(repo_gia, approver="Lan")
    monkeypatch.setenv("MARKETING_APPROVER", "Minh")
    assert AP.ten_nguoi_duyet() == "Minh"


@pytest.mark.parametrize("gia_tri", ["", "   ", 5, None])
def test_gia_tri_rong_hoac_sai_kieu_bi_bo_qua(repo_gia, monkeypatch, gia_tri):
    monkeypatch.setenv("MARKETING_APPROVER", "  ")
    _ghi_local(repo_gia, approver=gia_tri)
    assert AP.ten_nguoi_duyet() == "chủ kênh"
