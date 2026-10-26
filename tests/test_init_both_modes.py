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
    """máy chủ repo: biến đã có từ trước ⇒ không hỏi, và KHÔNG BAO GIỜ tạo workspaces/."""
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
# {bố cục trong repo: không có / `workspaces` / `workspace` cũ / cả hai} × {OPCOS_WORKSPACES: vắng /
# đặt mà `<biến>/marketing` chưa mang dấu / đặt và đã mang dấu} × kịch bản. Kết quả: (chế độ, đích) với
# W = trạm nhúng (`<repo>/workspaces`, hoặc `<repo>/workspace` cũ khi CHỈ có nó), V = <biến>/marketing,
# P = đường người dùng gõ; hoặc "LOI" = mã 2 và chưa ghi gì; "HUY" = Ctrl+C lan ra (biên CLI đổi nó
# thành mã 2). `hoi` = số câu hỏi đã đưa ra (test so BẰNG, không chỉ chặn hỏi thừa); `nhac` = số dòng
# khuyến nghị đổi tên bố cục cũ (chỉ khi kết quả là embedded và còn `workspace` cũ). `TTY` = stdin có
# phải terminal không (mỗi kịch bản khai riêng, không ép chung).
# id test cố định theo tên kịch bản × bố cục × trục biến — chèn dòng không đổi id dòng khác.
#
# Trạm nhúng CŨ CÓ DẤU (bố cục `cu` / `ca-hai`) + có biến + chưa ghi lựa chọn là ca "dữ liệu có sẵn
# thắng biến": `--yes`/không người/EOF giữ trạm cũ (0 câu); có người hỏi đúng MỘT câu giữ/chuyển;
# riêng `ca-hai` (workspace cũ mang dấu, workspaces mới chưa dấu) không hỏi gì và giữ `workspaces`.
# Lựa chọn tường minh (`--mode`) đi TRƯỚC ca này.

W, V, P, LOI, HUY = "W", "V", "P", "LOI", "HUY"
BO_CUC = ["khong", "moi", "cu", "ca-hai"]
BIEN = ["khong", "chua-dau", "da-dau"]
ID_BIEN = {"khong": "khong-bien", "chua-dau": "bien-chua-dau", "da-dau": "bien-da-dau"}
# Kịch bản nào chạy khi stdin LÀ terminal (`--non-interactive` phải thắng nó). Còn lại: không terminal.
TTY = {"ni": True, "ni_yes": True, "mode_separate_ni": True}
# Kịch bản chỉ có nghĩa khi máy đặt biến (câu hỏi ĐƯỜNG không có bảng chế độ đứng trước).
CHI_CO_BIEN = ("go_1", "go_2", "go_embedded", "go_separate", "go_duong")
# Kịch bản bị ca "trạm nhúng cũ có dữ liệu" chi phối khi có biến (không có `--mode`/`--station`).
KHONG_CO_CO = ("Enter", "yes", "ni", "ni_yes", "khong_tty", "eof", "ctrl_c") + CHI_CO_BIEN


def _mong(kich_ban, bo_cuc, bien):
    """-> (kết quả, số câu hỏi, số dòng nhắc đổi tên bố cục cũ)"""
    co_bien = bien != "khong"
    nhac = 1 if bo_cuc in ("cu", "ca-hai") else 0
    if kich_ban in ("2", "3"):                            # chỉ khi KHÔNG có biến (bảng chế độ)
        return (("separate", P), 2, 0) if kich_ban == "2" else (LOI, 1, 0)
    if kich_ban in ("mode_embedded",):
        return ("embedded", W), 0, nhac
    if kich_ban in ("mode_separate_ni", "mode_separate_yes"):
        return (("separate", V) if co_bien else LOI), 0, 0
    if kich_ban == "mode_separate_hoi":
        return ("separate", V if co_bien else P), (0 if bien == "da-dau" else 1), 0
    if co_bien and bo_cuc in ("cu", "ca-hai"):            # trạm nhúng cũ mang dấu, chưa ghi lựa chọn
        if bo_cuc == "ca-hai":                            # chọn thư mục mới rỗng: giữ, không hỏi, nhắc gộp
            return ("embedded", W), 0, 1
        if kich_ban in ("yes", "ni", "ni_yes", "khong_tty"):
            return ("embedded", W), 0, 1
        if kich_ban == "ctrl_c":
            return HUY, 1, 0
        return ("embedded", W), 1, 1                      # Enter · gõ gì khác từ khoá chuyển · EOF = giữ
    # từ đây: không có trạm nhúng cũ mang dấu đi cùng biến
    if kich_ban == "Enter":
        if co_bien:
            return ("separate", V), 1, 0
        return ("embedded", W), 1, nhac
    if kich_ban in ("yes", "ni_yes"):
        return (("separate", V), 0, 0) if co_bien else (("embedded", W), 0, nhac)
    if kich_ban in ("ni", "khong_tty"):
        return (("separate", V), 0, 0) if co_bien else (LOI, 0, 0)
    if kich_ban in ("go_1", "go_2", "go_embedded", "go_separate"):
        return LOI, 1, 0
    if kich_ban == "go_duong":
        return ("separate", P), 1, 0
    if kich_ban == "eof":
        return (("separate", V), 1, 0) if co_bien else (LOI, 1, 0)
    if kich_ban == "ctrl_c":
        return HUY, 1, 0
    raise AssertionError(kich_ban)


KICH_BAN = ["Enter", "2", "3", "yes", "ni", "ni_yes", "khong_tty", "mode_embedded",
            "mode_separate_ni", "mode_separate_yes", "mode_separate_hoi",
            "go_1", "go_2", "go_embedded", "go_separate", "go_duong", "eof", "ctrl_c"]


def _to_hop():
    for kb in KICH_BAN:
        for bc in BO_CUC:
            for bien in BIEN:
                if kb in ("2", "3") and bien != "khong":
                    continue
                if kb in CHI_CO_BIEN and bien == "khong":
                    continue
                yield pytest.param(kb, bc, bien, id=f"{kb}-{bc}-{ID_BIEN[bien]}")


def hoi_roi_ngat(ngoai_le):
    """Người dùng giả mà câu trả lời là một ngoại lệ (EOF khi stdin hết dữ liệu, Ctrl+C); vẫn ghi lại
    câu hỏi đã nhận để test đếm được."""
    da_hoi = []

    def ask(bang):
        da_hoi.append(bang)
        raise ngoai_le
    ask.da_hoi = da_hoi
    return ask


@pytest.mark.parametrize("kich_ban,bo_cuc,bien", list(_to_hop()))
def test_bang_hanh_vi_chung(kich_ban, bo_cuc, bien, repo, nha, tmp_path, monkeypatch, capsys):
    if bo_cuc in ("moi", "ca-hai"):
        (repo / "workspaces").mkdir()
    cu = tao_bo_cuc_cu(repo) if bo_cuc in ("cu", "ca-hai") else None
    co_bien = bien != "khong"
    if co_bien:
        monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    if bien == "da-dau":
        (tmp_path / "ws" / "marketing").mkdir(parents=True)
        (tmp_path / "ws" / "marketing" / SP.SO_KENH).write_text(
            "---\nchannels: []\n---\n", encoding="utf-8")
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: TTY.get(kich_ban, False))
    duong_go = tmp_path / "tram-go"
    nhung = cu if bo_cuc == "cu" else (repo / "workspaces")
    moc = {W: nhung.resolve(), V: (tmp_path / "ws" / "marketing").resolve(), P: duong_go.resolve()}
    # câu trả lời chuẩn bị sẵn; câu hỏi đường: có biến thì Enter (nhận đề xuất), không thì gõ P
    cau_duong = "" if co_bien else str(duong_go)
    kw, tra, ask = {}, [], None
    if kich_ban == "Enter":
        tra = [""]
    elif kich_ban == "2":
        tra = ["2", cau_duong]
    elif kich_ban == "3":
        tra = ["3"]
    elif kich_ban in ("go_1", "go_2", "go_embedded", "go_separate"):
        tra = [kich_ban[3:]]
    elif kich_ban == "go_duong":
        tra = [str(duong_go)]
    elif kich_ban == "eof":
        ask = hoi_roi_ngat(EOFError())
    elif kich_ban == "ctrl_c":
        ask = hoi_roi_ngat(KeyboardInterrupt())
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
    # `khong_tty`: không ask, không cờ, stdin không phải terminal
    if tra:
        ask = tra_loi(*tra)
    if ask:
        kw["ask"] = ask
    mong, hoi, nhac = _mong(kich_ban, bo_cuc, bien)
    truoc = chup(repo)
    if mong == LOI:
        with pytest.raises(SC.ContractError):
            IS.chon_che_do(**kw)
        assert chup(repo) == truoc
    elif mong == HUY:
        with pytest.raises(KeyboardInterrupt):
            IS.chon_che_do(**kw)
        assert chup(repo) == truoc
    else:
        try:
            mode, st, _ = IS.chon_che_do(**kw)
        except KeyboardInterrupt:       # một Ctrl+C giả lọt ra ở chỗ không được hỏi không được làm sập phiên pytest
            pytest.fail("hỏi ở chỗ bảng quy định KHÔNG hỏi (Ctrl+C giả lan ra)")
        assert (mode, Path(st)) == (mong[0], moc[mong[1]]), (mode, st)
    assert (len(ask.da_hoi) if ask else 0) == hoi
    dong = [d for d in capsys.readouterr().err.splitlines()
            if "[init]" in d and "workspace" in d and ("đổi tên" in d or "bố cục cũ" in d)]
    assert len(dong) == nhac, dong
    if ask and kich_ban == "2":                          # bảng chế độ nêu đúng đường embedded
        assert "<repo>/workspaces/" in ask.da_hoi[0] and "workspaces/marketing" not in ask.da_hoi[0]


