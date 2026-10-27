# -*- coding: utf-8 -*-
"""`migrate --to separate` hỏi rõ nơi dời.

Không còn đích ngầm. Không có `--station`:
  * có người ngồi → hỏi nơi dời (gợi ý, không áp đặt), cho thấy đường tuyệt đối đích và
    số file / dung lượng sẽ dời, rồi xin xác nhận y/N TRƯỚC khi dời byte đầu tiên;
  * không có người → bắt buộc `--station`, thiếu thì dừng mã 2 và nói cách làm.
Gợi ý: `<OPCOS_WORKSPACES>/marketing` khi biến có; không có biến thì KHÔNG gợi ý gì (người dùng gõ đường).
Thư mục trong nhà không bao giờ là đích mặc định. Nguồn là trạm nhúng `<repo>/workspaces`. Đích nằm trong chính trạm nguồn bị từ chối.
"""
import errno
import hashlib
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


def _tree_snapshot(root):
    """Exact directory/file snapshot for migration failure assertions."""
    result = {}
    for current, dirs, files in os.walk(root):
        rel = Path(current).relative_to(root)
        for name in dirs:
            result[str(rel / name)] = "<dir>"
        for name in files:
            path = Path(current) / name
            result[str(rel / name)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _inject_config_write_error(monkeypatch, repo, callback=None, opaque=False):
    """Fail once at the config boundary after the station move; allow rollback writes through."""
    config = repo / SP.LOCAL_CONFIG
    original_open = Path.open
    real_move_tree = ST._doi_cay
    moved = {"done": False}
    injected = {"count": 0, "path": None, "stage": None, "write_count": None}

    def move_then_mark(src, dst):
        real_move_tree(src, dst)
        moved["done"] = True

    class FailingConfigStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.stream.__exit__(*exc)

        def write(self, data):
            assert moved["done"], "config failure must follow the completed station move"
            if opaque:
                self.stream.write(b"X")
                injected.update(count=1, path=str(config), stage="opaque-partial-write")
                raise OSError("injected opaque config write failure")
            written = self.stream.write(data)
            injected["write_count"] = written
            return written

        def truncate(self, *args):
            if injected["count"] == 0:
                if callback:
                    callback()
                injected.update(count=1, path=str(config), stage="after-complete-write-before-truncate")
                raise OSError("injected local config write failure")
            return self.stream.truncate(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

    def fail_once(path, mode="r", *args, **kwargs):
        if path == config and mode in ("r+b", "x+b") and injected["count"] == 0:
            return FailingConfigStream(original_open(path, mode, *args, **kwargs))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(ST, "_doi_cay", move_then_mark)
    monkeypatch.setattr(Path, "open", fail_once)
    return config, moved, injected


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


def test_loi_ghi_local_config_sau_khi_doi_cay_khoi_phuc_toan_bo_trang_thai(
        repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    source = repo_git / SP.WORKSPACE
    target = tmp_path / "trạm-tách-riêng"
    env = repo_git / ".env"
    env.write_text("TEST_ONLY=not-a-secret\n", encoding="utf-8")
    env_bytes = env.read_bytes()
    config = repo_git / SP.LOCAL_CONFIG
    config_state = (config.exists(), config.read_bytes() if config.exists() else None)
    source_before = _tree_snapshot(source)
    marker = source / SP.SO_KENH
    marker_state = (marker.exists(), marker.read_bytes() if marker.exists() else None)
    secret_env = tmp_path / "fake-secret" / ".env"
    assert not target.exists() and not secret_env.exists()

    _, moved, injected = _inject_config_write_error(monkeypatch, repo_git)
    with pytest.raises(OSError, match="injected local config write failure"):
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert moved["done"] and injected == {
        "count": 1, "path": str(config),
        "stage": "after-complete-write-before-truncate", "write_count": injected["write_count"]}
    expected = {
        "source_tree": source_before,
        "marker": marker_state,
        "config": config_state,
        "source_env": env_bytes,
        "destination_exists": False,
        "secret_dir_exists": False,
        "secret_env_exists": False,
    }
    actual = {
        "source_tree": _tree_snapshot(source) if source.is_dir() else None,
        "marker": (marker.exists(), marker.read_bytes() if marker.exists() else None),
        "config": (config.exists(), config.read_bytes() if config.exists() else None),
        "source_env": env.read_bytes() if env.is_file() else None,
        "destination_exists": target.exists(),
        "secret_dir_exists": secret_env.parent.exists(),
        "secret_env_exists": secret_env.exists(),
    }
    assert actual == expected


def test_write_then_raise_is_unknown_and_retains_migration_artifacts(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    source = repo_git / SP.WORKSPACE
    target = tmp_path / "trạm-giữ-lại"
    env = repo_git / ".env"
    env.write_text("TEST_ONLY=not-a-secret\n", encoding="utf-8")
    original_config = (repo_git / SP.LOCAL_CONFIG).read_bytes()
    secret_env = tmp_path / "fake-secret" / ".env"
    _, moved, injected = _inject_config_write_error(monkeypatch, repo_git, opaque=True)

    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert "injected opaque config write failure" in str(error.value)
    assert moved["done"] and injected["stage"] == "opaque-partial-write"
    assert not source.exists() and target.is_dir(), "unknown config write must stop dependent tree rollback"
    assert not env.exists() and secret_env.read_text(encoding="utf-8") == "TEST_ONLY=not-a-secret\n"
    assert (repo_git / SP.LOCAL_CONFIG).read_bytes() != original_config


def test_rollback_keeps_new_config_when_it_was_absent_before_migration(repo_git, tmp_path, monkeypatch):
    config = repo_git / SP.LOCAL_CONFIG
    config.unlink()
    monkeypatch.setattr(ST.SP, "mode", lambda _repo: "embedded")
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    target = tmp_path / "trạm-config-mới"
    secret_env = tmp_path / "fake-secret" / ".env"
    _, _, injected = _inject_config_write_error(monkeypatch, repo_git)

    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert "injected local config write failure" in str(error.value)
    assert injected["count"] == 1 and injected["write_count"] > 0
    assert config.is_file(), "new metadata is retained rather than unlinked during rollback"
    assert target.is_dir() and not (repo_git / SP.WORKSPACE).exists()


def test_failed_config_write_does_not_overwrite_recreated_env_source(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    source = repo_git / SP.WORKSPACE
    target = tmp_path / "trạm-env-collision"
    env = repo_git / ".env"
    env.write_text("ORIGINAL=not-a-secret\n", encoding="utf-8")
    original_env = env.read_bytes()
    secret_env = tmp_path / "fake-secret" / ".env"
    foreign = b"FOREIGN=keep-me\n"

    def recreate_env_source():
        assert secret_env.is_file() and not env.exists()
        env.write_bytes(foreign)

    _, moved, injected = _inject_config_write_error(
        monkeypatch, repo_git, callback=recreate_env_source)
    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert "injected local config write failure" in str(error.value)
    assert moved["done"] and injected["count"] == 1
    assert env.read_bytes() == foreign and secret_env.read_bytes() == original_env
    assert source.exists() is False and target.is_dir(), "later tree rollback stops after env ownership conflict"


def test_failed_config_write_treats_dangling_env_source_as_occupied(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    env = repo_git / ".env"
    env.write_text("ORIGINAL=not-a-secret\n", encoding="utf-8")
    secret_env = tmp_path / "fake-secret" / ".env"
    missing_target = tmp_path / "foreign-not-created.txt"

    probe = tmp_path / "symlink-probe"
    try:
        probe.symlink_to(missing_target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink unavailable: {exc}")
    probe.unlink()

    def create_dangling_env_source():
        env.symlink_to(missing_target)

    _, moved, injected = _inject_config_write_error(
        monkeypatch, repo_git, callback=create_dangling_env_source)
    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(tmp_path / "trạm-env-link"),
                                 kho_secret=str(secret_env.parent))

    assert "injected local config write failure" in str(error.value)
    assert moved["done"] and injected["count"] == 1
    assert env.is_symlink() and not missing_target.exists()
    assert secret_env.read_text(encoding="utf-8") == "ORIGINAL=not-a-secret\n"


def test_env_restore_exdev_retains_copy_and_never_falls_back_to_copy2(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    env = repo_git / ".env"
    env.write_text("ORIGINAL=not-a-secret\n", encoding="utf-8")
    original_env = env.read_bytes()
    secret_env = tmp_path / "fake-secret" / ".env"
    target = tmp_path / "trạm-env-exdev"
    _, moved, injected = _inject_config_write_error(monkeypatch, repo_git)
    copy_calls = []

    def fail_restore(primitive):
        # Khôi phục dùng os.rename trên Windows và os.link trên POSIX: tiêm EXDEV vào cả hai.
        def restore(src, dst):
            if Path(src) == secret_env and Path(dst) == env:
                raise OSError(errno.EXDEV, "cross-device restore")
            return primitive(src, dst)
        return restore

    def forbidden_copy2(*args, **kwargs):
        copy_calls.append((args, kwargs))
        raise AssertionError("rollback must not fall back to copy2")

    monkeypatch.setattr(ST.os, "rename", fail_restore(ST.os.rename))
    monkeypatch.setattr(ST.os, "link", fail_restore(ST.os.link))
    monkeypatch.setattr(ST.shutil, "copy2", forbidden_copy2)
    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert "injected local config write failure" in str(error.value)
    assert "cross-device restore" in str(error.value)
    assert moved["done"] and injected["count"] == 1
    assert not copy_calls and not env.exists() and secret_env.read_bytes() == original_env
    assert target.is_dir() and not (repo_git / SP.WORKSPACE).exists()


def _posix_os(real_os, secret_env, env, rename_calls, before_link=None):
    """`os` giả POSIX: ghi lại mọi `rename` trả `.env` về repo (POSIX `rename` đè im lặng nên
    không được gọi), và cho chèn một cuộc đua ngay trước `link`."""
    class PosixOS:
        name = "posix"

        def __getattr__(self, name):
            return getattr(real_os, name)

        def rename(self, src, dst):
            if Path(src) == secret_env and Path(dst) == env:
                rename_calls.append((Path(src), Path(dst)))
            return real_os.rename(src, dst)

        def link(self, src, dst):
            if before_link and Path(src) == secret_env and Path(dst) == env:
                before_link()
            return real_os.link(src, dst)

    return PosixOS()


def test_posix_env_rollback_restores_by_link_never_overwriting_rename(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    env = repo_git / ".env"
    env.write_text("ORIGINAL=not-a-secret\n", encoding="utf-8")
    original_env = env.read_bytes()
    secret_env = tmp_path / "fake-secret" / ".env"
    target = tmp_path / "trạm-env-posix"
    source_before = _tree_snapshot(repo_git / SP.WORKSPACE)
    _, moved, injected = _inject_config_write_error(monkeypatch, repo_git)
    rename_calls = []
    monkeypatch.setattr(ST, "os", _posix_os(ST.os, secret_env, env, rename_calls))
    with pytest.raises(OSError, match="injected local config write failure"):
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert moved["done"] and injected["count"] == 1
    assert not rename_calls, "POSIX rollback must not invoke overwrite-capable rename"
    assert env.read_bytes() == original_env and not secret_env.exists()
    assert not secret_env.parent.exists() and not target.exists()
    assert _tree_snapshot(repo_git / SP.WORKSPACE) == source_before


def test_posix_env_rollback_never_clobbers_env_that_appears_at_link(repo_git, tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    env = repo_git / ".env"
    env.write_text("ORIGINAL=not-a-secret\n", encoding="utf-8")
    original_env = env.read_bytes()
    secret_env = tmp_path / "fake-secret" / ".env"
    target = tmp_path / "trạm-env-posix-race"
    _, moved, injected = _inject_config_write_error(monkeypatch, repo_git)
    rename_calls = []

    def foreign_env_appears():
        env.write_bytes(b"FOREIGN-SOURCE")

    monkeypatch.setattr(ST, "os", _posix_os(ST.os, secret_env, env, rename_calls, foreign_env_appears))
    with pytest.raises(SC.ContractError, match="rollback incomplete") as error:
        ST.migrate_sang_separate(station=str(target), kho_secret=str(secret_env.parent))

    assert ".env:" in str(error.value)
    assert moved["done"] and injected["count"] == 1
    assert not rename_calls
    assert env.read_bytes() == b"FOREIGN-SOURCE", "a path that appeared at the boundary stays untouched"
    assert secret_env.read_bytes() == original_env and target.is_dir()
    assert not (repo_git / SP.WORKSPACE).exists()


def test_dangling_secret_env_destination_is_rejected_before_tree_move(repo_git, tmp_path, monkeypatch):
    env = repo_git / ".env"
    env.write_text("TEST_ONLY=not-a-secret\n", encoding="utf-8")
    source = repo_git / SP.WORKSPACE
    before = _tree_snapshot(source)
    secret_dir = tmp_path / "fake-secret"
    secret_dir.mkdir()
    missing_target = tmp_path / "missing-secret-target"
    link = secret_dir / ".env"
    try:
        link.symlink_to(missing_target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink unavailable: {exc}")
    moved = {"called": False}

    def forbidden_move(*_args, **_kwargs):
        moved["called"] = True
        raise AssertionError("tree move must not start with dangling destination link")

    monkeypatch.setattr(ST, "_doi_cay", forbidden_move)
    with pytest.raises(SC.ContractError, match="liên kết|điểm nối|đã có"):
        ST.migrate_sang_separate(station=str(tmp_path / "trạm-secret-link"),
                                 kho_secret=str(secret_dir))

    assert not moved["called"] and link.is_symlink() and not missing_target.exists()
    assert _tree_snapshot(source) == before and env.is_file()


def test_source_tree_directory_symlink_is_rejected_before_move(repo_git, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("outside\n", encoding="utf-8")
    link = repo_git / SP.WORKSPACE / "external-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")
    moved = {"called": False}

    def forbidden_move(*_args, **_kwargs):
        moved["called"] = True
        raise AssertionError("tree move must not start before rejecting a symlink entry")

    monkeypatch.setattr(ST, "_doi_cay", forbidden_move)
    target = tmp_path / "trạm-no-symlink"
    with pytest.raises(SC.ContractError, match="symlink|junction|reparse"):
        ST.migrate_sang_separate(station=str(target), kho_secret=str(tmp_path / "fake-secret"))

    assert not moved["called"] and link.is_symlink() and (outside / "keep.txt").is_file()


def test_tuong_tac_go_duong_la_mot_FILE_o_cau_noi_doi_thi_noi_dich_la_FILE_va_ten_duong(repo_git, tmp_path):
    """Cùng thông báo với `--station`: đích là FILE (kèm đường), không phải 'không rỗng'; mã 2 trước câu y/N."""
    f = tmp_path / "la-file"
    f.write_text("x", encoding="utf-8")
    ask = _tra_loi(str(f))                       # chỉ một câu: y/N không được hỏi
    with pytest.raises(SC.ContractError, match="FILE") as e:
        ST.migrate_sang_separate(kho_secret=str(tmp_path / "kho"), ask=ask)
    assert str(f) in str(e.value) and "không rỗng" not in str(e.value)
    assert len(ask.loi_nhac) == 1 and _nguyen_ven(repo_git) and f.read_text(encoding="utf-8") == "x"
