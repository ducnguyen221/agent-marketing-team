# -*- coding: utf-8 -*-
"""SPR-61 TK8 — marketing tìm python của venv giọng ở `runtime/` của OpcOS.

Venv giọng nay ở `R/venvs/agent-voice-studio/omnivoice` (chủ: repo `agent-voice-studio`); marketing chỉ
`use` nó (tệp `opcos-runtime.json`). Thứ tự phân giải python giọng, MỘT luật cho cả hai bản:

    OMNIVOICE_PY → station.json: venv → R/venvs/agent-voice-studio/omnivoice (nếu có R)
    → <trạm>/omnivoice/.venv → .venv repo anh em (video rồi voice)

Gốc R theo hợp đồng `runtime-resource-v1` (véc-tơ VT1–VT9). Test thuần: venv giả chỉ là file rỗng
`python`, không cài gì, không đọc `~/OpcOS` thật (HOME trỏ cây tạm, biến OPCOS_* bị gỡ). Máy gốc có
`OPCOS_RUNTIME` thật ở cả tiến trình lẫn registry User nên PowerShell chạy trên BẢN SAO bỏ dòng registry
(cùng idiom `test_runner_brand_paths`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "runners"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
import studio_contract as SC  # noqa: E402
import studio_paths as SP  # noqa: E402
import voice as V  # noqa: E402

BP = ROOT / "scripts" / "runners" / "brand-paths.ps1"
PS = os.environ.get("BRAND_PATHS_PS") or shutil.which("pwsh") or shutil.which("powershell")
WIN = os.name == "nt"
CON = "Scripts" if WIN else "bin"
TEN_PY = "python.exe" if WIN else "python"
REPO_KEY = "agent-voice-studio"

# ── Véc-tơ chép từ khối `vectors` của system/workshop/planning/contracts/runtime-resource-v1.json
#    (đường POSIX, HOME giả = /h; repoKey đổi thành chủ venv giọng).
VECTORS = [
    ("VT1", {"OPCOS_RUNTIME": "/r", "OPCOS_ROOT": "/o"}, True, "/r/venvs/agent-voice-studio/omnivoice"),
    ("VT2", {"OPCOS_ROOT": "/o"}, False, "/o/runtime/venvs/agent-voice-studio/omnivoice"),
    ("VT3", {}, True, "/h/OpcOS/runtime/venvs/agent-voice-studio/omnivoice"),
    ("VT4", {}, False, None),                       # RT_NO_OPCOS — không phải lỗi, dùng đường cũ
]
BAD = [
    ("VT5", "venvs", REPO_KEY, "Bad_Key"),
    ("VT6", "models", REPO_KEY, "omnivoice"),
    ("VT7", "venvs", REPO_KEY, "con"),
    ("VT9", "venvs", "shared", "omnivoice"),
]


def _isfile_gia(co_paths_json):
    return lambda p: bool(co_paths_json) and Path(p).as_posix() == "/h/OpcOS/paths.json"


@pytest.mark.parametrize("vid,env,paths,mong", VECTORS, ids=[v[0] for v in VECTORS])
def test_vectors_vt1_vt4(vid, env, paths, mong):
    got = SP.runtime_resource("venvs", REPO_KEY, "omnivoice", env=env, home="/h", isfile=_isfile_gia(paths))
    if mong is None:
        assert got is None
    else:
        assert PurePosixPath(Path(got).as_posix()) == PurePosixPath(mong)


@pytest.mark.parametrize("vid,cat,repo,key", BAD, ids=[b[0] for b in BAD])
def test_bad_keys(vid, cat, repo, key):
    with pytest.raises(ValueError, match="RT_BAD_KEY"):
        SP.runtime_resource(cat, repo, key, env={"OPCOS_RUNTIME": "/r"}, home="/h",
                            isfile=_isfile_gia(False))


def test_bad_key_cung_loi_khi_may_khong_co_opcos():
    """Khoá sai báo lỗi TRƯỚC khi tìm R — máy không OpcOS cũng không nuốt khoá sai."""
    with pytest.raises(ValueError, match="RT_BAD_KEY"):
        SP.runtime_resource("venvs", REPO_KEY, "Bad_Key", env={}, home="/h", isfile=_isfile_gia(False))


# ── dựng máy giả ─────────────────────────────────────────────────────────────────────

def _venv(goc: Path) -> Path:
    py = goc / CON / TEN_PY
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    return py


@pytest.fixture
def may(tmp_path, monkeypatch):
    """Nhà giả (4 biến home), không biến trạm/OPCOS_*/OMNIVOICE_PY; một trạm giọng giả; một repo marketing giả."""
    nha = tmp_path / "nha"
    nha.mkdir()
    ve, duoi = os.path.splitdrive(str(nha))
    for k, v in (("HOME", str(nha)), ("USERPROFILE", str(nha)), ("HOMEDRIVE", ve), ("HOMEPATH", duoi)):
        monkeypatch.setenv(k, v)
    for ten in ("OPCOS_RUNTIME", "OPCOS_ROOT", "OMNIVOICE_PY", "OMNIVOICE_DIR", "VOICE_STATION",
                "VIDEO_STATION", "VIDEO_ROOT", "MARKETING_STUDIO_DATA", "OPCOS_WORKSPACES"):
        monkeypatch.delenv(ten, raising=False)
    repo = tmp_path / "cha" / "marketing"
    (repo / "scripts" / "lib").mkdir(parents=True)
    (repo / "install.ps1").write_text("", encoding="utf-8")
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(repo))
    tram = tmp_path / "tram-giong"
    tram.mkdir()
    monkeypatch.setenv("VOICE_STATION", str(tram))
    return {"nha": nha, "tram": tram, "repo": repo, "tmp": tmp_path, "mp": monkeypatch}


def _R(may, dung="env") -> Path:
    """Dựng R giả có venv giọng; `env` ⇒ OPCOS_RUNTIME, `paths` ⇒ chỉ `~/OpcOS/paths.json`."""
    if dung == "env":
        r = may["tmp"] / "R"
        may["mp"].setenv("OPCOS_RUNTIME", str(r))
    else:
        (may["nha"] / "OpcOS").mkdir(exist_ok=True)
        (may["nha"] / "OpcOS" / "paths.json").write_text("{}", encoding="utf-8")
        r = may["nha"] / "OpcOS" / "runtime"
    _venv(r / "venvs" / REPO_KEY / "omnivoice")
    return r


def _py_R(r: Path) -> Path:
    return r / "venvs" / REPO_KEY / "omnivoice" / CON / TEN_PY


def _py_ps(may, thu_muc_ps: Path, kich_ban: str = "Find-OmniVoicePython"):
    """Chạy `Find-OmniVoicePython` trong PowerShell trên bản sao brand-paths không registry -> (ma, ra)."""
    goc = BP.read_bytes().decode("utf-8")
    dong = "[Environment]::GetEnvironmentVariable($Name, 'User')"
    assert goc.count(dong) == 1, "dòng đọc registry của Get-EnvVar trôi — sửa fixture"
    thu_muc_ps.mkdir(parents=True, exist_ok=True)
    ban = thu_muc_ps / "brand-paths.ps1"
    ban.write_bytes(goc.replace(dong, "$null").encode("utf-8"))
    lai = thu_muc_ps / "lai.ps1"
    lai.write_text(f"$ErrorActionPreference = 'Stop'\n. '{ban}'\n{kich_ban}\n", encoding="utf-8-sig")
    nd = thu_muc_ps / "tram-noi-dung"                          # dot-source cần một trạm nội dung hợp lệ
    nd.mkdir(exist_ok=True)
    (nd / "CHANNELS.md").write_text("---\nschema: channels/1\nchannels: []\n---\n", encoding="utf-8")
    env = dict(os.environ, MARKETING_STUDIO_DATA=str(nd))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-File", str(lai)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()


def _cung(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a).strip())) == os.path.normcase(os.path.realpath(str(b)))


cho_ps = pytest.mark.skipif(not PS, reason="khong co PowerShell")


# ── Python: thứ tự phân giải ─────────────────────────────────────────────────────────

def test_absolute_station_venv_python(may):
    ngoai = may["tmp"] / "venv-tuyet-doi"
    py = _venv(ngoai)
    (may["tram"] / "station.json").write_text(json.dumps({"venv": str(ngoai)}), encoding="utf-8")
    _R(may)                                                  # có R nhưng station.json vẫn thắng
    assert _cung(V.python_exe(may["tram"]), py)
    assert V.python_exe_source(may["tram"])[1] == "station.json"


@cho_ps
def test_absolute_station_venv_powershell(may):
    ngoai = may["tmp"] / "venv-tuyet-doi"
    py = _venv(ngoai)
    (may["tram"] / "station.json").write_text(json.dumps({"venv": str(ngoai)}), encoding="utf-8")
    _R(may)
    ma, ra = _py_ps(may, may["tmp"] / "ps1")
    assert ma == 0, ra
    assert _cung(ra.splitlines()[-1], py), ra


def test_omnivoice_py_thang_tat_ca(may):
    _R(may)
    may["mp"].setenv("OMNIVOICE_PY", "/x/python")
    assert V.python_exe_source(may["tram"]) == (str(Path("/x/python")), "OMNIVOICE_PY")


def test_runtime_fallback_before_station(may):
    r = _R(may)
    _venv(may["tram"] / "omnivoice" / ".venv")
    py, nguon = V.python_exe_source(may["tram"])
    assert _cung(py, _py_R(r)) and nguon == "runtime"
    assert _cung(V.python_exe(may["tram"]), _py_R(r))


def test_runtime_qua_paths_json(may):
    r = _R(may, dung="paths")
    assert _cung(V.python_exe(may["tram"]), _py_R(r))


@cho_ps
def test_runtime_fallback_before_station_powershell(may):
    r = _R(may)
    _venv(may["tram"] / "omnivoice" / ".venv")
    ma, ra = _py_ps(may, may["tmp"] / "ps1")
    assert ma == 0, ra
    assert _cung(ra.splitlines()[-1], _py_R(r)), ra


@cho_ps
def test_runtime_qua_paths_json_powershell(may):
    r = _R(may, dung="paths")
    ma, ra = _py_ps(may, may["tmp"] / "ps1")
    assert ma == 0, ra
    assert _cung(ra.splitlines()[-1], _py_R(r)), ra


def test_r_co_nhung_chua_cai_venv_thi_roi_xuong_tram(may):
    may["mp"].setenv("OPCOS_RUNTIME", str(may["tmp"] / "R-rong"))
    py = _venv(may["tram"] / "omnivoice" / ".venv")
    assert V.python_exe_source(may["tram"]) == (str(py), "trạm")


def test_no_opcos_keeps_old_order(may):
    # trạm trước repo anh em, đúng thứ tự cũ; không R
    py_tram = _venv(may["tram"] / "omnivoice" / ".venv")
    cha = may["repo"].parent
    (cha / "video-x").mkdir()
    (cha / "video-x" / "pyproject.toml").write_text('[project]\nname = "agent-video-studio"\n', encoding="utf-8")
    py_video = _venv(cha / "video-x" / ".venv")
    assert SP.runtime_root() is None
    assert V.python_exe_source(may["tram"]) == (str(py_tram), "trạm")
    # bỏ venv trạm -> rơi xuống repo anh em
    py_tram.unlink()
    py, nguon = V.python_exe_source(may["tram"])
    assert _cung(py, py_video) and nguon == "repo anh em"


@cho_ps
def test_no_opcos_keeps_old_order_powershell(may):
    py_tram = _venv(may["tram"] / "omnivoice" / ".venv")
    cha = may["repo"].parent
    (cha / "video-x").mkdir()
    (cha / "video-x" / "pyproject.toml").write_text('[project]\nname = "agent-video-studio"\n', encoding="utf-8")
    _venv(cha / "video-x" / ".venv")
    ma, ra = _py_ps(may, may["tmp"] / "ps1")
    assert ma == 0, ra
    assert _cung(ra.splitlines()[-1], py_tram), ra


def test_thieu_ca_ba_thi_loi_liet_ke_ung_vien_runtime_va_goi_y_ensure(may):
    may["mp"].setenv("OPCOS_RUNTIME", str(may["tmp"] / "R-rong"))
    with pytest.raises(SC.StationMissing) as e:
        V.python_exe(may["tram"])
    msg = str(e.value)
    assert "R-rong" in msg and "opcos-runtime ensure --repo-dir" in msg


def test_thieu_khi_khong_co_R_thi_khong_goi_y_ensure(may):
    with pytest.raises(SC.StationMissing) as e:
        V.python_exe(may["tram"])
    assert "opcos-runtime ensure" not in str(e.value)


# ── tệp nhu cầu ──────────────────────────────────────────────────────────────────────

NEED_KEYS = {"scope", "category", "key", "engine", "version", "repo", "python", "install", "paths"}
INSTALL_KEYS = {"package", "torch", "requirements", "constraints", "kind"}
MUOI_GOI = ("av", "beautifulsoup4", "faster_whisper", "google_api_python_client", "google_auth_httplib2",
            "google_auth_oauthlib", "httplib2", "lxml", "openpyxl", "yt_dlp")


def _chuan(ten: str) -> str:
    return ten.lower().replace("-", "_")


def test_needs_file_use_scope():
    d = json.loads((ROOT / "opcos-runtime.json").read_text(encoding="utf-8"))
    assert set(d) == {"schema", "repoKey", "needs"}
    assert d["schema"] == "opcos-runtime-needs/1" and d["repoKey"] == "agent-marketing-team"
    assert len(d["needs"]) == 1
    n = d["needs"][0]
    assert set(n) <= NEED_KEYS and set(n.get("install", {})) <= INSTALL_KEYS
    assert (n["scope"], n["category"], n["repo"], n["key"]) == ("use", "venvs", REPO_KEY, "omnivoice")
    reqs = n["install"]["requirements"]
    assert reqs == ["requirements-runners.txt"]
    cac_goi = set()
    for dong in (ROOT / reqs[0]).read_text(encoding="utf-8").splitlines():
        dong = dong.split("#")[0].strip()
        if dong:
            cac_goi.add(_chuan(__import__("re").split(r"[<>=!~\[; ]", dong)[0]))
    thieu = [g for g in MUOI_GOI + ("requests",) if g not in cac_goi]
    assert not thieu, f"requirements-runners.txt thiếu {thieu}"


# ── doctor in nguồn python giọng ─────────────────────────────────────────────────────

def test_doctor_in_nguon_runtime(may):
    import doctor as DR
    r = _R(may)
    (may["tram"] / "station.json").write_text(
        json.dumps({"contract": "1.0.0", "venv": "omnivoice/.venv", "engine_dir": "omnivoice"}), encoding="utf-8")
    tram = may["tmp"] / "tram-nd"
    tram.mkdir()
    (tram / "CHANNELS.md").write_text("---\nschema: channels/1\nchannels: []\n---\n", encoding="utf-8")
    may["mp"].setenv("MARKETING_STUDIO_DATA", str(tram))
    kq = DR.kham()
    dong = [x for x in kq["info"] + kq["warn"] + kq["fail"] if "python giọng" in x]
    assert dong, kq
    assert str(_py_R(r)) in dong[0] and "runtime" in dong[0], dong


def test_doctor_in_nguon_bien_omnivoice_py(may):
    import doctor as DR
    (may["tram"] / "station.json").write_text(json.dumps({"contract": "1.0.0"}), encoding="utf-8")
    tram = may["tmp"] / "tram-nd"
    tram.mkdir()
    (tram / "CHANNELS.md").write_text("---\nschema: channels/1\nchannels: []\n---\n", encoding="utf-8")
    may["mp"].setenv("MARKETING_STUDIO_DATA", str(tram))
    may["mp"].setenv("OMNIVOICE_PY", sys.executable)
    kq = DR.kham()
    dong = [x for x in kq["info"] + kq["warn"] + kq["fail"] if "python giọng" in x]
    assert dong and "OMNIVOICE_PY" in dong[0], kq


# ── install_launchd: đường chờ ───────────────────────────────────────────────────────

def test_launchd_duong_cho_duoi_R(may):
    import install_launchd as IL
    r = may["tmp"] / "R-cho"                                  # chưa cài venv
    may["mp"].setenv("OPCOS_RUNTIME", str(r))
    got = Path(IL._omnivoice_py(may["tram"]))
    assert _cung(got.parent.parent, r / "venvs" / REPO_KEY / "omnivoice")
    assert got.parent.name == CON and got.name == "python"


def test_launchd_khong_R_thi_duong_cho_cu(may):
    import install_launchd as IL
    got = Path(IL._omnivoice_py(may["tram"]))
    assert _cung(got.parent.parent, may["tram"] / "omnivoice" / ".venv")


def test_launchd_phan_giai_duoc_thi_dung_python_exe(may):
    import install_launchd as IL
    r = _R(may)
    assert _cung(IL._omnivoice_py(may["tram"]), _py_R(r))


# ── bộ cài chỉ IN hướng dẫn ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tep", ["install.ps1", "install.sh"])
def test_bo_cai_in_lenh_ensure_nhung_khong_goi(tep):
    s = (ROOT / tep).read_text(encoding="utf-8")
    assert "opcos-runtime" in s and "ensure --repo-dir" in s
    # chỉ in: không có dòng nào gọi trực tiếp CLI với `ensure` ngoài lệnh in ra
    for dong in s.splitlines():
        if "ensure" in dong:
            assert any(t in dong for t in ("noi ", "Say ", "echo", "Write-Host", "printf", "#")), dong