def _khoi_changelog_hien_hanh() -> str:
    """Khối CHANGELOG nói về hành vi hiện hành của bộ cài: `### Chưa phát hành` khi còn; khi đã phát
    hành (khối đó thành mục của bản mới, không còn tiêu đề ấy) thì các bullet của mục `##` MỚI NHẤT
    có nói tới bộ cài (`--station <đường>`) — không phải mục đầu tiên: bản phát hành sau không đụng bộ cài
    (ví dụ 3.1.0 dọn dữ liệu riêng) đứng trên, và khối của bộ cài vẫn là khối hiện hành của nó."""
    import re
    t = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    dau = t.find("### Chưa phát hành")
    if dau < 0:
        muc = [m.start() for m in re.finditer(r"^## ", t, re.M)]
        co_bo_cai = [a for a, b in zip(muc, muc[1:] + [len(t)]) if "`--station <đường>`" in t[a:b]]
        dau = co_bo_cai[0] if co_bo_cai else muc[0]
        bullet = re.compile(r"^- ", re.M).search(t, dau)        # bỏ tiêu đề mục và đoạn dẫn
        dau = bullet.start() if bullet else dau
    cuoi = re.compile(r"^## ", re.M).search(t, dau + 4)
    return t[dau:cuoi.start() if cuoi else len(t)]


def test_changelog_chua_phat_hanh_noi_dung_cach_dung_bo_cuc_moi_va_ca_exit_2():
    khoi = _khoi_changelog_hien_hanh()
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


def test_co_nguoi_ngoi_va_bien_OPCOS_da_mang_dau_thi_VAN_hoi_dung_mot_cau_xac_nhan(repo, opcos):
    """Trạm OpcOS đã mang dấu: vẫn hỏi ĐÚNG MỘT câu nhận đường (như voice), Enter = trạm đó; không
    có bảng chế độ, không dựng thêm gì."""
    truoc = chup(opcos)
    ask = tra_loi("")
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "separate" and len(ask.da_hoi) == 1
    assert str(opcos) in ask.da_hoi[0] and "OPCOS_WORKSPACES" in ask.da_hoi[0]
    assert doc_local(repo)["station_path"] == os.path.abspath(opcos)
    assert not (repo / SP.WORKSPACE).exists()
    assert chup(opcos) >= truoc


def test_mode_embedded_ep_embedded_du_co_bien_OPCOS_va_co_nguoi_ngoi(repo, opcos):
    kq = IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert (repo / SP.WORKSPACE).is_dir()
    assert doc_local(repo)["station_path"] == SP.WORKSPACE


def test_yes_voi_bien_OPCOS_ra_tram_OPCOS_khong_hoi_va_khong_dung_workspaces_trong_repo(repo, opcos):
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == opcos.resolve()
    assert doc_local(repo)["station_path"] == os.path.abspath(opcos)
    assert not (repo / SP.WORKSPACE).exists()


def test_mode_embedded_van_duoc_khi_co_bien_OPCOS(repo, opcos):
    kq = IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded" and (repo / SP.WORKSPACE).is_dir()


def test_init_lai_clone_embedded_KHONG_bi_lat(repo, opcos):
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "embedded"}), encoding="utf-8")
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert doc_local(repo)["station_path"] == SP.WORKSPACE


def test_yes_voi_thu_muc_OPCOS_chua_mang_dau_dung_moi_trong_do_va_co_nguoi_thi_hoi_mot_cau(
        repo, tmp_path, monkeypatch, capsys):
    (tmp_path / "ws" / "marketing").mkdir(parents=True)
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == (tmp_path / "ws" / "marketing").resolve()
    cay_tram_ok(tmp_path / "ws" / "marketing")
    assert not (repo / SP.WORKSPACE).exists()
    assert len([d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]) == 1
    # có người ngồi thì ra <biến>/marketing sau MỘT câu xác nhận (thư mục đã mang dấu sau lần dựng trên)
    ask = tra_loi("")
    (repo / SP.LOCAL_CONFIG).unlink()
    kq2 = IS.do_init(ask=ask)
    assert kq2["mode"] == "separate" and len(ask.da_hoi) == 1
    assert "OPCOS_WORKSPACES" in ask.da_hoi[0]
    assert Path(kq2["station"]) == (tmp_path / "ws" / "marketing").resolve()


@pytest.mark.parametrize("cach", ["yes", "Enter", "ni", "khong_tty"])
@pytest.mark.parametrize("bien", ["khong", "chua-dau", "da-dau"])
def test_lan_chon_truoc_separate_thieu_station_path_la_ma_2_nhac_station_va_khong_hoi(
        cach, bien, repo, tmp_path, monkeypatch, nha):
    """Bản ghi `separate` mà thiếu `station_path` là bản ghi HỎNG: không đoán trạm OpcOS, không rơi về
    `<repo>/workspaces` — mã 2, 0 câu, nêu `--station` (như voice `NEED_STATION`). Mọi cách gọi, có hay
    không có biến."""
    if bien != "khong":
        monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    if bien == "da-dau":
        (tmp_path / "ws" / "marketing").mkdir(parents=True)
        (tmp_path / "ws" / "marketing" / SP.SO_KENH).write_text(
            "---\nchannels: []\n---\n", encoding="utf-8")
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "separate"}), encoding="utf-8")
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(ask=khong_duoc_hoi) if cach == "Enter" else dict(non_interactive=True) if cach == "ni" else {}
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: cach == "Enter")
    truoc = chup(repo, nha)
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(**kw)
    assert chup(repo, nha) == truoc


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


def test_doctor_KHONG_canh_bao_tram_OPCOS_khi_nguoi_dung_da_chon_embedded(repo, opcos):
    """Sau khi tên nhúng đi qua bộ phân giải nhúng, nguồn không còn là `studio.local.json`; phải nhìn
    CHẾ ĐỘ đã chọn. Chưa chọn gì thì vẫn nhắc."""
    nhac = lambda kq: [w for w in kq["warn"] if "trạm OpcOS" in w]       # noqa: E731
    (repo / "workspaces").mkdir()
    assert nhac(DR.kham()), "chưa chọn chế độ: vẫn phải nhắc có trạm OpcOS"
    IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert doc_local(repo)["mode"] == "embedded"
    assert not nhac(DR.kham())


