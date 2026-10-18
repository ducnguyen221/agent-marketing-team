# -*- coding: utf-8 -*-
"""`init_station.py` — bộ cài hai chế độ (F17): `embedded` và `separate`.

Vì sao mỗi nhóm test dưới đây tồn tại:

· **Bộ cài phải HỎI, không được tự chọn im lặng.** Chế độ quyết định nội dung của người
  dùng nằm trong hay ngoài repo — chọn hộ là quyết hộ họ một thứ khó đảo.
· **Không có người trả lời thì DỪNG, đừng đoán.** Chạy trong CI, trong một tác vụ theo
  lịch, hay qua pipe: `input()` ném `EOF` và một bộ cài ẩu sẽ hiểu thành "Enter". Ở đây
  nó phải in bảng lựa chọn ra rồi thoát mã 2 mà **chưa ghi gì**.
· **Máy đã có trạm ngoài thì không bao giờ mọc thêm `workspaces/`.** Đó là bảo vệ máy đang
  chạy lịch thật: hai nguồn sự thật cho cùng một repo là cách mất dữ liệu êm nhất.

Mọi test chạy trong thư mục tạm: repo giả (`MARKETING_STUDIO_HOME`) + nhà giả
(`HOME`/`USERPROFILE`). Không đụng trạm thật, không đụng `~`.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
import doctor as DR  # noqa: E402
import init_station as IS  # noqa: E402
import studio_contract as SC  # noqa: E402
import studio_paths as SP  # noqa: E402

NHA_CU = "." + "marketing"      # tên thư mục ẩn kiểu cũ trong nhà; ghép chuỗi để test chống chữ cũ không bắt chính nó

BIEN_HOP_DONG = ("MARKETING_STUDIO_DATA", "MARKETING_STUDIO_HOME", "VOICE_STATION",
                 "OMNIVOICE_DIR", "VIDEO_STATION", "VIDEO_ROOT")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Bản sao TỐI THIỂU của repo: đủ mốc để `repo_root()` nhận ra + cây mẫu thật."""
    r = tmp_path / "repo"
    (r / "scripts" / "lib").mkdir(parents=True)
    (r / "install.ps1").write_text("", encoding="utf-8")
    shutil.copytree(ROOT / "templates" / "workspace", r / "templates" / "workspace")
    (r / "templates" / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "templates" / "hooks" / "pre-commit",
                    r / "templates" / "hooks" / "pre-commit")
    shutil.copyfile(ROOT / ".env.example", r / ".env.example")
    nha = tmp_path / "nha"
    nha.mkdir()
    monkeypatch.setenv("HOME", str(nha))
    monkeypatch.setenv("USERPROFILE", str(nha))
    for b in BIEN_HOP_DONG:
        monkeypatch.delenv(b, raising=False)
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(r))
    return r


@pytest.fixture
def nha(tmp_path):
    return tmp_path / "nha"


def khong_duoc_hoi(_bang):
    raise AssertionError("bộ cài không được hỏi trong trường hợp này")


def chup(*goc):
    ra = set()
    for g in goc:
        for dp, dn, fn in os.walk(g):
            for n in dn + fn:
                ra.add(os.path.join(dp, n))
    return ra


def cay_tram_ok(st: Path):
    assert (st / "CHANNELS.md").is_file()
    assert (st / "README.md").is_file()
    return st


def doc_local(repo: Path) -> dict:
    return json.loads((repo / SP.LOCAL_CONFIG).read_text(encoding="utf-8"))


# ── embedded ──────────────────────────────────────────────────────────────────────────

def test_Enter_nghia_la_embedded(repo, nha):
    bang = []
    kq = IS.do_init(ask=lambda b: bang.append(b) or "")
    ws = repo / SP.WORKSPACE
    cay_tram_ok(ws)
    assert kq["mode"] == "embedded"
    assert Path(kq["station"]) == ws.resolve()
    t = bang[0]
    for phai_co in ("embedded", "separate", "KHUYẾN NGHỊ", "Là gì", "Lợi", "Hại", "Chọn khi"):
        assert phai_co in t, f"bảng lựa chọn thiếu mục {phai_co!r}"
    lc = doc_local(repo)
    assert lc["mode"] == "embedded" and lc["station_path"] == SP.WORKSPACE
    assert lc["secrets"] == ".env"
    # mọi script từ giờ phân giải ra đúng trạm này
    st, nguon = SP.resolve_station()
    assert st == ws.resolve() and nguon == SP.WORKSPACE      # tên nhúng không được tin: đi qua tram_nhung
    assert not (nha / NHA_CU).exists(), "embedded không được tạo thư mục kiểu cũ trong nhà"


# ── bảng lựa chọn PHÂN TÍCH theo trình độ người dùng (chỉ đạo 21/09) ──────────────────
#
# "Hỏi trống" — `Chọn [1/2]?` không kèm gì — là đẩy một quyết định khó đảo sang người
# chưa có dữ kiện để quyết. Bảng này phải TỰ PHÂN TÍCH: nói thẳng người kiểu nào nên chọn
# nhánh nào, và khuyến nghị một nhánh.

def test_bang_lua_chon_DAN_nguoi_dung_theo_TRINH_DO(repo):
    """Người không rành kỹ thuật phải đọc được câu dành cho mình ở nhánh `embedded`, và
    người nhiều máy/repo public đọc được câu của mình ở nhánh `separate`."""
    t = IS.BANG_LUA_CHON
    d1 = t[t.index("[1]"):t.index("[2]")]
    d2 = t[t.index("[2]"):]
    assert "không rành kỹ thuật" in d1, d1
    assert "KHUYẾN NGHỊ" in d1 and "Enter" in d1, d1
    for cum in ("rành kỹ thuật", "nhiều máy", "public"):
        assert cum in d2, f"nhánh separate thiếu {cum!r}:\n{d2}"


def test_bang_lua_chon_noi_ro_KHONG_BAT_BUOC_tram_giong_video(repo):
    """Lúc cài KHÔNG hỏi vu vơ "bạn có muốn cài trạm giọng/video không" — nhưng phải nói
    rằng cài xong là dùng được ngay, nếu không người mới tưởng mình còn thiếu hai repo nữa
    và bỏ dở giữa chừng. Lời đề nghị cài đến sau, đúng lúc chạm bước cần (voice.py)."""
    t = IS.BANG_LUA_CHON
    assert "không bắt buộc trạm giọng/video" in t, t
    assert "viết bài và đăng" in t.lower(), t


