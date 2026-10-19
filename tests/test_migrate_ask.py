# -*- coding: utf-8 -*-
"""`migrate --to separate` hỏi rõ nơi dời.

Không còn đích ngầm. Không có `--station`:
  * có người ngồi → hỏi nơi dời (gợi ý, không áp đặt), cho thấy đường tuyệt đối đích và
    số file / dung lượng sẽ dời, rồi xin xác nhận y/N TRƯỚC khi dời byte đầu tiên;
  * không có người → bắt buộc `--station`, thiếu thì dừng mã 2 và nói cách làm.
Gợi ý: `<OPCOS_WORKSPACES>/marketing` khi biến có; không có biến thì KHÔNG gợi ý gì (người dùng gõ đường).
Thư mục trong nhà không bao giờ là đích mặc định. Nguồn là trạm nhúng `<repo>/workspaces`. Đích nằm trong chính trạm nguồn bị từ chối.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
import init_station as IS  # noqa: E402
import studio as ST  # noqa: E402
import studio_contract as SC  # noqa: E402
import studio_paths as SP  # noqa: E402


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True,
                          text=True, encoding="utf-8")


@pytest.fixture
def repo_git(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("cần git")
    r = tmp_path / "clones" / "repo"
    (r / "scripts" / "lib").mkdir(parents=True)
    (r / "install.ps1").write_text("", encoding="utf-8")
    shutil.copytree(ROOT / "templates" / "workspace", r / "templates" / "workspace")
    (r / "templates" / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "templates" / "hooks" / "pre-commit",
                    r / "templates" / "hooks" / "pre-commit")
    shutil.copyfile(ROOT / ".env.example", r / ".env.example")
    shutil.copyfile(ROOT / ".gitignore", r / ".gitignore")
    _git(tmp_path, "init", "-q", str(r))
    for c in (["user.email", "x@y.z"], ["user.name", "x"]):
        _git(r, "config", *c)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    nha = tmp_path / "nha"
    nha.mkdir()
    monkeypatch.setenv("HOME", str(nha))
    monkeypatch.setenv("USERPROFILE", str(nha))
    for b in ("MARKETING_STUDIO_DATA", "VOICE_STATION", "OMNIVOICE_DIR",
              "VIDEO_STATION", "VIDEO_ROOT", "OPCOS_WORKSPACES"):
        monkeypatch.delenv(b, raising=False)
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(r))
    IS.do_init(yes=True)
    (r / SP.WORKSPACE / "kenh-cua-toi").mkdir()
    (r / SP.WORKSPACE / "kenh-cua-toi" / "channel.yml").write_text("id: kenh-cua-toi\n",
                                                                   encoding="utf-8")
    return r


def _tra_loi(*cau):
    """Giả người gõ: trả lần lượt từng câu, ghi lại lời nhắc đã hiện."""
    con = list(cau)
    loi_nhac = []

    def ask(nhac):
        loi_nhac.append(nhac)
        if not con:
            raise EOFError
        return con.pop(0)
    ask.loi_nhac = loi_nhac
    ask.con = con
    return ask


def _nguyen_ven(repo):
    return (repo / SP.WORKSPACE / "kenh-cua-toi" / "channel.yml").is_file()


# ── gợi ý đích ────────────────────────────────────────────────────────────────────────

def test_goi_y_la_opcos_workspaces_marketing_khi_co_bien(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "kho-ws"))
    g = ST.goi_y_dich(repo_git)
    assert g == (tmp_path / "kho-ws" / "marketing").resolve()
    assert g.is_absolute()


def test_goi_y_bien_tuong_doi_van_ra_duong_tuyet_doi(repo_git, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPCOS_WORKSPACES", "tuong-doi")
    g = ST.goi_y_dich(repo_git)
    assert g.is_absolute() and g == (tmp_path / "tuong-doi" / "marketing").resolve()


def test_khong_co_bien_thi_KHONG_goi_y_gi_ca(repo_git):
    """Không đoán đích từ vị trí của repo: clone có thể nằm trong một repo git khác, và
    một đường suy từ vị trí repo sẽ dời nội dung vào cây repo đó."""
    assert ST.goi_y_dich(repo_git) is None


def test_clone_nam_trong_repo_git_khac_khong_bi_goi_y_vao_cay_do(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("cần git")
    ngoai = tmp_path / "repo-khac"
    _git(tmp_path, "init", "-q", str(ngoai))
    (ngoai / "clones" / "repo").mkdir(parents=True)
    monkeypatch.delenv("OPCOS_WORKSPACES", raising=False)
    assert ST.goi_y_dich(ngoai / "clones" / "repo") is None
    ask = _tra_loi("")
    with pytest.raises(SC.ContractError):
        ST._hoi_noi_doi(ngoai / "clones" / "repo", ngoai / "clones" / "repo" / "workspaces", ask, False)
    assert str(ngoai) not in ask.loi_nhac[0], "lời nhắc không được gợi ý đường trong cây repo khác"


def test_khong_bao_gio_goi_y_thu_muc_trong_nha(repo_git, tmp_path, monkeypatch):
    nha = str(Path(SP.os.path.expanduser("~")))
    assert ST.goi_y_dich(repo_git) is None
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    assert not str(ST.goi_y_dich(repo_git)).startswith(nha) or str(tmp_path).startswith(nha)


def test_khong_co_bien_tuong_tac_Enter_rong_la_dung_va_chua_dung_gi(repo_git, tmp_path):
    ask = _tra_loi("")
    with pytest.raises(SC.ContractError):
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    assert _nguyen_ven(repo_git) and len(ask.loi_nhac) == 1


def test_khong_co_bien_tuong_tac_go_duong_thi_hoi_xac_nhan_roi_doi(repo_git, tmp_path):
    dich = tmp_path / "toi-go"
    kq = ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=_tra_loi(str(dich), "y"))
    assert Path(kq["station"]) == dich.resolve()


@pytest.mark.parametrize("bao", ['"{}"', "'{}'", ' "{}" '])
def test_duong_dan_dan_kem_ngoac_kep_van_dung(bao, repo_git, tmp_path):
    """'Copy as path' của Windows dán vào kèm cặp ngoặc kép."""
    dich = tmp_path / "tram co dau cach"
    kq = ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"),
                                  ask=_tra_loi(bao.format(dich), "y"))
    assert Path(kq["station"]) == dich.resolve() and '"' not in kq["station"]
    assert (dich / "kenh-cua-toi" / "channel.yml").is_file()


@pytest.mark.parametrize("cach", ["station", "hoi"])
@pytest.mark.parametrize("vi_tri", ["ben-trong", "chinh-no"])
def test_dich_nam_trong_nguon_bi_tu_choi_dung_ly_do_va_khong_de_thu_muc_rong(
        cach, vi_tri, repo_git, tmp_path):
    ws = repo_git / SP.WORKSPACE
    dich = ws / "con" / "moi" if vi_tri == "ben-trong" else ws
    kw = dict(kho_secret=str(tmp_path / "kho"))
    if cach == "station":
        kw["station"] = str(dich)
    else:
        kw["ask"] = _tra_loi(str(dich), "y")
    truoc = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*"))
    with pytest.raises(SC.ContractError, match="nằm trong"):
        ST.migrate_sang_separate(**kw)
    assert sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*")) == truoc
    assert _nguyen_ven(repo_git)
    lc = json.loads((repo_git / SP.LOCAL_CONFIG).read_text(encoding="utf-8"))
    assert lc["mode"] == "embedded"


def test_bien_chi_doc_tu_moi_truong_that_khong_doc_env_cua_repo(repo_git, tmp_path):
    (repo_git / ".env").write_text(f"OPCOS_WORKSPACES={tmp_path / 'tu-env'}\n", encoding="utf-8")
    assert "tu-env" not in str(ST.goi_y_dich(repo_git))


# ── tương tác: hỏi rồi mới dời ────────────────────────────────────────────────────────

def test_tuong_tac_enter_nhan_goi_y_roi_y_thi_doi(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    ask = _tra_loi("", "y")
    kq = ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    dich = (tmp_path / "ws" / "marketing").resolve()
    assert Path(kq["station"]) == dich
    assert (dich / "kenh-cua-toi" / "channel.yml").is_file()
    assert not (repo_git / SP.WORKSPACE).exists()
    nhac = "\n".join(ask.loi_nhac)
    assert str(dich) in nhac, "phải hiện đường TUYỆT ĐỐI của đích"


def test_tuong_tac_cho_thay_so_file_va_dung_luong(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    ws = repo_git / SP.WORKSPACE
    n = sum(1 for p in ws.rglob("*") if p.is_file())
    ask = _tra_loi("", "n")
    with pytest.raises(SC.ContractError):
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    nhac = "\n".join(ask.loi_nhac)
    assert f"{n} file" in nhac, nhac


def test_tuong_tac_tra_loi_khong_thi_khong_dung_gi(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    (repo_git / ".env").write_text("A=1\n", encoding="utf-8")
    for cau in ("n", "", "N", "co"):
        with pytest.raises(SC.ContractError):
            ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=_tra_loi("", cau))
        assert _nguyen_ven(repo_git) and (repo_git / ".env").is_file()
        assert not (tmp_path / "ws").exists()
        lc = json.loads((repo_git / SP.LOCAL_CONFIG).read_text(encoding="utf-8"))
        assert lc["mode"] == "embedded"


def test_tuong_tac_nguoi_dung_go_duong_khac_thay_goi_y(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    khac = tmp_path / "toi-chon"
    kq = ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=_tra_loi(str(khac), "y"))
    assert Path(kq["station"]) == khac.resolve()
    assert (khac / "kenh-cua-toi" / "channel.yml").is_file()
    assert not (tmp_path / "ws").exists()


def test_tuong_tac_duong_tuong_doi_duoc_doi_thanh_tuyet_doi(repo_git, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ask = _tra_loi("tram-tuong-doi", "y")
    kq = ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    assert Path(kq["station"]).is_absolute() and Path(kq["station"]) == (tmp_path / "tram-tuong-doi").resolve()


def test_tuong_tac_dich_khong_rong_van_bi_tu_choi_truoc_khi_hoi_xac_nhan(repo_git, tmp_path):
    co = tmp_path / "co-nguoi-o"
    co.mkdir()
    (co / "x.md").write_text("x", encoding="utf-8")
    ask = _tra_loi(str(co), "y")
    with pytest.raises(SC.ContractError, match="không rỗng"):
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    assert _nguyen_ven(repo_git)
    assert len(ask.loi_nhac) == 1 and ask.con == ["y"], "đích kẹt thì không được xin xác nhận"


# ── không tương tác: bắt buộc --station ───────────────────────────────────────────────

def test_khong_tuong_tac_thieu_station_la_ma_2_va_chua_dung_gi(repo_git, tmp_path, monkeypatch):
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    with pytest.raises(SC.ContractError, match="--station") as e:
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), non_interactive=True)
    assert e.value.code == SC.CONTRACT_ERROR == 2
    assert _nguyen_ven(repo_git) and not (tmp_path / "ws").exists()


def test_stdin_khong_phai_terminal_cung_la_ma_2(repo_git, tmp_path, monkeypatch):
    """Dưới pytest stdin không phải terminal: không khai `--station` thì không được đoán."""
    monkeypatch.setenv("OPCOS_WORKSPACES", str(tmp_path / "ws"))
    with pytest.raises(SC.ContractError, match="--station"):
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"))
    assert _nguyen_ven(repo_git) and not (tmp_path / "ws").exists()


def test_CLI_thieu_station_khong_tuong_tac_ra_ma_2_va_json(repo_git, tmp_path, capsys):
    ma = ST.main(["migrate", "--to", "separate", "--json"])
    out, _ = capsys.readouterr()
    assert ma == 2
    kq = json.loads(out.strip().splitlines()[-1])
    assert kq["ok"] is False and kq["code"] == 2 and "--station" in kq["error"]
    assert _nguyen_ven(repo_git)


def test_CLI_co_station_thi_khong_hoi_va_doi(repo_git, tmp_path, capsys):
    dich = tmp_path / "dich"
    ma = ST.main(["migrate", "--to", "separate", "--station", str(dich),
                  "--secret-dir", str(tmp_path / "kho")])
    assert ma == 0
    assert (dich / "kenh-cua-toi" / "channel.yml").is_file()


def test_thong_bao_loi_neu_cach_lam_va_khong_nhac_thu_muc_trong_nha(repo_git, tmp_path):
    with pytest.raises(SC.ContractError) as e:
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), non_interactive=True)
    msg = str(e.value)
    assert "--station" in msg and "migrate" in msg and ("." + "marketing") not in msg


def test_khong_tao_thu_muc_nao_trong_nha_khi_bi_tu_choi(repo_git, tmp_path):
    nha = Path(SP.os.path.expanduser("~"))
    truoc = sorted(p.name for p in nha.iterdir())
    with pytest.raises(SC.ContractError):
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), non_interactive=True)
    assert sorted(p.name for p in nha.iterdir()) == truoc


def test_help_khong_con_noi_mac_dinh_thu_muc_trong_nha():
    nguon = (ROOT / "scripts" / "pipeline" / "studio.py").read_text(encoding="utf-8")
    assert ("." + "marketing") not in nguon.replace("studio.marketing", ""), \
        "studio.py không còn coi một thư mục ẩn trong nhà là đích mặc định"


def test_nguon_la_bo_cuc_cu_workspace_so_it_van_dem_duoc_nhu_nguon(repo_git, tmp_path):
    """Bản cài cũ để `<repo>/workspace` (mang CHANNELS.md): migrate dời đúng thư mục đó."""
    moi = repo_git / "workspaces"
    cu = repo_git / "workspace"
    moi.rename(cu)
    lc = json.loads((repo_git / SP.LOCAL_CONFIG).read_text(encoding="utf-8"))
    lc["station_path"] = "workspace"
    (repo_git / SP.LOCAL_CONFIG).write_text(json.dumps(lc), encoding="utf-8")
    dich = tmp_path / "ra-ngoai"
    kq = ST.migrate_sang_separate(station=str(dich), kho_secret=str(tmp_path / "kho"))
    assert Path(kq["station"]) == dich.resolve()
    assert (dich / "kenh-cua-toi" / "channel.yml").is_file() and not cu.exists()


def test_dich_la_mot_FILE_thi_ma_2_chu_khong_NotADirectoryError(repo_git, tmp_path):
    f = tmp_path / "la-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SC.ContractError, match="FILE") as e:
        ST.migrate_sang_separate(station=str(f), kho_secret=str(tmp_path / "kho"))
    assert e.value.code == 2 and _nguyen_ven(repo_git) and f.read_text(encoding="utf-8") == "x"


def test_doi_that_bai_thi_thu_muc_dich_rong_co_san_cua_nguoi_dung_con_nguyen(
        repo_git, tmp_path, monkeypatch):
    """Báo 'chưa đụng gì' thì phải đúng: thư mục đích rỗng có sẵn bị rmdir để đổi tên được,
    nên khi đổi tên hỏng nó phải được dựng lại."""
    import errno
    dich = tmp_path / "dich-rong-co-san"
    dich.mkdir()

    def hong(*_a, **_k):
        raise OSError(errno.EACCES, "đang bị giữ")
    monkeypatch.setattr(ST.os, "rename", hong)
    with pytest.raises(SC.ContractError, match="CHƯA đụng gì"):
        ST.migrate_sang_separate(station=str(dich), kho_secret=str(tmp_path / "kho"))
    assert dich.is_dir() and not any(dich.iterdir()), "thư mục đích rỗng của người dùng phải còn"
    assert _nguyen_ven(repo_git)
    assert SP.mode(repo_git) == "embedded", "dời hỏng thì lựa chọn đã ghi vẫn là embedded"


def test_loi_OSError_giua_chung_van_tra_lai_thu_muc_dich_rong_co_san(repo_git, tmp_path, monkeypatch):
    """Không chỉ lỗi hợp đồng: một `OSError` (khác ổ, thiếu quyền) giữa chừng cũng phải dựng lại thư mục
    đích rỗng mà người dùng đã có, và để nguồn nguyên."""
    import errno
    dich = tmp_path / "dich-rong-co-san"
    dich.mkdir()

    def hong(*_a, **_k):
        raise OSError(errno.EXDEV, "cross-device")
    monkeypatch.setattr(ST, "_doi_cay", hong)
    with pytest.raises(OSError):
        ST.migrate_sang_separate(station=str(dich), kho_secret=str(tmp_path / "kho"))
    assert dich.is_dir() and not any(dich.iterdir()), "thư mục đích rỗng của người dùng phải còn"
    assert _nguyen_ven(repo_git)
    assert SP.mode(repo_git) == "embedded", "dời hỏng thì lựa chọn đã ghi vẫn là embedded"


def test_tuong_tac_go_duong_la_mot_FILE_o_cau_noi_doi_thi_noi_dich_la_FILE_va_ten_duong(repo_git, tmp_path):
    """Cùng thông báo với `--station`: đích là FILE (kèm đường), không phải 'không rỗng'; mã 2 trước câu y/N."""
    f = tmp_path / "la-file"
    f.write_text("x", encoding="utf-8")
    ask = _tra_loi(str(f))                       # chỉ một câu: y/N không được hỏi
    with pytest.raises(SC.ContractError, match="FILE") as e:
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    assert str(f) in str(e.value) and "không rỗng" not in str(e.value)
    assert len(ask.loi_nhac) == 1 and _nguyen_ven(repo_git) and f.read_text(encoding="utf-8") == "x"