def test_cau_chung_du_lieu_cu_o_noi_khac_co_trong_moi_thong_bao_ma_3(repo, tmp_path, monkeypatch):
    cau = SC.GOI_Y_DU_LIEU_CU
    assert "--station" in cau and "dữ liệu cũ" in cau
    assert ("." + "marketing") not in cau and "~/." not in cau, "không nêu tên thư mục ẩn nào"
    # doctor: chưa có trạm
    kq = DR.kham()
    assert kq["code"] == SC.STATION_MISSING and any(cau in x for x in kq["fail"]), kq
    # backup, init --existing, runner paths.station()
    import studio as ST
    with pytest.raises(SC.StationMissing, match="Có dữ liệu cũ"):
        ST.backup(str(tmp_path / "x.zip"))
    with pytest.raises(SC.StationMissing, match="Có dữ liệu cũ"):
        IS.do_init(station=str(tmp_path / "khong-co"), existing=True)
    import importlib.util
    spec = importlib.util.spec_from_file_location("paths_runner", ROOT / "scripts" / "runners" / "paths.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.delenv("MARKETING_STUDIO_DATA", raising=False)
    (repo / SP.LOCAL_CONFIG).unlink(missing_ok=True)
    shutil.rmtree(repo / SP.WORKSPACE, ignore_errors=True)
    with pytest.raises(SC.StationMissing, match="Có dữ liệu cũ") as e:
        m.station()
    assert SC.GOI_Y_DU_LIEU_CU in str(e.value)
    # PowerShell: cùng ý (ASCII, không dấu)
    ps = (ROOT / "scripts" / "runners" / "brand-paths.ps1").read_text(encoding="utf-8-sig")
    assert "Co du lieu cu o noi khac? Dung --station" in ps


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
    loi, da_quet = [], 0
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in nhan or bo_qua & set(p.relative_to(ROOT).parts):
            continue
        try:
            t = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        if p.name == "CHANGELOG.md":
            # Các bản ĐÃ phát hành là lịch sử, giữ nguyên chữ; riêng khối chưa phát hành là luật hiện hành.
            if p != ROOT / "CHANGELOG.md":
                continue
            t = _khoi_changelog_hien_hanh()
        da_quet += 1
        if cu.search(t):
            loi.append(f"{p.relative_to(ROOT)}: chữ thư mục nhà kiểu cũ")
        if p.name not in ngoai_le_so_it and so_it.search(t):
            loi.append(f"{p.relative_to(ROOT)}: còn `workspace/` số ít làm trạm embedded")
    assert da_quet > 150, f"chỉ quét {da_quet} tệp - bộ lọc đang nuốt cả repo, test này không còn bảo vệ gì"
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


def test_non_interactive_voi_bien_OPCOS_ra_tram_OPCOS_va_in_mot_dong_nen_ca_bien_lan_duong(
        repo, tmp_path, monkeypatch, capsys):
    """Không có ai trả lời mà máy đặt biến (trạm OpcOS chưa dựng): KHÔNG mã 2 — trạm OpcOS, và một dòng
    nêu biến + đường cùng cách đổi (`--station <đường>`)."""
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    mode, st, _ = IS.chon_che_do(non_interactive=True)
    de_xuat = os.path.abspath(tmp_path / "ws" / "marketing")
    assert mode == "separate" and Path(st) == Path(de_xuat)
    dong = [d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]
    assert len(dong) == 1 and de_xuat in dong[0] and "--station" in dong[0]



# ══ Trạm nhúng CŨ CÓ DẤU + có OPCOS_WORKSPACES + chưa ghi lựa chọn: dữ liệu có sẵn THẮNG biến ═══
# `--yes`/không người/EOF giữ trạm cũ và ghi `mode: embedded`; có người hỏi MỘT câu giữ/chuyển; chọn
# chuyển thì HÀM CHỌN CHẾ ĐỘ KHÔNG DỜI GÌ (chỉ trả cờ `then_migrate`) — `do_init` mới ghi embedded rồi xin
# `y/N` của `migrate` (2 câu). Không bao giờ dựng một trạm OpcOS rỗng cạnh dữ liệu cũ.

def tram_nhung_co_du_lieu(repo: Path, ten: str = "workspaces") -> Path:
    d = repo / ten
    d.mkdir()
    (d / SP.SO_KENH).write_text("---\nchannels: []\n---\n# cua toi\n", encoding="utf-8")
    (d / "kenh-a").mkdir()
    (d / "kenh-a" / "bai.md").write_text("noi dung quan trong\n", encoding="utf-8")
    return d


def bam_cay(goc: Path) -> dict:
    import hashlib
    ra = {}
    for dp, _dn, fn in os.walk(goc):
        for n in fn:
            f = Path(dp) / n
            ra[f.relative_to(goc).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return ra


@pytest.fixture
def oc_ws(repo, tmp_path, monkeypatch):
    """Máy đặt OPCOS_WORKSPACES; `<ws>/marketing` CHƯA tồn tại."""
    ws = tmp_path / "ws"
    monkeypatch.setenv("OPCOS_WORKSPACES", str(ws))
    return ws


def dich_oc(oc_ws: Path) -> str:
    return os.path.abspath(oc_ws / "marketing")


def tra_roi_ngat(cau, ngoai_le):
    """Trả lời `cau`, rồi câu kế tiếp nhận `ngoai_le` (EOF / Ctrl+C)."""
    con = [cau]
    da_hoi = []

    def ask(bang):
        da_hoi.append(bang)
        if con:
            return con.pop(0)
        raise ngoai_le
    ask.da_hoi = da_hoi
    return ask


@pytest.mark.parametrize("bo_cuc", ["moi", "cu"])
@pytest.mark.parametrize("cach", ["yes", "ni", "khong_tty", "ni_yes"])
def test_khong_nguoi_hoac_yes_thi_GIU_tram_cu_ghi_embedded_va_in_mot_dong_chi_migrate(
        cach, bo_cuc, repo, oc_ws, capsys, monkeypatch):
    cu = tram_nhung_co_du_lieu(repo, "workspaces" if bo_cuc == "moi" else SP.WORKSPACE_CU)
    truoc = bam_cay(cu)
    kw = {"yes": dict(yes=True, ask=khong_duoc_hoi), "ni": dict(non_interactive=True),
          "khong_tty": {}, "ni_yes": dict(non_interactive=True, yes=True)}[cach]
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: cach == "ni")
    kq = IS.do_init(**kw)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == cu.resolve() and kq["then_migrate"] is None
    assert doc_local(repo)["mode"] == "embedded"
    assert not (oc_ws / "marketing").exists(), "không bao giờ dựng trạm OpcOS rỗng cạnh dữ liệu cũ"
    assert all(bam_cay(cu).get(r) == h for r, h in truoc.items()), "dữ liệu cũ phải còn nguyên"
    dong = [d for d in capsys.readouterr().err.splitlines() if "migrate --to separate" in d]
    assert len(dong) == 1, dong
    assert str(cu.resolve()) in dong[0] and dich_oc(oc_ws) in dong[0] and dong[0].startswith("[init]")


def test_init_lan_hai_sau_khi_giu_thi_khong_hoi_va_khong_nhac_migrate(repo, oc_ws, capsys):
    tram_nhung_co_du_lieu(repo)
    IS.do_init(yes=True)
    capsys.readouterr()
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert "migrate --to separate" not in capsys.readouterr().err


def test_co_nguoi_Enter_hoac_chu_khac_thi_giu_voi_dung_mot_cau_nen_duong_tram_cu(repo, oc_ws):
    cu = tram_nhung_co_du_lieu(repo)
    for tra in ("", "khong", "1", "separate"):
        ask = tra_loi(tra)
        mode, st, _ = IS.chon_che_do(ask=ask)
        assert (mode, Path(st)) == ("embedded", cu.resolve()) and len(ask.da_hoi) == 1, tra
    assert str(cu.resolve()) in ask.da_hoi[0] and "chuyen" in ask.da_hoi[0]
    assert dich_oc(oc_ws) in ask.da_hoi[0]


@pytest.mark.parametrize("tu", ["chuyen", "chuyển", "c", "CHUYEN", " Chuyen "])
def test_chon_chuyen_thi_ham_chon_che_do_tra_co_then_migrate_va_KHONG_doi_byte_nao(
        tu, repo, oc_ws, nha):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = chup(repo, nha)
    h = bam_cay(cu)
    ask = tra_loi(tu)
    ch = IS.chon_che_do(ask=ask)
    mode, st, _ = ch                       # vẫn unpack được 3 giá trị như cũ
    assert (mode, Path(st)) == ("embedded", cu.resolve())
    assert ch.then_migrate == dich_oc(oc_ws) and len(ask.da_hoi) == 1
    assert chup(repo, nha) == truoc and bam_cay(cu) == h and not oc_ws.exists()
    assert not (repo / SP.LOCAL_CONFIG).exists(), "chưa ghi gì ở bước chọn"


def test_EOF_o_cau_giu_chuyen_la_giu_ma_0_KHONG_ra_tram_OPCOS(repo, oc_ws):
    cu = tram_nhung_co_du_lieu(repo)
    ask = hoi_roi_ngat(EOFError())
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == cu.resolve() and len(ask.da_hoi) == 1
    assert not (oc_ws / "marketing").exists()


def test_CtrlC_o_cau_giu_chuyen_lan_ra_va_chua_ghi_gi(repo, oc_ws, nha):
    tram_nhung_co_du_lieu(repo)
    truoc = chup(repo, nha)
    with pytest.raises(KeyboardInterrupt):
        IS.do_init(ask=hoi_roi_ngat(KeyboardInterrupt()))
    assert chup(repo, nha) == truoc and not (repo / SP.LOCAL_CONFIG).exists()


def test_both_moi_chua_dau_thi_giu_workspaces_khong_hoi_nhac_gop_khong_dong_migrate(
        repo, oc_ws, capsys):
    tram_nhung_co_du_lieu(repo, SP.WORKSPACE_CU)
    (repo / "workspaces").mkdir()
    for kw in (dict(yes=True, ask=khong_duoc_hoi), dict(ask=khong_duoc_hoi), dict(non_interactive=True)):
        (repo / SP.LOCAL_CONFIG).unlink(missing_ok=True)
        shutil.rmtree(repo / "workspaces")             # mỗi vòng lại là `workspaces` MỚI, CHƯA dấu
        (repo / "workspaces").mkdir()
        kq = IS.do_init(**kw)
        assert kq["mode"] == "embedded" and Path(kq["station"]) == (repo / "workspaces").resolve()
        assert kq["then_migrate"] is None and doc_local(repo)["mode"] == "embedded"
        err = capsys.readouterr().err
        assert "migrate --to separate" not in err and "bố cục cũ" in err
    assert not (oc_ws / "marketing").exists()
    assert (repo / SP.WORKSPACE_CU / "kenh-a" / "bai.md").is_file(), "dữ liệu ở workspace/ không mồ côi bị dời"


def test_hai_tram_cung_mang_dau_thi_giu_noi_hai_tram_va_KHONG_goi_y_migrate(
        repo, oc_ws, capsys):
    cu = tram_nhung_co_du_lieu(repo)
    (oc_ws / "marketing").mkdir(parents=True)
    (oc_ws / "marketing" / SP.SO_KENH).write_text("---\nchannels: []\n---\n", encoding="utf-8")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == cu.resolve()
    dong = [d for d in capsys.readouterr().err.splitlines() if "hai trạm" in d]
    assert len(dong) == 1 and str(cu.resolve()) in dong[0] and dich_oc(oc_ws) in dong[0]
    assert "--station" in dong[0] and "migrate --to separate" not in dong[0]


def test_chon_chuyen_roi_y_thi_doi_that_ghi_separate_va_moi_file_con_nguyen_hash(
        repo, oc_ws, nha):
    cu = tram_nhung_co_du_lieu(repo)
    (repo / ".env").write_text("CUA_TOI=1\n", encoding="utf-8")
    truoc = bam_cay(cu)
    ask = tra_loi("chuyen", "y")
    kq = IS.do_init(ask=ask)
    dich = oc_ws / "marketing"
    assert len(ask.da_hoi) == 2 and "[y/N]" in ask.da_hoi[1] and dich_oc(oc_ws) in ask.da_hoi[1]
    assert kq["mode"] == "separate" and Path(kq["station"]) == dich.resolve()
    sau = bam_cay(dich)
    assert all(sau.get(r) == h for r, h in truoc.items()), "mọi file phải sang đích nguyên hash"
    assert not cu.exists(), "nguồn đã dời"
    lc = doc_local(repo)
    assert lc["mode"] == "separate" and Path(lc["station_path"]) == dich.resolve()
    assert (nha / ".secret" / "marketing-studio" / ".env").is_file(), ".env sang kho secret DƯỚI HOME giả"


@pytest.mark.parametrize("tra_loi_yn", ["n", "", "N", "khong"])
def test_chon_chuyen_roi_tra_loi_khong_o_y_N_thi_giu_ma_0_va_chi_lenh_migrate(
        tra_loi_yn, repo, oc_ws, capsys):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = bam_cay(cu)
    ask = tra_loi("chuyen", tra_loi_yn)
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == cu.resolve()
    assert len(ask.da_hoi) == 2, "chuyển + xác nhận y/N phải gọi đúng hai prompt"
    assert doc_local(repo)["mode"] == "embedded"
    assert all(bam_cay(cu)[r] == h for r, h in truoc.items()) and not (oc_ws / "marketing").exists()
    assert len([d for d in capsys.readouterr().err.splitlines() if "migrate --to separate" in d]) == 1


def test_chon_chuyen_roi_EOF_o_y_N_thi_giu_ma_0(repo, oc_ws):
    cu = tram_nhung_co_du_lieu(repo)
    ask = tra_roi_ngat("chuyen", EOFError())
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "embedded" and cu.is_dir() and not (oc_ws / "marketing").exists()
    assert len(ask.da_hoi) == 2, "EOF tại xác nhận vẫn là prompt thứ hai đã được gọi"


def test_chon_chuyen_roi_CtrlC_o_y_N_lan_ra_embedded_da_ghi_va_khong_doi_byte(repo, oc_ws):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = bam_cay(cu)
    with pytest.raises(KeyboardInterrupt):
        IS.do_init(ask=tra_roi_ngat("chuyen", KeyboardInterrupt()))
    assert doc_local(repo)["mode"] == "embedded" and cu.is_dir()
    assert all(bam_cay(cu)[r] == h for r, h in truoc.items()) and not (oc_ws / "marketing").exists()


@pytest.mark.parametrize("dich_co", ["file-la", "da-dau"])
def test_chon_chuyen_nhung_dich_khong_rong_thi_ma_2_TRUOC_y_N_va_embedded_van_dung_duoc(
        dich_co, repo, oc_ws):
    cu = tram_nhung_co_du_lieu(repo)
    d = oc_ws / "marketing"
    d.mkdir(parents=True)
    (d / ("x.txt" if dich_co == "file-la" else SP.SO_KENH)).write_text("co san\n", encoding="utf-8")
    truoc_dich = bam_cay(d)
    ask = tra_loi("chuyen")                      # chỉ MỘT câu: y/N không bao giờ được hỏi
    with pytest.raises(SC.ContractError, match="không rỗng"):
        IS.do_init(ask=ask)
    assert len(ask.da_hoi) == 1
    assert doc_local(repo)["mode"] == "embedded" and (cu / "kenh-a" / "bai.md").is_file()
    assert bam_cay(d) == truoc_dich, "mọi byte ở đích không rỗng phải giữ nguyên"


def test_dry_run_cung_chuyen_chi_in_se_doi_va_khong_ghi_byte_nao(repo, oc_ws, nha, capsys):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = chup(repo, nha)
    h = bam_cay(cu)
    ask = tra_loi("chuyen")
    kq = IS.do_init(dry_run=True, ask=ask)
    assert len(ask.da_hoi) == 1 and kq["dry_run"] is True and kq["then_migrate"] == dich_oc(oc_ws)
    assert chup(repo, nha) == truoc and bam_cay(cu) == h
    assert not (repo / SP.LOCAL_CONFIG).exists() and not oc_ws.exists()
    IS._in(kq)
    err = capsys.readouterr().err
    assert "sẽ dời" in err and str(cu.resolve()) in err and dich_oc(oc_ws) in err


def test_dry_run_voi_yes_in_ke_hoach_giu_va_khong_ghi_gi(repo, oc_ws, nha):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = chup(repo, nha)
    kq = IS.do_init(yes=True, dry_run=True)
    assert kq["mode"] == "embedded" and chup(repo, nha) == truoc and not (repo / SP.LOCAL_CONFIG).exists()


def test_luat_uu_tien_mode_separate_thang_tram_cu_va_van_dung_tram_OPCOS(repo, oc_ws):
    """Lựa chọn tường minh đi TRƯỚC ca này (khoá để không ai 'sửa' thứ tự)."""
    tram_nhung_co_du_lieu(repo)
    kq = IS.do_init(mode="separate", yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == (oc_ws / "marketing").resolve()


def test_lua_chon_da_ghi_thang_ca_nay_khong_in_dong_migrate(repo, oc_ws, capsys):
    tram_nhung_co_du_lieu(repo)
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "embedded"}), encoding="utf-8")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded"
    assert "migrate --to separate" not in capsys.readouterr().err