def test_co_yes_thi_nhan_khuyen_nghi_khong_hoi(repo):
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded" and (repo / SP.WORKSPACE / "CHANNELS.md").is_file()


def test_embedded_tao_env_tu_env_example_va_khoa_quyen(repo):
    IS.do_init(yes=True)
    f = repo / ".env"
    assert f.is_file(), "embedded phải dọn sẵn <repo>/.env để người dùng điền"
    assert "MARKETING_STUDIO_DATA" in f.read_text(encoding="utf-8")
    if os.name != "nt":
        assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_embedded_cai_hook_pre_commit_va_KHONG_de_ban_co_san(repo):
    (repo / ".git" / "hooks").mkdir(parents=True)
    kq = IS.do_init(yes=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.is_file() and "pre_commit_guard" in hook.read_text(encoding="utf-8")
    assert kq["hook"] == "đã cài"
    hook.write_text("#!/bin/sh\necho cua toi\n", encoding="utf-8")
    kq2 = IS.do_init(yes=True)
    assert "cua toi" in hook.read_text(encoding="utf-8") and kq2["hook"] == "giữ bản có sẵn"


def test_chay_lai_KHONG_de_file_da_co(repo):
    IS.do_init(yes=True)
    f = repo / SP.WORKSPACE / "CHANNELS.md"
    f.write_text("---\nschema: channels/1\nchannels: []\n---\n# của tôi\n", encoding="utf-8")
    IS.do_init(yes=True)
    assert "của tôi" in f.read_text(encoding="utf-8")


# ── separate: tường minh và tự nhận diện ──────────────────────────────────────────────

def tra_loi(*cau):
    """Người dùng giả: trả lần lượt từng câu, ghi lại mọi câu hỏi đã nhận. Hỏi nhiều hơn
    số câu đã chuẩn bị là lỗi (bộ cài hỏi thừa)."""
    con = list(cau)
    da_hoi = []

    def ask(bang):
        da_hoi.append(bang)
        assert con, "bộ cài hỏi nhiều hơn dự kiến:\n" + bang
        return con.pop(0)
    ask.da_hoi = da_hoi
    return ask


def test_tra_loi_2_roi_go_duong_thi_separate_o_duong_do(repo, nha, tmp_path):
    dich = tmp_path / "tram-moi"
    ask = tra_loi("2", str(dich))
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "separate" and len(ask.da_hoi) == 2
    cay_tram_ok(dich)
    assert Path(doc_local(repo)["station_path"]) == dich.resolve()
    assert not (repo / SP.WORKSPACE).exists() and not (nha / NHA_CU).exists()


def test_tra_loi_2_roi_Enter_rong_khong_co_goi_y_thi_DUNG_khong_ghi_gi(repo, nha):
    truoc = chup(repo, nha)
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(ask=tra_loi("2", ""))
    assert chup(repo, nha) == truoc and not (repo / SP.LOCAL_CONFIG).exists()


def test_separate_khong_station_khong_nguoi_hoi_thi_ma_2_doi_station_va_khong_ghi_gi(repo, nha):
    truoc = chup(repo, nha)
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(mode="separate", non_interactive=True)
    assert chup(repo, nha) == truoc and not (nha / NHA_CU).exists()


def test_separate_khong_station_KHONG_roi_ve_thu_muc_trong_nha(repo, nha):
    with pytest.raises(SC.ContractError):
        IS.chon_che_do(mode="separate", non_interactive=True)
    assert not (nha / NHA_CU).exists()


def test_co_station_thi_separate_khong_hoi(repo, tmp_path):
    st = tmp_path / "noi-khac"
    kq = IS.do_init(station=str(st), ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and kq["reason"] == "--station"
    cay_tram_ok(st)
    assert not (repo / SP.WORKSPACE).exists()
    assert Path(doc_local(repo)["station_path"]) == st.resolve()


def test_MARKETING_STUDIO_DATA_da_dat_thi_TU_CHON_separate(repo, tmp_path, monkeypatch):
    """Máy Đức: biến đã có từ trước ⇒ không hỏi, và KHÔNG BAO GIỜ tạo workspaces/."""
    ngoai = tmp_path / "tram-cu"
    ngoai.mkdir()
    monkeypatch.setenv("MARKETING_STUDIO_DATA", str(ngoai))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)       # kể cả khi được bảo "nhận khuyến nghị"
    assert kq["mode"] == "separate" and "MARKETING_STUDIO_DATA" in kq["reason"]
    assert not (repo / SP.WORKSPACE).exists()
    assert Path(kq["station"]) == ngoai.resolve()


@pytest.mark.parametrize("bien", ["VOICE_STATION", "VIDEO_STATION", "OMNIVOICE_DIR", "VIDEO_ROOT"])
def test_bien_tram_nang_luc_da_dat_thi_van_separate_nhung_KHONG_doan_duong(
        bien, repo, tmp_path, nha, monkeypatch):
    """Biến của trạm giọng/video nói "máy này theo mô hình trạm ngoài" nhưng KHÔNG nói trạm
    nội dung ở đâu: không workspaces/ trong repo, không đoán thư mục trong nhà — hỏi đường."""
    ngoai = tmp_path / "tram-cu"
    ngoai.mkdir()
    monkeypatch.setenv(bien, str(ngoai))
    dich = tmp_path / "noi-chon"
    ask = tra_loi(str(dich))
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "separate" and bien in kq["reason"]
    assert not (repo / SP.WORKSPACE).exists() and not (nha / NHA_CU).exists()
    assert Path(kq["station"]) == dich.resolve() and len(ask.da_hoi) == 1
    # không hỏi được ⇒ dừng, nêu --station
    (repo / SP.LOCAL_CONFIG).unlink()
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(non_interactive=True)
    # --yes cũng KHÔNG hỏi đường (có người nghe hay không): thiếu đường thì dừng
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert not (repo / SP.LOCAL_CONFIG).exists()


def test_yes_voi_bien_tram_nang_luc_va_bien_OPCOS_dung_luon_de_xuat(repo, tmp_path, monkeypatch,
                                                                    capsys):
    monkeypatch.setenv("VOICE_STATION", str(tmp_path))
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert Path(kq["station"]) == (tmp_path / "ws" / "marketing").resolve()
    assert len([d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]) >= 1


def test_duong_go_tuong_doi_duoc_tuyet_doi_hoa_va_ghi_station_path_tuyet_doi(repo, tmp_path,
                                                                             monkeypatch):
    monkeypatch.chdir(tmp_path)
    kq = IS.do_init(ask=tra_loi("2", "tram-tuong-doi"))
    dich = (tmp_path / "tram-tuong-doi").resolve()
    assert Path(kq["station"]) == dich and os.path.isabs(kq["station"])
    ghi = doc_local(repo)["station_path"]
    assert os.path.isabs(ghi) and Path(ghi) == dich


@pytest.mark.parametrize("bao", ['"{}"', "'{}'", ' "{}" '])
def test_duong_dan_dan_kem_ngoac_kep_bao_quanh_van_dung(bao, repo, tmp_path):
    """'Copy as path' của Windows dán vào kèm cặp ngoặc kép."""
    dich = tmp_path / "tram co dau cach"
    kq = IS.do_init(ask=tra_loi("2", bao.format(dich)))
    assert Path(kq["station"]) == dich.resolve() and dich.is_dir()
    assert '"' not in kq["station"] and "'" not in kq["station"]


def tao_thu_muc_nha_kieu_cu(nha: Path) -> Path:
    """Thư mục ẩn kiểu cũ trong nhà, mang CHANNELS.md. Không còn được dò/nhận/nhắc."""
    cu = nha / NHA_CU
    cu.mkdir(parents=True)
    (cu / "CHANNELS.md").write_text("---\nchannels: []\n---\n# cua toi\n", encoding="utf-8")
    return cu


def tao_bo_cuc_cu(repo: Path) -> Path:
    """`<repo>/workspace` (số ít) của bản cài trước, mang dấu trạm."""
    cu = repo / SP.WORKSPACE_CU
    cu.mkdir()
    (cu / "CHANNELS.md").write_text("---\nchannels: []\n---\n# cua toi\n", encoding="utf-8")
    return cu


@pytest.mark.parametrize("cach", ["yes", "hoi", "mode_embedded"])
def test_thu_muc_nha_kieu_cu_KHONG_bao_gio_duoc_nhan_hay_nhac(cach, repo, nha, capsys):
    cu = tao_thu_muc_nha_kieu_cu(nha)
    truoc = chup(cu)
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(mode="embedded", ask=khong_duoc_hoi) if cach == "mode_embedded" else dict(ask=tra_loi(""))
    kq = IS.do_init(**kw)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == (repo / SP.WORKSPACE).resolve()
    assert chup(cu) == truoc and (cu / "CHANNELS.md").read_text(encoding="utf-8").endswith("cua toi\n")
    assert NHA_CU not in capsys.readouterr().err and NHA_CU not in kq["reason"]


def test_khong_con_ham_hay_hang_so_do_thu_muc_kieu_cu():
    for ten in ("legacy_station", "tram_cu_o_nha", "_nhac_tram_cu", "CAU_HOI_TRAM_CU"):
        assert not hasattr(IS, ten), ten


def test_init_moi_tao_dung_workspaces_va_KHONG_bao_gio_tao_workspace_so_it(repo):
    kq = IS.do_init(yes=True)
    cay_tram_ok(repo / "workspaces")
    assert Path(kq["station"]) == (repo / "workspaces").resolve()
    assert not (repo / SP.WORKSPACE_CU).exists()
    assert doc_local(repo)["station_path"] == "workspaces"


def test_bo_cuc_cu_workspace_so_it_duoc_nhan_va_nhac_doi_ten_mot_dong(repo, capsys):
    cu = tao_bo_cuc_cu(repo)
    truoc = chup(cu)
    assert SP.resolve_station() == (cu.resolve(), SP.WORKSPACE_CU)      # trước khi init ghi gì
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert Path(kq["station"]) == cu.resolve() and not (repo / "workspaces").exists()
    assert doc_local(repo)["station_path"] == "workspaces"      # ghi tên MỚI; bộ phân giải không tin chuỗi
    assert (cu / "CHANNELS.md").read_text(encoding="utf-8").endswith("cua toi\n")
    dong = [d for d in capsys.readouterr().err.splitlines() if "workspaces" in d and "workspace" in d
            and "[init]" in d and "đổi tên" in d]
    assert len(dong) == 1, dong
    assert SP.resolve_station()[0] == cu.resolve()
    assert chup(cu) >= truoc


def test_bo_cuc_cu_va_moi_cung_ton_tai_thi_uu_tien_workspaces_va_nhac(repo, capsys):
    tao_bo_cuc_cu(repo)
    (repo / "workspaces").mkdir()
    assert SP.resolve_station() == ((repo / "workspaces").resolve(), "workspaces")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert Path(kq["station"]) == (repo / "workspaces").resolve()
    assert len([d for d in capsys.readouterr().err.splitlines() if "[init]" in d and "workspace" in d]) == 1


def test_workspace_so_it_khong_co_dau_tram_thi_khong_duoc_nhan(repo):
    (repo / SP.WORKSPACE_CU).mkdir()
    assert SP.resolve_station() == ((repo / "workspaces").resolve(), "default")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert Path(kq["station"]) == (repo / "workspaces").resolve()


@pytest.mark.parametrize("config", ["cu-workspace", "moi-workspaces", "khong"])
@pytest.mark.parametrize("bo_cuc", ["A-chi-cu", "B-chi-moi", "C-ca-hai"])
def test_station_path_embedded_la_TEN_khong_duoc_tin_chuoi(bo_cuc, config, repo, capsys):
    """(A) chỉ `workspace` cũ: nhận đúng và nhắc; (B) đã đổi tên theo gợi ý: KHÔNG mất trạm dù config
    còn ghi `workspace`; (C) cả hai: `workspaces` thắng dù config ghi `workspace`."""
    if bo_cuc != "B-chi-moi":
        tao_bo_cuc_cu(repo)
    if bo_cuc != "A-chi-cu":
        (repo / "workspaces").mkdir()
        (repo / "workspaces" / "CHANNELS.md").write_text("---\nchannels: []\n---\n", encoding="utf-8")
    if config != "khong":
        ten = "workspace" if config == "cu-workspace" else "workspaces"
        (repo / SP.LOCAL_CONFIG).write_text(
            json.dumps({"mode": "embedded", "station_path": ten}), encoding="utf-8")
    mong = repo / ("workspace" if bo_cuc == "A-chi-cu" else "workspaces")
    st, nguon = SP.resolve_station()
    assert st == mong.resolve() and nguon in ("workspace", "workspaces", "default"), (st, nguon)
    assert nguon != SP.LOCAL_CONFIG
    # doctor nhắc đúng khi còn bố cục cũ (A, C), im khi không (B)
    kq = DR.kham()
    nhac = [w for w in kq["warn"] if "đổi tên" in w or "bố cục cũ" in w]
    assert bool(nhac) == (bo_cuc != "B-chi-moi"), (bo_cuc, config, kq["warn"])
    # init chạy lại: cùng trạm, nhắc một dòng khi còn bố cục cũ, ghi lại tên MỚI
    kq2 = IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert Path(kq2["station"]) == mong.resolve()
    dong = [d for d in capsys.readouterr().err.splitlines()
            if "[init]" in d and ("đổi tên" in d or "bố cục cũ" in d or "workspace" in d and "cả" in d)]
    assert len(dong) == (0 if bo_cuc == "B-chi-moi" else 1), dong
    assert doc_local(repo)["station_path"] == "workspaces"


def test_station_path_workspace_cua_separate_hoac_duong_khac_van_duoc_tin(repo, tmp_path):
    (repo / "workspaces").mkdir()
    (repo / "khac").mkdir()
    for cfg, mong in ((  {"mode": "separate", "station_path": "workspace"}, repo / "workspace"),
                      ({"mode": "embedded", "station_path": "khac"}, repo / "khac"),
                      ({"mode": "embedded", "station_path": str(tmp_path / "ngoai")}, tmp_path / "ngoai")):
        (repo / SP.LOCAL_CONFIG).write_text(json.dumps(cfg), encoding="utf-8")
        assert SP.resolve_station() == (mong.resolve(), SP.LOCAL_CONFIG), cfg


def test_giong_PS_va_Python_ve_bo_cuc_cu_va_moi_dung_mot_dinh_nghia_co_that():
    """Python: bố cục mới chỉ cần là thư mục, bố cục cũ phải mang CHANNELS.md — PowerShell cùng luật."""
    ps = (ROOT / "scripts" / "runners" / "brand-paths.ps1").read_text(encoding="utf-8-sig")
    assert "Join-Path $script:RepoRoot 'workspaces'" in ps and "-PathType Container" in ps
    assert "Join-Path $cu 'CHANNELS.md'" in ps


# ── BẢNG HÀNH VI CHUNG (cùng một bảng cho voice / video / marketing) ──────────────────
#
# {bố cục trong repo: không có / `workspaces` / `workspace` cũ / cả hai} × {OPCOS_WORKSPACES:
# đặt/không} × kịch bản. Kết quả: (chế độ, đích) với W = trạm nhúng (`<repo>/workspaces`, hoặc
# `<repo>/workspace` cũ khi CHỈ có nó), V = <biến>/marketing, P = đường người dùng gõ; hoặc "LOI"
# = mã 2 và chưa ghi gì. `hoi` = số câu hỏi đã đưa ra; `nhac` = số dòng khuyến nghị đổi tên bố cục
# cũ (chỉ khi kết quả là embedded và còn `workspace` cũ).
# Có biến + có người ngồi + không --mode: Enter ra thẳng V (không có bảng chế độ).

W, V, P, LOI = "W", "V", "P", "LOI"
BO_CUC = ["khong", "moi", "cu", "ca-hai"]


def _mong(kich_ban, bo_cuc, bien):
    """-> (kết quả, số câu hỏi, số dòng nhắc đổi tên bố cục cũ)"""
    nhac = 1 if bo_cuc in ("cu", "ca-hai") else 0
    if kich_ban == "Enter":
        return (("separate", V), 1, 0) if bien else (("embedded", W), 1, nhac)
    if kich_ban == "2":                                   # chỉ khi KHÔNG có biến (bảng chế độ)
        return ("separate", P), 2, 0
    if kich_ban == "3":                                   # chỉ khi KHÔNG có biến: lựa chọn sai
        return LOI, 1, 0
    if kich_ban in ("yes", "ni_yes", "mode_embedded"):
        return ("embedded", W), 0, nhac
    if kich_ban == "ni":
        return LOI, 0, 0
    if kich_ban in ("mode_separate_ni", "mode_separate_yes"):
        return (("separate", V) if bien else LOI), 0, 0
    if kich_ban == "mode_separate_hoi":
        return ("separate", V if bien else P), 1, 0
    raise AssertionError(kich_ban)


KICH_BAN = ["Enter", "2", "3", "yes", "ni", "ni_yes", "mode_embedded",
            "mode_separate_ni", "mode_separate_yes", "mode_separate_hoi"]


def _to_hop():
    for kb in KICH_BAN:
        for bc in BO_CUC:
            for bien in (False, True):
                if kb in ("2", "3") and bien:
                    continue
                yield pytest.param(kb, bc, bien, id=f"{kb}-{bc}-{'co-bien' if bien else 'khong-bien'}")


@pytest.mark.parametrize("kich_ban,bo_cuc,bien", list(_to_hop()))
def test_bang_hanh_vi_chung(kich_ban, bo_cuc, bien, repo, nha, tmp_path, monkeypatch, capsys):
    if bo_cuc in ("moi", "ca-hai"):
        (repo / "workspaces").mkdir()
    cu = tao_bo_cuc_cu(repo) if bo_cuc in ("cu", "ca-hai") else None
    if bien:
        monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    duong_go = tmp_path / "tram-go"
    nhung = cu if bo_cuc == "cu" else (repo / "workspaces")
    moc = {W: nhung.resolve(), V: (tmp_path / "ws" / "marketing").resolve(), P: duong_go.resolve()}
    # câu trả lời chuẩn bị sẵn; câu hỏi đường: có biến thì Enter (nhận đề xuất), không thì gõ P
    cau_duong = "" if bien else str(duong_go)
    kw, tra = {}, []
    if kich_ban == "Enter":
        tra = [""]
    elif kich_ban == "2":
        tra = ["2", cau_duong]
    elif kich_ban == "3":
        tra = ["3"]
    elif kich_ban == "yes":
        kw = dict(yes=True, ask=khong_duoc_hoi)
    elif kich_ban == "ni":
        kw = dict(non_interactive=True)
    elif kich_ban == "ni_yes":
        kw = dict(non_interactive=True, yes=True)
    elif kich_ban == "mode_embedded":
        kw = dict(mode="embedded", ask=khong_duoc_hoi)
    elif kich_ban == "mode_separate_ni":
        kw = dict(mode="separate", non_interactive=True)
    elif kich_ban == "mode_separate_yes":
        kw = dict(mode="separate", yes=True, ask=khong_duoc_hoi)
    elif kich_ban == "mode_separate_hoi":
        tra = [cau_duong]
        kw = dict(mode="separate")
    ask = tra_loi(*tra) if tra else None
    if ask:
        kw["ask"] = ask
    mong, hoi, nhac = _mong(kich_ban, bo_cuc, bien)
    truoc = chup(repo)
    if mong == LOI:
        with pytest.raises(SC.ContractError):
            IS.chon_che_do(**kw)
        assert chup(repo) == truoc
    else:
        mode, st, _ = IS.chon_che_do(**kw)
        assert (mode, Path(st)) == (mong[0], moc[mong[1]]), (mode, st)
    assert (len(ask.da_hoi) if ask else 0) == hoi
    dong = [d for d in capsys.readouterr().err.splitlines()
            if "[init]" in d and "workspace" in d and ("đổi tên" in d or "bố cục cũ" in d)]
    assert len(dong) == nhac, dong
    if ask and kich_ban == "2":                          # bảng chế độ nêu đúng đường embedded
        assert "<repo>/workspaces/" in ask.da_hoi[0] and "workspaces/marketing" not in ask.da_hoi[0]


def test_changelog_chua_phat_hanh_noi_dung_cach_dung_bo_cuc_moi_va_ca_exit_2():
    t = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    khoi = t[t.index("### Chưa phát hành"):t.index("## 2.0.0")]
    assert NHA_CU not in khoi, "khối chưa phát hành không được nhắc tên thư mục kiểu cũ"
    assert ".- " not in khoi, "bullet dính dòng"
    assert all(d.startswith("- ") or not d.strip() or d.startswith("###") for d in khoi.splitlines()), \
        "mỗi ý của khối chưa phát hành là một bullet riêng"
    assert "chỉ còn là tên" in khoi and "không tin chuỗi" in khoi
    assert "`--station <đường>`" in khoi
    assert "`<biến>/marketing`" in khoi and "`<repo>/workspaces`" in khoi
    assert "VOICE_STATION" in khoi and "mã 2" in khoi, "init --yes + biến trạm giọng/video thiếu biến OpcOS"


def test_may_da_chon_tu_truoc_thi_khong_hoi_lai(repo):
    """Chạy lại `init` trên bản cài đã chọn: dùng lựa chọn cũ, không hỏi."""
    IS.do_init(yes=True)
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"


def test_doi_embedded_khi_may_da_co_tram_ngoai_la_LOI_khong_phai_cam_ket(repo, tmp_path,
                                                                         monkeypatch):
    monkeypatch.setenv("MARKETING_STUDIO_DATA", str(tmp_path / "tram-cu"))
    with pytest.raises(SC.ContractError, match="hai nguồn sự thật"):
        IS.do_init(mode="embedded")
    assert not (repo / SP.WORKSPACE).exists()


# ── không có người trả lời ────────────────────────────────────────────────────────────

def test_khong_co_nguoi_tra_loi_thi_ma_2_va_KHONG_ghi_gi(repo, nha, capsys):
    truoc = chup(repo)
    ma = IS.main(["--json"])                 # stdin của pytest không phải terminal
    out, err = capsys.readouterr()
    assert ma == SC.CONTRACT_ERROR
    assert "embedded" in err and "separate" in err and "--mode" in err
    assert json.loads(out.strip().splitlines()[-1])["ok"] is False
    assert chup(repo) == truoc and not (nha / NHA_CU).exists()


def test_tra_loi_bay_la_ma_2_va_KHONG_ghi_gi(repo):
    truoc = chup(repo)
    with pytest.raises(SC.ContractError):
        IS.do_init(ask=lambda b: "ba")
    assert chup(repo) == truoc


def test_existing_ma_khong_co_thu_muc_la_ma_3(repo, tmp_path):
    with pytest.raises(SC.StationMissing):
        IS.do_init(station=str(tmp_path / "khong-co"), existing=True)


def test_dry_run_khong_ghi_gi(repo, nha):
    truoc = chup(repo)
    kq = IS.do_init(yes=True, dry_run=True)
    assert kq["mode"] == "embedded" and kq["dry_run"] is True
    assert chup(repo) == truoc and not (nha / NHA_CU).exists()


# ── cross-repo (F17.3): bộ cài ghi lại trạm giọng/video đã có ──────────────────────────

def test_ghi_lai_tram_giong_video_neu_may_da_co(repo, tmp_path, monkeypatch):
    giong, video = tmp_path / "giong", tmp_path / "video"
    for d in (giong, video):
        d.mkdir()
        (d / "station.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VOICE_STATION", str(giong))
    monkeypatch.setenv("VIDEO_STATION", str(video))
    IS.do_init(yes=True, station=str(tmp_path / "tram-noi-dung"))
    lc = doc_local(repo)
    assert Path(lc["voice_station"]) == giong.resolve()
    assert Path(lc["video_station"]) == video.resolve()


def test_tram_tu_repo_ANH_EM_thi_KHONG_ghi_duong_tuyet_doi(repo, tmp_path):
    """Trạm giọng/video tìm ra nhờ repo anh em cùng thư mục cha thì KHÔNG đóng băng vào
    `studio.local.json`: dời cả thư mục chứa các repo đi thì nấc anh em vẫn tự tìm lại,
    còn một đường tuyệt đối cũ (đứng trước nấc anh em) sẽ trỏ vào chỗ không còn."""
    for thu_muc, ten in (("giong-o-day", "agent-voice-studio"), ("video-o-day", "agent-video-studio")):
        r = tmp_path / thu_muc
        (r / "workspace").mkdir(parents=True)
        (r / "pyproject.toml").write_text(f'[project]\nname = "{ten}"\n', encoding="utf-8")
    assert SP.voice_station() == (tmp_path / "giong-o-day" / "workspace").resolve()
    IS.do_init(yes=True)
    lc = doc_local(repo)
    assert "voice_station" not in lc and "video_station" not in lc, lc


# ── cây trạm dựng ra phải qua được cổng thật ──────────────────────────────────────────

@pytest.mark.parametrize("che_do", ["embedded", "separate"])
def test_check_tree_XANH_tren_cay_vua_dung(che_do, repo, tmp_path, nha):
    kq = IS.do_init(station=str(tmp_path / "ngoai") if che_do == "separate" else None,
                    yes=(che_do == "embedded"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pipeline" / "check_tree.py"),
                        "--station", kq["station"]],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 đỏ" in r.stdout


def test_CLI_json_in_dung_mot_dong_ket_qua(repo, capsys):
    ma = IS.main(["--yes", "--json"])
    out, _ = capsys.readouterr()
    assert ma == SC.OK
    kq = json.loads(out.strip().splitlines()[-1])
    assert kq["ok"] is True and kq["mode"] == "embedded"


# ── hai vỏ phải đi cùng nhau ──────────────────────────────────────────────────────────
#
# `install.ps1` và `install.sh` là hai cửa vào của CÙNG một bộ cài. Chúng trôi khỏi nhau
# một cách im lặng: sửa bên Windows rồi quên bên macOS thì không test nào đỏ, và người
# dùng macOS nhận một bộ cài khác — chỉ phát hiện khi họ đã cài xong.

INSTALL_PS1 = ROOT / "install.ps1"
INSTALL_SH = ROOT / "install.sh"


def test_ca_hai_vo_deu_giao_viec_cho_init_station():
    for f in (INSTALL_PS1, INSTALL_SH):
        t = f.read_text(encoding="utf-8-sig")
        assert "init_station.py" in t, f"{f.name} không gọi lõi chung"


def test_install_sh_khong_BOM_va_dung_LF():
    tho = INSTALL_SH.read_bytes()
    assert not tho.startswith(b"\xef\xbb\xbf"), "BOM làm `#!` hỏng: sh sẽ không chạy được file"
    assert b"\r\n" not in tho, "CRLF trong script sh = 'bad interpreter' trên macOS"
    assert tho.startswith(b"#!/bin/sh")


@pytest.mark.skipif(not shutil.which("sh"), reason="máy không có sh")
def test_install_sh_dung_cu_phap():
    r = subprocess.run([shutil.which("sh"), "-n", str(INSTALL_SH)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr


def test_install_ps1_giu_BOM():
    """PS 5.1 đọc file không BOM bằng ANSI — tiếng Việt trong file vỡ ngay dòng đầu."""
    assert INSTALL_PS1.read_bytes()[:3] == b"\xef\xbb\xbf"


# ── Bộ cài phải CHỈ ĐƯỜNG sang tài liệu ──────────────────────────────────────
# `install.sh`/`install.ps1` chỉ là vỏ dò interpreter; phần in ra cho người dùng nằm ở
# đây. Người vừa cài xong là người duy nhất chưa biết đọc tiếp cái gì — và cũng là người
# sắp mắc lỗi đắt nhất của cả hệ (bật lịch trên máy thứ hai).

@pytest.mark.parametrize("duong", ["docs/ONBOARDING.md", "docs/WORKSPACE.md",
                                   "docs/RUNBOOK-DOI-MAY.md"])
def test_bo_cai_in_duong_tai_lieu(capsys, duong):
    IS._in({"dry_run": False, "mode": "embedded", "station": "/x", "reason": "test",
            "created": [], "hook": None})
    ra = capsys.readouterr()
    assert duong in (ra.out + ra.err), f"bộ cài không chỉ sang {duong}"
    assert (ROOT / duong).is_file(), f"{duong} được in ra nhưng không tồn tại"


# ══ REVIEW-P2 N6 + N7 — lỗi CẤU HÌNH của `--station` phải là mã 2, và không ═
# ══ bao giờ để lại một cây nửa vời ══════════════════════════════════════════

def test_station_tro_vao_mot_FILE_la_ma_2(tmp_path):
    """`FileExistsError` lọt ra thành mã 1 = "thử lại được", và lịch chạy/CI sẽ thử lại
    vô hạn một lỗi gõ nhầm đường dẫn."""
    f = tmp_path / "toi-la-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(IS.SC.ContractError):
        IS.do_init(station=str(f), yes=True)


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH la luat cua Windows")
def test_duong_qua_MAX_PATH_la_ma_2_va_KHONG_tao_gi(tmp_path):
    """`station import` đã học bài này (`station.py:267`), `init_station` thì chưa: mkdir
    tạo được vài cấp rồi nổ, để lại cây nửa vời mà người dùng không biết dọn gì."""
    sau = tmp_path / ("x" * 90) / ("y" * 90) / ("z" * 90) / ("w" * 90)
    with pytest.raises(IS.SC.ContractError) as e:
        IS.do_init(station=str(sau), yes=True)
    assert "260" in str(e.value) or "dài" in str(e.value).lower()
    assert not (tmp_path / ("x" * 90)).exists(), "đã nổ mà vẫn để lại cây nửa vời"


def test_hai_VO_cai_xu_su_GIONG_NHAU_khi_khong_co_ai_tra_loi():
    """REVIEW-P2 N8. `install.sh --noninteractive` cho mã 2 (lõi không hiểu cờ, và kể cả
    hiểu thì luật "không có người ⇒ không đoán" cũng cho mã 2), trong khi `install.ps1
    -NonInteractive` lặng lẽ đổi thành `--yes` ⇒ cài embedded không hỏi ai.

    Đó là hai bộ cài khác nhau cho hai hệ điều hành — đúng thứ P2-T02 gộp lõi để tránh.
    Cổng này canh bằng văn bản vì không chạy được `install.ps1` thật trên máy CI macOS."""
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    dong = [d.strip() for d in ps1.splitlines()
            if "--yes" in d and not d.strip().startswith("#")]
    assert dong, "khong thay dong ghep --yes trong install.ps1"
    for d in dong:
        assert "NonInteractive" not in d, (
            "`-NonInteractive` KHONG duoc tu bien thanh `--yes`: khong co ai tra loi thi "
            "dung va bao ma 2, giong het install.sh")


def test_hai_VO_deu_chuyen_co_KHONG_TUONG_TAC_vao_LOI():
    """Parity phải là parity THẬT: cả hai vỏ cùng đổ vào một cờ của lõi, chứ không phải
    mỗi vỏ tự diễn giải "không có ai ngồi đây" theo cách riêng."""
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "'--non-interactive'" in ps1
    assert "--non-interactive" in sh, "install.sh phai NHAC toi co nay (no forward $@)"
    # Va no phai la mot co THAT cua loi, khong phai mot chuoi trang tri:
    assert "--non-interactive" in IS._parser_help()


def test_non_interactive_KHONG_doan_che_do(repo, tmp_path, monkeypatch):
    """`--non-interactive` nghĩa là "đừng hỏi", KHÔNG phải "đoán hộ tôi".

    Chạy trên `repo` GIẢ (chưa có `studio.local.json`): bản clone thật của một máy đã cài
    embedded có sẵn lựa chọn cũ, và `chon_che_do` đọc nó thay vì dừng (P1-8)."""
    for b in IS.BIEN_NHAN_DIEN:
        monkeypatch.delenv(b, raising=False)
    with pytest.raises(IS.SC.ContractError) as e:
        IS.chon_che_do(non_interactive=True)
    assert "chọn chế độ" in str(e.value)
    # nhưng khai rõ thì vẫn chạy, không hỏi ai
    assert IS.chon_che_do(station=str(tmp_path / "t"), non_interactive=True)[0] == "separate"


# ── trạm OpcOS (OPCOS_WORKSPACES) — chỉ đề xuất, không bao giờ tự nhận ────────

@pytest.fixture
def opcos(repo, tmp_path, monkeypatch):
    """Máy có OPCOS_WORKSPACES và `<ws>/marketing` mang dấu trạm."""
    ws = tmp_path / "ws"
    tram = ws / "marketing"
    tram.mkdir(parents=True)
    (tram / SP.SO_KENH).write_text("---\nchannels: []\n---\n", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(ws))
    return tram


def test_mode_separate_mac_dinh_tram_OPCOS_va_ghi_station_path_tuyet_doi(repo, opcos, nha):
    truoc = chup(opcos)
    kq = IS.do_init(mode="separate", ask=khong_duoc_hoi)
    assert kq["mode"] == "separate"
    assert doc_local(repo)["station_path"] == os.path.abspath(opcos)
    assert os.path.isabs(doc_local(repo)["station_path"])
    assert chup(opcos) == truoc, "không tạo thư mục/file nào trong trạm OpcOS"
    assert not (repo / SP.WORKSPACE).exists() and not (nha / NHA_CU).exists()


def test_co_nguoi_ngoi_va_bien_OPCOS_thi_ra_thang_tram_OPCOS_da_mang_dau_khong_hoi(repo, opcos):
    """Trạm OpcOS đã dựng sẵn (mang dấu): dùng luôn, không có bảng chế độ, không dựng thêm gì."""
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "separate"
    assert doc_local(repo)["station_path"] == os.path.abspath(opcos)
    assert not (repo / SP.WORKSPACE).exists()


def test_mode_embedded_ep_embedded_du_co_bien_OPCOS_va_co_nguoi_ngoi(repo, opcos):
    kq = IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert (repo / SP.WORKSPACE).is_dir()
    assert doc_local(repo)["station_path"] == SP.WORKSPACE


def test_yes_voi_bien_OPCOS_van_embedded(repo, opcos):
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert doc_local(repo)["station_path"] == SP.WORKSPACE


def test_mode_embedded_van_duoc_khi_co_bien_OPCOS(repo, opcos):
    kq = IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded" and (repo / SP.WORKSPACE).is_dir()


def test_init_lai_clone_embedded_KHONG_bi_lat(repo, opcos):
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "embedded"}), encoding="utf-8")
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert doc_local(repo)["station_path"] == SP.WORKSPACE


def test_yes_bo_qua_thu_muc_OPCOS_khong_CHANNELS(repo, tmp_path, monkeypatch):
    (tmp_path / "ws" / "marketing").mkdir(parents=True)
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert doc_local(repo)["station_path"] == SP.WORKSPACE
    # có người ngồi thì ra <biến>/marketing sau MỘT câu xác nhận (thư mục chưa mang dấu)
    ask = tra_loi("")
    (repo / SP.LOCAL_CONFIG).unlink()
    kq2 = IS.do_init(ask=ask)
    assert kq2["mode"] == "separate" and len(ask.da_hoi) == 1
    assert "OPCOS_WORKSPACES" in ask.da_hoi[0]
    assert Path(kq2["station"]) == (tmp_path / "ws" / "marketing").resolve()


def test_lan_chon_truoc_separate_khong_station_path_KHONG_ra_tram_OPCOS(repo, opcos, nha):
    """Nhánh `truoc == "separate"` (studio.local.json) đứng TRƯỚC nhánh OpcOS: không station_path
    ⇒ resolve_station() = default (`<repo>/workspaces`), tuyệt đối không nhảy sang trạm OpcOS."""
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "separate"}), encoding="utf-8")
    kq = IS.chon_che_do(ask=khong_duoc_hoi)
    assert kq[0] == "separate"
    assert Path(kq[1]) == SP.resolve_station()[0] == (repo / SP.WORKSPACE).resolve()
    assert Path(kq[1]) != Path(os.path.abspath(opcos))