# ── biến TRẠM RIÊNG và biến ANH EM giao với ca trạm cũ ───────────────────────

@pytest.mark.parametrize("cach", ["yes", "Enter"])
@pytest.mark.parametrize("bien", ["VOICE_STATION", "VIDEO_STATION", "OMNIVOICE_DIR", "VIDEO_ROOT"])
def test_bien_anh_em_va_OPCOS_va_tram_nhung_mang_dau_thi_du_lieu_co_san_THANG_nhanh_bien_anh_em(
        bien, cach, repo, oc_ws, tmp_path, monkeypatch):
    cu = tram_nhung_co_du_lieu(repo)
    monkeypatch.setenv(bien, str(tmp_path))
    ask = khong_duoc_hoi if cach == "yes" else tra_loi("")
    kq = IS.do_init(yes=(cach == "yes"), ask=ask)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == cu.resolve()
    assert cach == "yes" or len(ask.da_hoi) == 1
    assert not (oc_ws / "marketing").exists()


def test_bien_anh_em_KHONG_co_OPCOS_thi_van_ma_2_du_co_tram_nhung_mang_dau_khong_doi(
        repo, tmp_path, monkeypatch):
    tram_nhung_co_du_lieu(repo)
    monkeypatch.setenv("VOICE_STATION", str(tmp_path))
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(yes=True, ask=khong_duoc_hoi)
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(non_interactive=True)


def test_bien_anh_em_va_OPCOS_khong_co_tram_nhung_thi_ra_tram_OPCOS_dung_mot_cau_khi_co_nguoi(
        repo, oc_ws, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_STATION", str(tmp_path))
    ask = tra_loi("")
    kq = IS.do_init(ask=ask)
    assert Path(kq["station"]) == (oc_ws / "marketing").resolve() and len(ask.da_hoi) == 1


@pytest.mark.parametrize("cach", ["yes", "Enter", "ni"])
def test_bien_tram_rieng_MARKETING_STUDIO_DATA_thang_ca_tram_cu_va_OPCOS(
        cach, repo, oc_ws, tmp_path, monkeypatch):
    tram_nhung_co_du_lieu(repo)
    ngoai = tmp_path / "tram-rieng"
    ngoai.mkdir()
    monkeypatch.setenv("MARKETING_STUDIO_DATA", str(ngoai))
    ws_invalid = tmp_path / "opcos-not-a-directory"
    ws_invalid.write_text("untouched\n", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(ws_invalid))
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(ask=khong_duoc_hoi) if cach == "Enter" else dict(non_interactive=True)
    kq = IS.do_init(**kw)
    assert kq["mode"] == "separate" and Path(kq["station"]) == ngoai.resolve()
    assert ws_invalid.read_text(encoding="utf-8") == "untouched\n"
    assert not (ws_invalid / "marketing").exists()


@pytest.mark.parametrize("cach", ["yes", "ni", "Enter"])
def test_lua_chon_da_ghi_embedded_thang_bien_OPCOS_khong_hoi_lai(cach, repo, oc_ws):
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "embedded"}), encoding="utf-8")
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(ask=khong_duoc_hoi) if cach == "Enter" else dict(non_interactive=True)
    kq = IS.do_init(**kw)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == (repo / "workspaces").resolve()
    assert not (oc_ws / "marketing").exists()


def test_lua_chon_da_ghi_separate_co_station_path_thang_bien_OPCOS(repo, oc_ws, tmp_path):
    rieng = tmp_path / "rieng"
    (repo / SP.LOCAL_CONFIG).write_text(
        json.dumps({"mode": "separate", "station_path": str(rieng)}), encoding="utf-8")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == rieng.resolve()
    assert not (oc_ws / "marketing").exists()


# ── ra trạm OpcOS, một câu, EOF, lựa chọn trần ───────────────

@pytest.mark.parametrize("cach", ["yes", "ni", "khong_tty", "ni_yes"])
def test_yes_va_khong_nguoi_voi_bien_ra_tram_OPCOS_dung_moi_va_in_mot_dong(
        cach, repo, oc_ws, capsys, monkeypatch):
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: cach == "ni")
    kw = {"yes": dict(yes=True, ask=khong_duoc_hoi), "ni": dict(non_interactive=True),
          "khong_tty": {}, "ni_yes": dict(non_interactive=True, yes=True)}[cach]
    kq = IS.do_init(**kw)
    dich = oc_ws / "marketing"
    assert kq["mode"] == "separate" and Path(kq["station"]) == dich.resolve()
    cay_tram_ok(dich)
    assert not (repo / "workspaces").exists()
    assert Path(doc_local(repo)["station_path"]) == dich.resolve()
    dong = [d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]
    assert len(dong) == 1 and dich_oc(oc_ws) in dong[0] and "--station" in dong[0]


def test_tram_OPCOS_da_mang_dau_thi_dung_thang_khong_dong_nao_khong_dung_them_gi(
        repo, opcos, capsys):
    truoc = chup(opcos)
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == opcos.resolve()
    assert chup(opcos) == truoc
    assert not [d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]


def test_EOF_o_cau_duong_khi_co_bien_ra_tram_OPCOS_ma_0_va_in_mot_dong(repo, oc_ws, capsys):
    ask = hoi_roi_ngat(EOFError())
    kq = IS.do_init(ask=ask)
    assert kq["mode"] == "separate" and Path(kq["station"]) == (oc_ws / "marketing").resolve()
    assert len(ask.da_hoi) == 1
    assert len([d for d in capsys.readouterr().err.splitlines() if "OPCOS_WORKSPACES" in d]) >= 1