def test_mode_separate_voi_thu_muc_OPCOS_chua_mang_dau_thi_HOI_xac_nhan_de_xuat(
        repo, tmp_path, nha, monkeypatch):
    (tmp_path / "ws" / "marketing").mkdir(parents=True)          # có thư mục, KHÔNG có CHANNELS.md
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    ask = tra_loi("")                                            # Enter = nhận đề xuất
    mode, st, _ = IS.chon_che_do(mode="separate", ask=ask)
    de_xuat = (tmp_path / "ws" / "marketing").resolve()
    assert mode == "separate" and Path(st) == de_xuat
    assert len(ask.da_hoi) == 1 and str(de_xuat) in ask.da_hoi[0]
    assert not (nha / NHA_CU).exists()


def test_bien_OPCOS_tuong_tac_go_duong_khac_thi_dung_duong_khac(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    khac = tmp_path / "noi-khac"
    mode, st, _ = IS.chon_che_do(mode="separate", ask=tra_loi(str(khac)))
    assert Path(st) == khac.resolve()


def test_bien_OPCOS_khong_tuong_tac_dung_luon_de_xuat_va_in_mot_dong(
        repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    mode, st, ly_do = IS.chon_che_do(mode="separate", non_interactive=True)
    de_xuat = os.path.abspath(tmp_path / "ws" / "marketing")
    assert Path(st) == Path(de_xuat) and os.path.isabs(str(st))
    err = capsys.readouterr().err
    dong = [d for d in err.splitlines() if "OPCOS_WORKSPACES" in d]
    assert len(dong) == 1 and de_xuat in dong[0]


def test_bien_OPCOS_tuong_doi_duoc_tuyet_doi_hoa_cho_de_xuat(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPCOS_WORKSPACES", "ws")
    mode, st, _ = IS.chon_che_do(mode="separate", non_interactive=True)
    assert os.path.isabs(str(st)) and Path(st) == (tmp_path / "ws" / "marketing").resolve()


def test_khong_bien_OPCOS_thi_hoi_duong_va_KHONG_nhac_OPCOS(repo, nha, tmp_path):
    dich = tmp_path / "tram-moi"
    ask = tra_loi("2", str(dich))
    kq = IS.do_init(ask=ask)
    assert all("OPCOS_WORKSPACES" not in b for b in ask.da_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == dich.resolve()
    assert not (nha / NHA_CU).exists()


def test_KHONG_con_chu_thu_muc_nha_kieu_cu_o_ma_test_docs_help_template():
    """Mọi tệp văn bản của repo (trừ CHANGELOG — lịch sử các bản đã phát hành) không còn nhắc
    thư mục ẩn kiểu cũ trong nhà, và không còn mô tả `workspace/` số ít như trạm embedded."""
    import re
    # Mọi dạng ĐƯỜNG tới thư mục ẩn kiểu cũ của ba trạm (nội dung/giọng/video và tts): dạng `~` + `/.x`,
    # `/.x/`, `$HOME/.x`, `%USERPROFILE%` + `\.x`, tên có ngoặc. Class CSS kiểu `.x-embed` không dính.
    ten = "(?:" + "|".join(("voice", "video", "marketing", "tts")) + ")"
    cu = re.compile(r"(?:~[/\\]|\$HOME[/\\]|%USERPROFILE%\\|\$env:USERPROFILE[/\\]|[/\\]|['\"`])\."
                    + ten + r"(?![A-Za-z0-9_-])")
    so_it = re.compile(r"<repo>/workspace(?![s\w])")
    bo_qua = {".git", ".venv", "node_modules", "__pycache__", "workspaces", ".pytest_cache"}
    nhan = {".md", ".py", ".ps1", ".sh", ".json", ".toml", ".yml", ".yaml", ".txt", ".html",
            ".plist", ".example", ".cfg", ""}
    ngoai_le_so_it = {"studio_paths.py", "test_init_both_modes.py", "test_studio_paths.py",
                      "test_migrate_ask.py", "init_station.py", "doctor.py", "brand-paths.ps1",
                      "test_runner_brand_paths.py", "test_gitignore_guard.py", "CHANGELOG.md",
                      "pre_commit_guard.py", "conftest.py", "WORKSPACE.md", "ONBOARDING.md"}
    loi = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in nhan or bo_qua & set(p.relative_to(ROOT).parts):
            continue
        if p.name == "CHANGELOG.md":
            continue
        try:
            t = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        if cu.search(t):
            loi.append(f"{p.relative_to(ROOT)}: chữ thư mục nhà kiểu cũ")
        if p.name not in ngoai_le_so_it and so_it.search(t):
            loi.append(f"{p.relative_to(ROOT)}: còn `workspace/` số ít làm trạm embedded")
    assert not loi, "\n".join(loi)


def test_OPCOS_WORKSPACES_tuong_doi_ghi_station_path_TUYET_DOI_va_resolve_tu_cwd_khac(
        repo, tmp_path, monkeypatch):
    """Biến là đường TƯƠNG ĐỐI (tính theo cwd lúc `init`): `station_path` phải ghi dạng tuyệt đối,
    để chạy lại từ cwd khác (repo, cron) vẫn ra đúng trạm — không trôi theo thư mục hiện hành."""
    tram = tmp_path / "ws" / "marketing"
    tram.mkdir(parents=True)
    (tram / SP.SO_KENH).write_text("---\nchannels: []\n---\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPCOS_WORKSPACES", "ws")
    IS.do_init(mode="separate", ask=khong_duoc_hoi)
    ghi = doc_local(repo)["station_path"]
    assert os.path.isabs(ghi) and Path(ghi) == tram.resolve()
    monkeypatch.chdir(repo)
    assert SP.resolve_station()[0] == tram.resolve()


def test_non_interactive_bang_lua_chon_co_chu_OPCOS_WORKSPACES(repo, opcos, capsys):
    """Agent đọc bảng ở stderr rồi chạy lại với --mode; bảng phải nêu biến + đường trạm."""
    with pytest.raises(SC.ContractError):
        IS.chon_che_do(non_interactive=True)
    err = capsys.readouterr().err
    assert "OPCOS_WORKSPACES" in err and str(opcos) in err