@pytest.mark.parametrize("go", ["1", "2", "embedded", "separate", "EMBEDDED"])
def test_go_lua_chon_tran_o_cau_duong_la_ma_2_nen_mode_embedded_va_KHONG_tao_thu_muc_la(
        go, repo, oc_ws, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    truoc = chup(repo, tmp_path)
    with pytest.raises(SC.ContractError, match="--mode embedded"):
        IS.do_init(ask=tra_loi(go))
    assert chup(repo, tmp_path) == truoc and not (tmp_path / go).exists()


@pytest.mark.parametrize("bao", ['"{}"', "'{}'", ' "{}" '])
def test_go_duong_khac_o_cau_duong_co_bien_dung_duong_do_khong_dung_tram_OPCOS(
        bao, repo, oc_ws, tmp_path):
    dich = tmp_path / "tram co dau cach"
    ask = tra_loi(bao.format(dich))
    kq = IS.do_init(ask=ask)
    assert Path(kq["station"]) == dich.resolve() and len(ask.da_hoi) == 1 and dich.is_dir()
    assert not (oc_ws / "marketing").exists()


def test_go_duong_tuong_doi_o_cau_duong_co_bien_ghi_tuyet_doi(repo, oc_ws, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    kq = IS.do_init(ask=tra_loi("noi-tuong-doi"))
    assert Path(kq["station"]) == (tmp_path / "noi-tuong-doi").resolve()
    assert os.path.isabs(doc_local(repo)["station_path"])


def test_go_duong_la_mot_FILE_o_cau_duong_co_bien_la_ma_2_chua_ghi_gi(repo, oc_ws, tmp_path):
    f = tmp_path / "la-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SC.ContractError):
        IS.do_init(ask=tra_loi(str(f)))
    assert not (repo / SP.LOCAL_CONFIG).exists()


def test_mode_separate_chua_dau_co_nguoi_hoi_mot_cau_con_da_dau_thi_dung_thang(repo, oc_ws):
    ask = tra_loi("")
    IS.do_init(mode="separate", ask=ask)
    assert len(ask.da_hoi) == 1
    (repo / SP.LOCAL_CONFIG).unlink()
    ask2 = khong_duoc_hoi                    # trạm đã mang dấu sau lần dựng trên
    kq = IS.do_init(mode="separate", ask=ask2)
    assert Path(kq["station"]) == (oc_ws / "marketing").resolve()


# ── giá trị OPCOS_WORKSPACES lệch ───────────────────────────────────────────────────

@pytest.mark.parametrize("gia_tri", ["", "   "])
def test_bien_rong_hoac_khoang_trang_coi_nhu_vang_giu_embedded(gia_tri, repo, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", gia_tri)
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "embedded" and Path(kq["station"]) == (repo / "workspaces").resolve()


def test_bien_tuong_doi_thi_ra_tuyet_doi_theo_cwd_va_ghi_tuyet_doi(
        repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPCOS_WORKSPACES", "relws")
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    dich = (tmp_path / "relws" / "marketing").resolve()
    assert Path(kq["station"]) == dich and os.path.isabs(kq["station"])
    assert Path(doc_local(repo)["station_path"]) == dich


@pytest.mark.parametrize("cach", ["yes", "Enter", "ni"])
@pytest.mark.parametrize("hinh", ["bien-la-file", "tram-la-file"])
def test_bien_tro_vao_FILE_la_ma_2_nen_TEN_BIEN_va_chua_ghi_gi(
        hinh, cach, repo, tmp_path, monkeypatch, nha):
    if hinh == "bien-la-file":
        f = tmp_path / "la-file"
        f.write_text("x", encoding="utf-8")
        monkeypatch.setenv("OPCOS_WORKSPACES", str(f))
    else:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "marketing").write_text("x", encoding="utf-8")
        monkeypatch.setenv("OPCOS_WORKSPACES", str(ws))
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(ask=tra_loi("")) if cach == "Enter" else dict(non_interactive=True)
    truoc = chup(repo, nha)
    with pytest.raises(SC.ContractError, match="OPCOS_WORKSPACES"):
        IS.do_init(**kw)
    assert chup(repo, nha) == truoc and not (repo / SP.LOCAL_CONFIG).exists()


# Pinned as current behaviour, not a contract: ba ca dưới ghi lại hành vi hiện tại (dựng, không chặn, không
# xoá gì, mã 0) khi biến trỏ chỗ lạ. Chặn hay giữ là quyết định riêng của review bảo mật.

def test_dac_ta_bien_tro_vao_trong_repo_thi_dung_trong_repo_hien_trang(repo, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(repo / "ws"))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == (repo / "ws" / "marketing").resolve()
    cay_tram_ok(repo / "ws" / "marketing")


@pytest.mark.parametrize("cach", ["yes", "Enter", "ni"])
def test_bien_chinh_no_la_mot_tram_la_ma_2_nen_ten_bien_va_khong_dung_long_nhau(
        cach, repo, tmp_path, monkeypatch):
    """`OPCOS_WORKSPACES` phải là GỐC chứa các trạm, không phải một trạm: dựng `<biến>/marketing` bên trong
    một trạm là lồng trạm vào trạm. Gốc không mang dấu thì không bị chặn (các test khác)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / SP.SO_KENH).write_text("---\nchannels: []\n---\n# tram\n", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(ws))
    if cach == "yes":
        kw = dict(yes=True, ask=khong_duoc_hoi)
    elif cach == "Enter":
        kw = dict(ask=tra_loi(""))
    else:
        kw = dict(non_interactive=True)
    with pytest.raises(SC.ContractError, match="OPCOS_WORKSPACES"):
        IS.do_init(**kw)
    assert not (ws / "marketing").exists() and not (repo / SP.LOCAL_CONFIG).exists()
    assert (ws / SP.SO_KENH).read_text(encoding="utf-8").endswith("# tram\n")


def test_dac_ta_tram_OPCOS_co_san_khong_rong_chua_dau_thi_dung_tiep_khong_xoa_gi_hien_trang(
        repo, tmp_path, monkeypatch):
    d = tmp_path / "ws" / "marketing"
    d.mkdir(parents=True)
    (d / "cua-toi.txt").write_text("giu\n", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert Path(kq["station"]) == d.resolve()
    assert (d / "cua-toi.txt").read_text(encoding="utf-8") == "giu\n"
    cay_tram_ok(d)


# ── Ctrl+C ở biên CLI = mã 2, một dòng, không traceback ──────────────────────────

def _ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def _khong_de_ctrl_c_lan(fn, *a):
    """Gọi `fn`; Ctrl+C lan ra khỏi biên CLI là LỖI của test này (không được làm sập cả phiên pytest)."""
    try:
        return fn(*a)
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C lan ra khỏi biên CLI thay vì thành mã 2")


def test_CtrlC_o_bien_CLI_la_ma_2_mot_dong_da_huy_khong_traceback(capsys):
    def nang(_a):
        raise KeyboardInterrupt
    ma = _khong_de_ctrl_c_lan(SC.run, nang, _ns(prog="init_station"), False)
    err = capsys.readouterr().err
    assert ma == SC.CONTRACT_ERROR == 2
    assert "[init_station] đã huỷ (Ctrl+C)." in err and "Traceback" not in err
    assert len([d for d in err.splitlines() if d.strip()]) == 1


def test_CtrlC_voi_json_phat_ok_false_code_2(capsys):
    def nang(_a):
        raise KeyboardInterrupt
    ma = _khong_de_ctrl_c_lan(SC.run, nang, _ns(prog="studio"), True)
    out, err = capsys.readouterr()
    assert ma == 2 and "Traceback" not in err
    assert json.loads(out.strip().splitlines()[-1]) == {"ok": False, "code": 2, "error": "đã huỷ (Ctrl+C)"}


def test_CtrlC_o_cau_hoi_cua_init_thanh_ma_2_qua_main(repo, oc_ws, monkeypatch, capsys):
    """Đường thật: bàn phím ném KeyboardInterrupt ở câu hỏi đường → `main` trả 2, chưa ghi gì."""
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: True)

    def huy(_cau):
        raise KeyboardInterrupt
    monkeypatch.setattr(IS, "_hoi_duong_ban_phim", huy)
    truoc = chup(repo)
    ma = _khong_de_ctrl_c_lan(IS.main, ["--no-doctor"])
    err = capsys.readouterr().err
    assert ma == SC.CONTRACT_ERROR and "đã huỷ (Ctrl+C)" in err and "Traceback" not in err
    assert chup(repo) == truoc


# ── Chữ khớp hành vi: help, installer, tài liệu không còn nói `--yes` = embedded vô điều kiện ───

def test_help_yes_va_non_interactive_noi_dung_hanh_vi_khi_may_dat_OPCOS_WORKSPACES():
    ap = IS._parser()
    tro = {a.option_strings[0]: (a.help or "") for a in ap._actions if a.option_strings}
    assert "OPCOS_WORKSPACES" in tro["--yes"] and "(embedded)" not in tro["--yes"], tro["--yes"]
    assert "OPCOS_WORKSPACES" in tro["--non-interactive"], tro["--non-interactive"]


def test_vo_cai_dat_khong_con_noi_yes_la_embedded_hay_non_interactive_la_ma_2_vo_dieu_kien():
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    cam = {"install.ps1": ("nhan khuyen nghi: embedded", "khong hoi; khong co ai tra loi -> ma 2"),
           "install.sh": ("nhận khuyến nghị: embedded", "không hỏi; không ai trả lời -> mã 2")}
    for ten, doc in (("install.ps1", ps1), ("install.sh", sh)):
        for c in cam[ten]:
            assert c not in doc, f"{ten} còn câu '{c}'"
        assert "OPCOS_WORKSPACES" in doc, f"{ten} phải nêu hành vi khi máy đặt OPCOS_WORKSPACES"


def test_tai_lieu_khong_con_noi_yes_ra_repo_workspaces_vo_dieu_kien():
    cu = ("`--yes` thì không bao giờ hỏi và ra `<repo>/workspaces`",
          "`--yes` không bao giờ hỏi và ra `<repo>/workspaces`",
          "`--yes` ra `<repo>/workspaces` (không bao giờ hỏi)")
    da_doc = 0
    for rel in ("docs/ONBOARDING.md", "docs/WORKSPACE.md", "AGENTS.md", "INSTALL.md", "README.md"):
        f = ROOT / rel
        if f.is_file():
            da_doc += 1
            gop = " ".join(f.read_text(encoding="utf-8").split())
            for c in cu:
                assert c not in gop, f"{rel}: còn câu '{c}'"
    assert da_doc >= 3


def test_goi_y_cai_tram_giong_video_khong_noi_yes_la_embedded_vo_dieu_kien():
    for rel in ("scripts/lib/voice.py", "scripts/lib/video.py"):
        t = (ROOT / rel).read_text(encoding="utf-8")
        assert "init --yes   (embedded: trạm = " not in t and "OPCOS_WORKSPACES" in t, rel


def test_changelog_noi_cach_giu_tram_trong_repo_khi_may_co_bien_va_cac_ca_moi():
    khoi = _khoi_changelog_hien_hanh()
    gop = " ".join(khoi.split())
    assert "--mode embedded --yes" in gop, "thiếu cách chuyển cho người quen `--yes` = embedded"
    assert "còn `--yes` ra `<repo>/workspaces`" not in gop
    assert "`--non-interactive` thiếu cả `--yes` lẫn `--mode` thì dừng mã 2." not in gop
    for phai_co in ("-NonInteractive", "< NUL", "giữ", "Ctrl+C"):
        assert phai_co in gop, phai_co


# ── Các ô KHÔNG ĐỔI của bảng chuẩn mà trước đây chưa có test riêng: khoá lại (đếm câu hỏi bằng đúng) ─────

@pytest.mark.parametrize("go", ["1", "embedded", "EMBEDDED", " 1 "])
def test_go_1_hoac_embedded_o_bang_che_do_ra_embedded_dung_mot_cau(go, repo):
    ask = tra_loi(go)
    mode, st, _ = IS.chon_che_do(ask=ask)
    assert (mode, Path(st)) == ("embedded", (repo / "workspaces").resolve()) and len(ask.da_hoi) == 1


def test_go_2_roi_Enter_rong_khong_co_goi_y_la_ma_2_sau_dung_hai_cau(repo, nha):
    ask = tra_loi("2", "")
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(ask=ask)
    assert len(ask.da_hoi) == 2 and not (repo / SP.LOCAL_CONFIG).exists()


def test_mode_separate_co_nguoi_Enter_rong_khong_co_goi_y_la_ma_2_sau_dung_mot_cau(repo, nha):
    ask = tra_loi("")
    with pytest.raises(SC.ContractError, match="--station"):
        IS.do_init(mode="separate", ask=ask)
    assert len(ask.da_hoi) == 1 and not (repo / SP.LOCAL_CONFIG).exists()


def test_station_thang_bien_OPCOS_va_khong_hoi_cau_nao(repo, oc_ws, tmp_path):
    rieng = tmp_path / "chi-dinh"
    kq = IS.do_init(station=str(rieng), ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == rieng.resolve() and kq["reason"] == "--station"
    assert not (oc_ws / "marketing").exists()


@pytest.mark.parametrize("bien", ["MARKETING_STUDIO_DATA", "VOICE_STATION", "VIDEO_STATION",
                                  "OMNIVOICE_DIR", "VIDEO_ROOT"])
@pytest.mark.parametrize("co_opcos", [False, True])
def test_mode_embedded_khi_da_co_bien_tram_la_ma_2_hai_nguon_su_that(
        bien, co_opcos, repo, tmp_path, monkeypatch):
    if co_opcos:
        monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    monkeypatch.setenv(bien, str(tmp_path / "tram-cu"))
    with pytest.raises(SC.ContractError, match="hai nguồn sự thật"):
        IS.do_init(mode="embedded", ask=khong_duoc_hoi)
    assert not (repo / SP.WORKSPACE).exists()


def test_lua_chon_da_ghi_separate_co_station_path_thi_dung_no_khong_hoi_khi_khong_co_bien(
        repo, tmp_path):
    rieng = tmp_path / "rieng"
    (repo / SP.LOCAL_CONFIG).write_text(
        json.dumps({"mode": "separate", "station_path": str(rieng)}), encoding="utf-8")
    kq = IS.do_init(ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and Path(kq["station"]) == rieng.resolve()


@pytest.mark.parametrize("cach", ["yes", "ni", "khong_tty"])
@pytest.mark.parametrize("hinh", ["bien-chua-dau", "bien-da-dau"])
def test_khong_doi_nhanh_bien_anh_em_van_dung_tram_OPCOS_khi_co_OPCOS_WORKSPACES(
        hinh, cach, repo, oc_ws, tmp_path, monkeypatch):
    """Biến anh em + OPCOS_WORKSPACES + trạm nhúng KHÔNG mang dấu ⇒ trạm OpcOS (mã hiện đã vậy)."""
    monkeypatch.setenv("VOICE_STATION", str(tmp_path))
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: cach == "ni")
    if hinh == "bien-da-dau":
        (oc_ws / "marketing").mkdir(parents=True)
        (oc_ws / "marketing" / SP.SO_KENH).write_text("---\nchannels: []\n---\n", encoding="utf-8")
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else \
        dict(non_interactive=True) if cach == "ni" else {}
    kq = IS.do_init(**kw)
    assert kq["mode"] == "separate" and Path(kq["station"]) == (oc_ws / "marketing").resolve()


def test_station_tuong_doi_duoc_tuyet_doi_hoa_va_ghi_tuyet_doi_khong_hoi(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    kq = IS.do_init(station="noi-tuong-doi", ask=khong_duoc_hoi)
    dich = (tmp_path / "noi-tuong-doi").resolve()
    assert kq["mode"] == "separate" and Path(kq["station"]) == dich
    assert os.path.isabs(doc_local(repo)["station_path"]) and Path(doc_local(repo)["station_path"]) == dich


def test_bien_anh_em_va_OPCOS_va_tram_cu_chon_chuyen_thi_tra_then_migrate_va_khong_doi_byte(
        repo, oc_ws, tmp_path, monkeypatch):
    cu = tram_nhung_co_du_lieu(repo)
    monkeypatch.setenv("VOICE_STATION", str(tmp_path))
    truoc = bam_cay(cu)
    ask = tra_loi("chuyen")
    ch = IS.chon_che_do(ask=ask)
    assert ch.mode == "embedded" and Path(ch.path) == cu.resolve() and ch.then_migrate == dich_oc(oc_ws)
    assert len(ask.da_hoi) == 1 and bam_cay(cu) == truoc and not oc_ws.exists()


def test_bien_anh_em_va_OPCOS_va_tram_cu_chon_chuyen_xac_nhan_roi_migrate(
        repo, oc_ws, tmp_path, monkeypatch):
    cu = tram_nhung_co_du_lieu(repo)
    monkeypatch.setenv("VOICE_STATION", str(tmp_path))
    truoc = bam_cay(cu)
    ask = tra_loi("chuyen", "y")
    kq = IS.do_init(ask=ask)
    dich = oc_ws / "marketing"
    assert len(ask.da_hoi) == 2
    assert kq["mode"] == "separate" and Path(kq["station"]) == dich.resolve()
    assert not cu.exists() and all(bam_cay(dich).get(p) == h for p, h in truoc.items())
    assert doc_local(repo)["mode"] == "separate"


# ── Vòng sửa sau review: chữ còn sót, kiểm đích trước câu y/N, thông báo nêu tên biến ────────

def test_tai_lieu_cai_dat_noi_ngoai_le_may_co_OPCOS_WORKSPACES_o_cho_noi_ma_2():
    """Hai chỗ nói "không truyền lựa chọn thì mã 2" phải có vế "trừ khi máy đặt OPCOS_WORKSPACES"."""
    install = " ".join((ROOT / "INSTALL.md").read_text(encoding="utf-8").split())
    i = install.index("Không truyền lựa chọn")
    assert "OPCOS_WORKSPACES" in install[i:i + 700], "INSTALL.md thiếu vế OPCOS_WORKSPACES"
    for dong in (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8").splitlines():
        if "Bộ cài dừng **mã 2** ngay" in dong:
            assert "OPCOS_WORKSPACES" in dong, dong
            break
    else:
        pytest.fail("không thấy dòng 'Bộ cài dừng mã 2 ngay' trong docs/troubleshooting.md")
    ws = " ".join((ROOT / "docs" / "WORKSPACE.md").read_text(encoding="utf-8").split())
    j = ws.index("Máy đã có trạm ngoài thì")
    assert "trừ khi" in ws[j:j + 900] and "dữ liệu có sẵn" in ws[j:j + 1400], "WORKSPACE.md thiếu ngoại lệ"


def test_tram_opcos_docstring_khong_con_noi_chi_init_va_doctor_goi():
    assert "CHỈ `init`" not in (SP.tram_opcos.__doc__ or "")


def _tao_junction(link: Path, dich: Path) -> bool:
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(dich)], capture_output=True, text=True)
    return r.returncode == 0 and link.exists()


@pytest.mark.skipif(os.name != "nt", reason="junction là của Windows")
def test_chon_chuyen_nhung_dich_la_junction_vao_trong_tram_nguon_thi_ma_2_truoc_cau_y_N(
        repo, oc_ws, tmp_path):
    cu = tram_nhung_co_du_lieu(repo)
    (cu / "sub").mkdir()
    oc_ws.mkdir()
    if not _tao_junction(oc_ws / "marketing", cu / "sub"):
        pytest.skip("không tạo được junction trên máy này")
    ask = tra_loi("chuyen")                        # chỉ MỘT câu: y/N không được hỏi
    with pytest.raises(SC.ContractError, match="nằm trong"):
        IS.do_init(ask=ask)
    assert len(ask.da_hoi) == 1 and (cu / "kenh-a" / "bai.md").is_file()
    assert doc_local(repo)["mode"] == "embedded"


def test_chon_chuyen_nhung_kho_secret_da_co_env_va_repo_co_env_cua_ban_thi_ma_2_truoc_cau_y_N(
        repo, oc_ws, nha):
    tram_nhung_co_du_lieu(repo)
    (repo / ".env").write_text("CUA_TOI=1\n", encoding="utf-8")
    kho = nha / ".secret" / "marketing-studio"
    kho.mkdir(parents=True)
    (kho / ".env").write_text("DA_CO=1\n", encoding="utf-8")
    ask = tra_loi("chuyen")
    with pytest.raises(SC.ContractError, match=r"\.env"):
        IS.do_init(ask=ask)
    assert len(ask.da_hoi) == 1
    assert (repo / ".env").read_text(encoding="utf-8") == "CUA_TOI=1\n"
    assert (kho / ".env").read_text(encoding="utf-8") == "DA_CO=1\n"
    assert not (oc_ws / "marketing").exists()


def test_chon_chuyen_khong_tu_tao_env_mau_roi_dem_vao_kho_secret_cua_may(repo, oc_ws, nha):
    """`init` chỉ dọn `.env` mẫu khi giữ trạm trong repo; chuyển đi thì không tạo file rồi bắt gộp nó."""
    tram_nhung_co_du_lieu(repo)
    kho = nha / ".secret" / "marketing-studio"
    kho.mkdir(parents=True)
    (kho / ".env").write_text("DA_CO=1\n", encoding="utf-8")
    kq = IS.do_init(ask=tra_loi("chuyen", "y"))
    assert kq["mode"] == "separate" and not (repo / ".env").exists()
    assert (kho / ".env").read_text(encoding="utf-8") == "DA_CO=1\n"


@pytest.mark.parametrize("cach", ["yes", "Enter"])
def test_bien_nam_duoi_mot_file_la_ma_2_nen_ten_bien(cach, repo, tmp_path, monkeypatch):
    f = tmp_path / "la-file"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(f / "ws"))
    kw = dict(yes=True, ask=khong_duoc_hoi) if cach == "yes" else dict(ask=tra_loi(""))
    with pytest.raises(SC.ContractError, match="OPCOS_WORKSPACES"):
        IS.do_init(**kw)
    assert not (repo / SP.LOCAL_CONFIG).exists()


# ── doctor im lặng về OPCOS_WORKSPACES khi đã chọn embedded; câu `--station` nguyên văn ở runner ─────

def test_doctor_im_lang_ve_OPCOS_khi_da_chon_embedded_du_thu_muc_OPCOS_chua_mang_dau(
        repo, tmp_path, monkeypatch):
    (repo / "workspaces").mkdir()
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))        # <ws>/marketing không có CHANNELS.md
    (repo / SP.LOCAL_CONFIG).write_text(json.dumps({"mode": "embedded"}), encoding="utf-8")
    assert [d for d in DR.kham()["warn"] if "OPCOS_WORKSPACES" in d] == []
    assert any(".env" in d for d in DR.kham()["warn"]), "cảnh báo khác vẫn phải được giữ"
    (repo / SP.LOCAL_CONFIG).unlink()          # chưa chọn gì thì vẫn nhắc
    assert [d for d in DR.kham()["warn"] if "OPCOS_WORKSPACES" in d]


def test_runner_paths_thieu_tram_mang_nguyen_van_cau_station_cua_hop_dong(repo):
    import importlib.util
    spec = importlib.util.spec_from_file_location("paths_runner_nv", ROOT / "scripts" / "runners" / "paths.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with pytest.raises(SC.StationMissing) as e:
        m.station()
    assert SC.GOI_Y_DU_LIEU_CU in str(e.value)


def test_khong_nguoi_khong_co_khong_bien_thong_bao_neu_ca_station_va_yes_va_mode(repo, monkeypatch):
    """Không có ai trả lời (stdin hết dữ liệu hoặc không phải terminal) và không có OPCOS_WORKSPACES: mã 2,
    thông báo nêu đủ cách đi tiếp: `--mode`, `--station <đường>` và `--yes`."""
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: True)
    with pytest.raises(SC.ContractError) as e1:
        IS.chon_che_do(ask=hoi_roi_ngat(EOFError()))
    monkeypatch.setattr(IS, "_co_nguoi_tra_loi", lambda: False)
    with pytest.raises(SC.ContractError) as e2:
        IS.chon_che_do()
    for e in (e1, e2):
        m = str(e.value)
        assert "--mode" in m and "--station <đường>" in m and "--yes" in m, m


# ── Biến không dùng được + trạm cũ có dữ liệu: kiểm biến chạy TRƯỚC mọi câu hỏi và mọi lần dời ─────────

@pytest.mark.parametrize("hinh", ["bien-la-tram", "bien-la-file"])
@pytest.mark.parametrize("cach", ["yes", "chuyen-roi-y"])
def test_bien_khong_dung_duoc_va_tram_cu_co_du_lieu_la_ma_2_nen_ten_bien_khong_doi_byte(
        cach, hinh, repo, tmp_path, monkeypatch):
    cu = tram_nhung_co_du_lieu(repo)
    truoc = bam_cay(cu)
    ws = tmp_path / "ws"
    if hinh == "bien-la-tram":
        ws.mkdir()
        (ws / SP.SO_KENH).write_text("---\nchannels: []\n---\n# tram\n", encoding="utf-8")
    else:
        ws.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPCOS_WORKSPACES", str(ws))
    ask = khong_duoc_hoi if cach == "yes" else tra_loi("chuyen", "y")
    with pytest.raises(SC.ContractError, match="OPCOS_WORKSPACES"):
        IS.do_init(yes=(cach == "yes"), ask=ask)
    if cach != "yes":
        assert ask.da_hoi == [], "phải từ chối TRƯỚC mọi câu hỏi"
    assert bam_cay(cu) == truoc and not (repo / SP.LOCAL_CONFIG).exists()
    assert not (ws / "marketing").exists() if hinh == "bien-la-tram" else ws.is_file()


@pytest.mark.skipif(os.name != "nt", reason="ký tự cấm trong tên là của Windows")
@pytest.mark.parametrize("gia_tri", ['"{ws}"', "{ws}<a", "{ws}?x"])
@pytest.mark.parametrize("hinh", ["khong-tram-cu", "co-tram-cu"])
@pytest.mark.parametrize("cach", ["yes", "Enter"])
def test_bien_co_ky_tu_cam_la_ma_2_mot_dong_khong_cau_hoi_khong_ghi(
        cach, hinh, gia_tri, repo, tmp_path, monkeypatch, capsys):
    if hinh == "co-tram-cu":
        tram_nhung_co_du_lieu(repo)
    monkeypatch.setenv("OPCOS_WORKSPACES", gia_tri.format(ws=tmp_path / "ws"))
    ask = khong_duoc_hoi if cach == "yes" else tra_loi("")
    truoc = chup(repo, tmp_path)
    with pytest.raises(SC.ContractError, match="OPCOS_WORKSPACES"):
        IS.do_init(yes=(cach == "yes"), ask=ask)
    if cach != "yes":
        assert ask.da_hoi == [], "phải từ chối TRƯỚC câu hỏi"
    assert chup(repo, tmp_path) == truoc
    assert "dùng " not in capsys.readouterr().err, "không in dòng 'dùng …' rồi mới lỗi"


@pytest.mark.skipif(os.name != "nt", reason="tiền tố đường dài là của Windows")
@pytest.mark.parametrize("kieu", ["gach-nguoc", "gach-xuoi"])
def test_bien_co_tien_to_duong_dai_hop_le_ra_tram_OPCOS_ma_0(kieu, repo, tmp_path, monkeypatch):
    """`\\?\C:\...` (và dạng `//?/C:/...`) là đường hợp lệ: dấu `?` của tiền tố không phải ký tự cấm."""
    goc = str(tmp_path / "ws")
    if kieu == "gach-nguoc":
        gia_tri = chr(92) * 2 + "?" + chr(92) + goc
    else:
        gia_tri = "//?/" + goc.replace(chr(92), "/")
    monkeypatch.setenv("OPCOS_WORKSPACES", gia_tri)
    kq = IS.do_init(yes=True, ask=khong_duoc_hoi)
    assert kq["mode"] == "separate" and (tmp_path / "ws" / "marketing" / SP.SO_KENH).is_file()
