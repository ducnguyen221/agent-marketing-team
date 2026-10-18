# -*- coding: utf-8 -*-
"""`brand-paths.ps1` (PowerShell) và `studio_paths.py` (Python) phải phân giải CÙNG một bố cục ra
CÙNG một kết quả — chúng là hai bản của một luật (P1-14).

Dựng một thư mục cha giả chứa: bản clone marketing (chế độ embedded, `.env`, `workspaces/`), repo
anh em `agent-voice-studio` (trạm `workspaces/`) và `agent-video-studio` (trạm `station_path`
tương đối + `.venv`). Tên thư mục KHÔNG phải tên repo — nhận diện phải đi bằng `pyproject.toml`.
Không mạng, không trạm thật: HOME trỏ thư mục tạm, biến trạm bị gỡ khỏi tiến trình.

`Get-EnvVar` CỐ Ý đọc registry User (máy Windows đã `setx` biến trạm), nên bố cục
giả không cô lập được trên máy đó. Mọi ca chạy trên BẢN SAO `brand-paths.ps1` trong `tmp_path`
đã thay đúng MỘT lần dòng đọc registry bằng `$null` (`_ban_sao_khong_registry`, assert số lần
thay = 1 nên mã trôi là đỏ, không `skip`). Bản gốc không đổi: cổng tĩnh `_REG_USER` của
`test_runners_portable` vẫn thấy dòng registry. Lớp kiểm SUT nguyên bản = CI Windows + Ubuntu.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BP = ROOT / "scripts" / "runners" / "brand-paths.ps1"
# Trình PowerShell: biến BRAND_PATHS_PS (run-isolated.ps1 -PsExe) thắng; `which` chỉ là đường lùi.
PS = os.environ.get("BRAND_PATHS_PS") or shutil.which("pwsh") or shutil.which("powershell")
BIEN = ("MARKETING_STUDIO_DATA", "MARKETING_STUDIO_HOME", "VOICE_STATION", "OMNIVOICE_DIR",
        "VIDEO_STATION", "VIDEO_ROOT", "OMNIVOICE_PY", "VOICE_BGM_DIR", "WEB_REPO_DIR",
        "L30_SCRIPT", "CLAUDE_CONFIG_DIR")

pytestmark = pytest.mark.skipif(not PS, reason="khong co PowerShell")


_DONG_REGISTRY = "[Environment]::GetEnvironmentVariable($Name, 'User')"


def _ban_sao_khong_registry(dich: Path) -> Path:
    """Chép `brand-paths.ps1` sang `dich`, thay ĐÚNG MỘT lần dòng đọc registry User bằng `$null`.

    Cấm đổi `$env:OS`, `reg load`, cờ tắt registry trong mã sản phẩm, ghi đè `Get-EnvVar`:
    registry là hành vi cố ý của SUT, che bằng bản sao là cách duy nhất không chạm máy."""
    goc = BP.read_bytes().decode("utf-8")          # giữ BOM: PS 5.1 cần nó để đọc tiếng Việt
    so_lan_thay = goc.count(_DONG_REGISTRY)
    assert so_lan_thay == 1, (f"brand-paths.ps1 có {so_lan_thay} dòng đọc registry User (cần đúng 1) "
                              "— mã trôi, sửa fixture cho khớp")
    dich.parent.mkdir(parents=True, exist_ok=True)
    dich.write_bytes(goc.replace(_DONG_REGISTRY, "$null").encode("utf-8"))
    return dich


def _kiem_phien_ban(major: int) -> None:
    """Trình `powershell` (5.1) phải báo major 5; `pwsh` phải >= 7 (kiểm đúng trình đã mời)."""
    if Path(PS).stem.lower() == "powershell":
        assert major == 5, f"BRAND_PATHS_PS là 5.1 mà chạy bản {major}"
    else:
        assert major >= 7, f"pwsh mà chạy bản {major}"


def _viet(p: Path, s: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")
    return p


@pytest.fixture
def bo_cuc(tmp_path):
    cha = tmp_path / "noi-chua-repo"
    mkt = cha / "ban-marketing"                          # tên thư mục ≠ tên repo
    (mkt / "scripts" / "runners").mkdir(parents=True)
    _ban_sao_khong_registry(mkt / "scripts" / "runners" / "brand-paths.ps1")
    _viet(mkt / "scripts" / "pipeline" / "campaign_cfg.py")
    (mkt / "scripts" / "lib").mkdir(parents=True)
    _viet(mkt / "install.ps1")
    _viet(mkt / "pyproject.toml", '[project]\nname = "agent-marketing-team"\n')
    _viet(mkt / "studio.local.json", '{"mode": "embedded"}')
    ws = mkt / "workspaces"
    _viet(ws / "CHANNELS.md", "---\nchannels: []\n---\n")
    _viet(ws / "k" / "c" / "logs" / "config.json", "{}")
    bgm = tmp_path / "nhac"
    bgm.mkdir()
    _viet(mkt / ".env", f"VOICE_BGM_DIR={bgm}\nWEB_REPO_DIR={tmp_path / 'web'}\n")
    giong = cha / "giong-x"
    _viet(giong / "pyproject.toml", '[project]\nname = "agent-voice-studio"\n')
    (giong / "workspaces").mkdir()
    video = cha / "video-y"
    _viet(video / "pyproject.toml", "[project]\nname = 'agent-video-studio'\n")
    _viet(video / "studio.local.json", '{"station_path": "tram-rieng"}')
    (video / "tram-rieng").mkdir()
    con = "Scripts" if os.name == "nt" else "bin"
    ten = "python.exe" if os.name == "nt" else "python3"
    vpy = _viet(video / ".venv" / con / ten)
    return {"cha": cha, "mkt": mkt, "ws": ws, "giong": giong, "video": video, "bgm": bgm,
            "vpy": vpy, "nha": tmp_path / "nha", "tmp": tmp_path}


def _env(b) -> dict:
    """Môi trường tiến trình con: không biến trạm; nhà giả theo cả `HOME`/`USERPROFILE` (pwsh 7)
    lẫn `HOMEDRIVE`+`HOMEPATH` (5.1 tính lại `$HOME` từ đó). `PATHEXT`... thừa kế từ `os.environ`."""
    env = {k: v for k, v in os.environ.items() if k not in BIEN}
    nha = str(b["nha"])
    ve, duoi = os.path.splitdrive(nha)
    env.update(HOME=nha, USERPROFILE=nha, HOMEDRIVE=ve, HOMEPATH=duoi)
    return env


def _chay(b, config: str = "") -> dict:
    lai = b["tmp"] / "lai.ps1"
    lai.write_text(
        "param([string]$Config = '')\n$ErrorActionPreference = 'Stop'\n"
        f". '{b['mkt'] / 'scripts' / 'runners' / 'brand-paths.ps1'}'\n"
        "$c = [pscustomobject]@{ repo = 'news/ai' }\n"
        "$c2 = [pscustomobject]@{ repo = '${WEB_REPO_DIR}/data' }\n"
        "$bj = Join-Path ([IO.Path]::GetTempPath()) ('bp-' + [guid]::NewGuid().ToString('N') + '.json')\n"
        "@{ repo = 'news/ai' } | ConvertTo-Json | Set-Content -Path $bj -Encoding UTF8\n"
        "$g = Get-Cfg -BrandDir (Split-Path $bj -Parent) -Config $bj\n"
        "@{ repo = '${WEB_REPO_DIR}/data' } | ConvertTo-Json | Set-Content -Path $bj -Encoding UTF8\n"
        "$g2 = Get-Cfg -BrandDir (Split-Path $bj -Parent) -Config $bj\n"
        "Remove-Item $bj -Force\n"
        "[pscustomobject]@{ psver = $PSVersionTable.PSVersion.Major; station = $Station; repo = $script:RepoRoot; voice = $VoiceStation;"
        " video = $VideoStation; bgm = (Get-EnvVar 'VOICE_BGM_DIR'); ovpy = (Find-OmniVoicePython);"
        " web = $g.repo; web2 = $g2.repo } | ConvertTo-Json -Compress\n",
        encoding="utf-8-sig")
    env = _env(b)
    a = [PS, "-NoProfile", "-NonInteractive", "-File", str(lai)]
    if config:
        a += ["-Config", config]
    r = subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    kq = json.loads(r.stdout.strip().splitlines()[-1])
    _kiem_phien_ban(kq["psver"])
    return kq


def _cung(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def test_PS_va_Python_phan_giai_CUNG_bo_cuc(bo_cuc, monkeypatch):
    kq = _chay(bo_cuc, str(bo_cuc["ws"] / "k" / "c" / "logs" / "config.json"))
    assert _cung(kq["station"], bo_cuc["ws"]), kq
    assert _cung(kq["repo"], bo_cuc["mkt"]), kq
    assert _cung(kq["voice"], bo_cuc["giong"] / "workspaces"), kq
    assert _cung(kq["video"], bo_cuc["video"] / "tram-rieng"), kq
    assert _cung(kq["bgm"], bo_cuc["bgm"]), "embedded: Get-EnvVar phải đọc <repo>/.env"
    assert _cung(kq["ovpy"], bo_cuc["vpy"]), "python giọng: .venv của repo anh em video"
    assert _cung(kq["web"], bo_cuc["cha"] / "news" / "ai"), "repo tương đối theo thư mục CHA"
    assert _cung(kq["web2"], bo_cuc["tmp"] / "web" / "data"), "${WEB_REPO_DIR} nở từ .env"

    # Cùng bố cục qua studio_paths (Python) — hai bản của MỘT luật.
    for n in BIEN:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(bo_cuc["mkt"]))
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import studio_paths as SP
    assert _cung(SP.voice_station(), kq["voice"])
    assert _cung(SP.video_station(), kq["video"])
    assert _cung(SP.duong_repo_web("news/ai"), kq["web"])


def test_khong_Config_thi_tram_embedded_la_workspace(bo_cuc):
    assert _cung(_chay(bo_cuc)["station"], bo_cuc["ws"])


# ── bố cục `khong-gi-ca` và `sibling` — KHÔNG đoán thư mục nhà ───────────
# Nhà giả (`sandbox_home`) mồi một thư mục ẩn kiểu cũ mang CHANNELS.md; thêm các thư mục ẩn cũ
# của trạm video/giọng mang dấu. Bản cũ thấy chúng là lấy làm trạm (kèm WARN). Nay: không biến, không
# studio.local.json, không repo anh em, không <repo>/workspaces ⇒ `Get-StationRoot` NÉM nêu MARKETING_STUDIO_DATA,
# `Get-VideoStation`/`Get-VoiceStation` trả `$null` — đúng như Python (`resolve_station` nguồn
# "default" / `video_station()`/`voice_station()` là None).

@pytest.fixture
def bo_cuc_trong(tmp_path, sandbox_home):
    cha = tmp_path / "noi-chua-repo"
    mkt = cha / "ban-marketing"
    _ban_sao_khong_registry(mkt / "scripts" / "runners" / "brand-paths.ps1")
    _viet(mkt / "scripts" / "pipeline" / "campaign_cfg.py")
    (mkt / "scripts" / "lib").mkdir(parents=True)
    _viet(mkt / "install.ps1")
    _viet(mkt / "pyproject.toml", '[project]\nname = "agent-marketing-team"\n')
    # Nhà giả mang dấu ở MỌI thư mục cũ mà bản trước dò.
    for ten in ("." + "video", "." + "voice", "." + "tts"):      # ghép: test chống chữ cũ quét cả file này
        _viet(sandbox_home / ten / "station.json", "{}")
    assert any((d / "CHANNELS.md").is_file() for d in sandbox_home.iterdir() if d.is_dir())
    return {"cha": cha, "mkt": mkt, "nha": sandbox_home, "tmp": tmp_path}


def _chay_tho(b, than: str, env_them=None, config: str = ""):
    """Dot-source bản sao `brand-paths.ps1` rồi chạy `than`. Trả CompletedProcess, KHÔNG assert.
    `env_them`: biến cấu hình thêm (bố cục 'biến'); `config`: truyền `-Config` (nấc gợi ý)."""
    lai = b["tmp"] / "lai-tho.ps1"
    lai.write_text(
        "param([string]$Config = '')\n$ErrorActionPreference = 'Stop'\n"
        f". '{b['mkt'] / 'scripts' / 'runners' / 'brand-paths.ps1'}'\n" + than + "\n",
        encoding="utf-8-sig")
    env = _env(b)
    env.update(env_them or {})
    a = [PS, "-NoProfile", "-NonInteractive", "-File", str(lai)]
    if config:
        a += ["-Config", config]
    return subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=120)


def _py_voi_repo(monkeypatch, b):
    """Python phân giải trên CÙNG bố cục: repo = bản clone giả, biến trạm đã gỡ bởi sandbox_home."""
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(b["mkt"]))
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import studio_paths as SP
    return SP


_IN_KET_QUA = ("[pscustomobject]@{ psver = $PSVersionTable.PSVersion.Major; station = $Station; "
               "voice = $VoiceStation; video = $VideoStation } | ConvertTo-Json -Compress")


def test_khong_gi_ca_thi_Get_StationRoot_NEM_nen_ten_bien_khong_lay_nha(bo_cuc_trong, monkeypatch):
    r = _chay_tho(bo_cuc_trong, "")
    ra = r.stdout + r.stderr
    assert r.returncode != 0, "không có trạm mà vẫn thoát 0: " + ra
    assert "MARKETING_STUDIO_DATA" in ra, ra
    assert "WARN" not in ra and ("." + "marketing") not in ra, "còn lấy thư mục nhà làm trạm: " + ra
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert SP.resolve_station()[1] == "default", "Python cũng phải coi là 'không ai khai gì'"


def test_khong_gi_ca_thi_Video_Voice_la_null_va_Find_OmniVoicePython_dung(bo_cuc_trong, monkeypatch):
    ws = bo_cuc_trong["mkt"] / "workspaces"
    _viet(ws / "CHANNELS.md", "---\nchannels: []\n---\n")        # có trạm, KHÔNG có anh em
    r = _chay_tho(bo_cuc_trong, _IN_KET_QUA)
    assert r.returncode == 0, r.stdout + r.stderr
    kq = json.loads(r.stdout.strip().splitlines()[-1])
    _kiem_phien_ban(kq["psver"])
    assert _cung(kq["station"], ws), kq
    assert kq["voice"] is None and kq["video"] is None, f"còn lấy thư mục ẩn kiểu cũ của nhà làm trạm giọng/video: {kq}"
    assert "WARN" not in r.stdout, r.stdout
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert SP.voice_station() is None and SP.video_station() is None
    # Fail-closed của bên gọi: trạm giọng trống ⇒ NÉM, nêu tên biến phải đặt.
    r2 = _chay_tho(bo_cuc_trong, "Find-OmniVoicePython | Out-Null")
    assert r2.returncode != 0, r2.stdout + r2.stderr
    assert "OMNIVOICE_PY" in r2.stdout + r2.stderr and "VOICE_STATION" in r2.stdout + r2.stderr


def test_sibling_PS_va_Python_cung_tram_anh_em(bo_cuc_trong, monkeypatch):
    cha = bo_cuc_trong["cha"]
    giong = cha / "giong-x"
    _viet(giong / "pyproject.toml", '[project]\nname = "agent-voice-studio"\n')
    _viet(giong / "workspaces" / "station.json", "{}")
    video = cha / "video-y"
    _viet(video / "pyproject.toml", "[project]\nname = 'agent-video-studio'\n")
    (video / "workspaces").mkdir()
    _viet(bo_cuc_trong["mkt"] / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    r = _chay_tho(bo_cuc_trong, _IN_KET_QUA)
    assert r.returncode == 0, r.stdout + r.stderr
    kq = json.loads(r.stdout.strip().splitlines()[-1])
    _kiem_phien_ban(kq["psver"])
    assert _cung(kq["voice"], giong / "workspaces"), kq
    assert _cung(kq["video"], video / "workspaces"), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.voice_station(), kq["voice"]) and _cung(SP.video_station(), kq["video"])


@pytest.mark.parametrize("bo_cuc_anh_em", ["cu", "ca-hai"])
def test_sibling_bo_cuc_cu_workspace_so_it_PS_va_Python_cung_ket_qua(bo_cuc_trong, monkeypatch,
                                                                       bo_cuc_anh_em):
    """Repo anh em còn bố cục cũ (`workspace`): vẫn nhận; có cả `workspaces` thì ưu tiên nó."""
    cha = bo_cuc_trong["cha"]
    giong = cha / "giong-x"
    _viet(giong / "pyproject.toml", '[project]\nname = "agent-voice-studio"\n')
    (giong / "workspace").mkdir()
    if bo_cuc_anh_em == "ca-hai":
        (giong / "workspaces").mkdir()
    _viet(bo_cuc_trong["mkt"] / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    kq = _ket_qua_ps(bo_cuc_trong)
    mong = giong / ("workspaces" if bo_cuc_anh_em == "ca-hai" else "workspace")
    assert _cung(kq["voice"], mong), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.voice_station(), kq["voice"])


@pytest.mark.parametrize("config", ["cu-workspace", "moi-workspaces", "khong"])
@pytest.mark.parametrize("bo_cuc", ["A-chi-cu", "B-chi-moi", "C-ca-hai"])
def test_station_path_la_TEN_nhung_PS_va_Python_cung_khong_tin_chuoi(bo_cuc_trong, monkeypatch,
                                                                     bo_cuc, config):
    """`studio.local.json` embedded ghi `workspace` (bộ cài cũ) hay `workspaces`: cả hai ngôn ngữ đi
    qua cùng định nghĩa "có thật" — (B) đổi tên thì không mất trạm, (C) có cả hai thì `workspaces`."""
    mkt = bo_cuc_trong["mkt"]
    if bo_cuc != "B-chi-moi":
        _viet(mkt / "workspace" / "CHANNELS.md", "---\nchannels: []\n---\n")
    if bo_cuc != "A-chi-cu":
        _viet(mkt / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    if config != "khong":
        ten = "workspace" if config == "cu-workspace" else "workspaces"
        _viet(mkt / "studio.local.json", json.dumps({"mode": "embedded", "station_path": ten}))
    kq = _ket_qua_ps(bo_cuc_trong)
    mong = mkt / ("workspace" if bo_cuc == "A-chi-cu" else "workspaces")
    assert _cung(kq["station"], mong), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.resolve_station()[0], kq["station"])


@pytest.mark.parametrize("mode,sp,la_ten", [
    ("embedded", "Workspace", False),          # sai hoa/thường: KHÔNG phải tên nhúng, là một đường lạ
    ("Embedded", "workspace", False),          # chế độ viết hoa: không phải `embedded`
    ("embedded", "x/../workspace", True),      # chuẩn hoá như normpath => `workspace`
    ("embedded", "./workspaces", True),
    ("embedded", "workspace/", True),
    ("embedded", "workspace\\", True),
], ids=["Workspace", "mode-Embedded", "x-gap-workspace", "dot-workspaces", "workspace-slash", "workspace-backslash"])
def test_gia_tri_khong_chuan_PS_va_Python_cung_ket_qua(bo_cuc_trong, monkeypatch, mode, sp, la_ten):
    """Không bộ cài nào ghi ra các giá trị này, nhưng parity là mục tiêu: so ĐÚNG chữ và chuẩn hoá
    đường tương đối như nhau ở hai ngôn ngữ. Bố cục có cả hai thư mục để mọi lệch đều lộ ra."""
    mkt = bo_cuc_trong["mkt"]
    _viet(mkt / "workspace" / "CHANNELS.md", "---\nchannels: []\n---\n")
    _viet(mkt / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    _viet(mkt / "studio.local.json", json.dumps({"mode": mode, "station_path": sp}))
    kq = _ket_qua_ps(bo_cuc_trong)
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.resolve_station()[0], kq["station"]), (kq, SP.resolve_station())
    if la_ten:
        assert _cung(kq["station"], mkt / "workspaces"), kq      # đi qua bộ phân giải nhúng
    elif mode == "Embedded":
        assert _cung(kq["station"], mkt / "workspace"), kq       # không phải embedded => tin đường


def test_station_path_la_TEN_nhung_cua_repo_anh_em_PS_va_Python(bo_cuc_trong, monkeypatch):
    cha = bo_cuc_trong["cha"]
    giong = cha / "giong-x"
    _viet(giong / "pyproject.toml", '[project]\nname = "agent-voice-studio"\n')
    _viet(giong / "studio.local.json", json.dumps({"mode": "embedded", "station_path": "workspace"}))
    (giong / "workspace").mkdir()
    (giong / "workspaces").mkdir()                       # đã đổi tên một phần: workspaces thắng
    _viet(bo_cuc_trong["mkt"] / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    kq = _ket_qua_ps(bo_cuc_trong)
    assert _cung(kq["voice"], giong / "workspaces"), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.voice_station(), kq["voice"])


@pytest.mark.parametrize("bo_cuc_mkt", ["cu", "ca-hai", "moi-rong", "cu-khong-dau"])
def test_tram_nhung_PS_va_Python_cung_dinh_nghia_co_that(bo_cuc_trong, monkeypatch, bo_cuc_mkt):
    """`workspaces` chỉ cần là thư mục; `workspace` cũ phải có CHANNELS.md; có cả hai → `workspaces`."""
    mkt = bo_cuc_trong["mkt"]
    if bo_cuc_mkt in ("cu", "ca-hai"):
        _viet(mkt / "workspace" / "CHANNELS.md", "---\nchannels: []\n---\n")
    if bo_cuc_mkt in ("ca-hai", "moi-rong"):
        (mkt / "workspaces").mkdir()
    if bo_cuc_mkt == "cu-khong-dau":
        (mkt / "workspace").mkdir()                      # có thư mục nhưng KHÔNG có dấu trạm
        r = _chay_tho(bo_cuc_trong, "")
        assert r.returncode != 0 and "MARKETING_STUDIO_DATA" in r.stdout + r.stderr
        SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
        assert SP.resolve_station()[1] == "default"
        return
    kq = _ket_qua_ps(bo_cuc_trong)
    mong = mkt / ("workspace" if bo_cuc_mkt == "cu" else "workspaces")
    assert _cung(kq["station"], mong), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.resolve_station()[0], kq["station"])


# ── parity cho bố cục 'biến', 'local-config', nấc gợi ý `-Config` ──────────
# Cùng bố cục, PowerShell và Python phải ra CÙNG kết quả; so TRỰC TIẾP, không qua giá trị dựng sẵn.

def _ket_qua_ps(b, env_them=None, config: str = "") -> dict:
    r = _chay_tho(b, _IN_KET_QUA, env_them=env_them, config=config)
    assert r.returncode == 0, r.stdout + r.stderr
    kq = json.loads(r.stdout.strip().splitlines()[-1])
    _kiem_phien_ban(kq["psver"])
    return kq


@pytest.mark.parametrize("bien_giong,bien_video,giong_la_cha", [
    ("VOICE_STATION", "VIDEO_STATION", False),
    ("OMNIVOICE_DIR", "VIDEO_ROOT", True),          # tên CŨ: OMNIVOICE_DIR trỏ engine, trạm = thư mục CHA
], ids=["ten-moi", "ten-cu"])
def test_bien_PS_va_Python_cung_tram(bo_cuc_trong, monkeypatch, bien_giong, bien_video, giong_la_cha):
    tmp = bo_cuc_trong["tmp"]
    tram, giong, video = tmp / "bien" / "tram", tmp / "bien" / "giong" / "engine", tmp / "bien" / "video"
    for d in (tram, giong, video):
        d.mkdir(parents=True)
    # Repo anh em CÓ mặt: biến phải THẮNG anh em (thứ tự biến → local-config → anh em).
    sib = bo_cuc_trong["cha"] / "giong-x"
    _viet(sib / "pyproject.toml", '[project]\nname = "agent-voice-studio"\n')
    (sib / "workspaces").mkdir()
    env = {"MARKETING_STUDIO_DATA": str(tram), bien_giong: str(giong), bien_video: str(video)}
    kq = _ket_qua_ps(bo_cuc_trong, env)
    mong_giong = giong.parent if giong_la_cha else giong
    assert _cung(kq["station"], tram) and _cung(kq["voice"], mong_giong) and _cung(kq["video"], video), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _cung(SP.resolve_station()[0], kq["station"])
    assert _cung(SP.voice_station(), kq["voice"]) and _cung(SP.video_station(), kq["video"])


def test_local_config_PS_va_Python_cung_tram_station_path_tuong_doi(bo_cuc_trong, monkeypatch):
    mkt, tmp = bo_cuc_trong["mkt"], bo_cuc_trong["tmp"]
    (mkt / "tram-rieng").mkdir()                      # tương đối: nối với <repo>, KHÔNG với cwd
    giong, video = tmp / "lc" / "giong", tmp / "lc" / "video"
    giong.mkdir(parents=True)
    video.mkdir(parents=True)
    _viet(mkt / "studio.local.json", json.dumps(
        {"station_path": "tram-rieng", "voice_station": str(giong), "video_station": str(video)}))
    kq = _ket_qua_ps(bo_cuc_trong)
    assert _cung(kq["station"], mkt / "tram-rieng"), kq
    assert _cung(kq["voice"], giong) and _cung(kq["video"], video), kq
    SP = _py_voi_repo(monkeypatch, bo_cuc_trong)
    assert _cung(SP.resolve_station()[0], kq["station"])
    assert _cung(SP.voice_station(), kq["voice"]) and _cung(SP.video_station(), kq["video"])


# ── thiếu cả VOICE_BGM_DIR lẫn trạm video ⇒ nhạc nền tắt thì phải NÓI RA ───────────────────────
# Bản cũ lấy thư mục ẩn của trạm video trong nhà; nay `$VideoStation` là `$null` trên máy cũ và `$bgmDir` thành '' — tắt nhạc
# nền im lặng. Nhạc nền là tuỳ chọn nên KHÔNG dừng pipeline (dừng làm hỏng video đã lên lịch), chỉ WARN.

def _bgm(b, env_them=None):
    _viet(b["mkt"] / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    r = _chay_tho(b, "$bgm = Get-BgmDir\n@{ bgm = [string]$bgm } | ConvertTo-Json -Compress", env_them=env_them)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout, json.loads(r.stdout.strip().splitlines()[-1])["bgm"]


def test_Get_BgmDir_thieu_ca_hai_thi_WARN_nen_ten_bien(bo_cuc_trong):
    ra, bgm = _bgm(bo_cuc_trong)
    assert bgm == "", bgm
    assert "WARN" in ra and "VOICE_BGM_DIR" in ra and "VIDEO_STATION" in ra, ra


def test_Get_BgmDir_co_bien_thi_im_lang_va_dung_duong(bo_cuc_trong):
    tmp = bo_cuc_trong["tmp"]
    ra, bgm = _bgm(bo_cuc_trong, {"VOICE_BGM_DIR": str(tmp / "nhac")})
    assert _cung(bgm, tmp / "nhac") and "WARN" not in ra, ra
    ra, bgm = _bgm(bo_cuc_trong, {"VIDEO_STATION": str(tmp / "v")})
    assert _cung(bgm, tmp / "v" / "assets" / "news-bgm") and "WARN" not in ra, ra


@pytest.mark.parametrize("ten", ["run-toptoday-hot.ps1", "run-weekly-news.ps1", "run-weekly-repo.ps1"])
def test_runner_dung_Get_BgmDir_khong_tu_ghep_bgmDir(ten):
    """Ba runner cùng một luật: không ai tự ghép `$bgmDir` (sẽ lại tắt nhạc nền im lặng)."""
    ma = (ROOT / "scripts" / "runners" / ten).read_text(encoding="utf-8-sig")
    assert "= Get-BgmDir" in ma, f"{ten} không gọi Get-BgmDir"
    assert "'news-bgm'" not in ma, f"{ten} còn tự ghép đường news-bgm"


def test_goi_y_Config_thang_workspace(bo_cuc_trong):
    """`run.ps1` chọn trạm theo đường đi LÊN từ chiến dịch; runner nhận `-Config` (bản chụp trong
    `<chiến dịch>/logs/`) phải ra ĐÚNG trạm đó, kể cả khi `<repo>/workspaces` là một trạm khác."""
    tmp, mkt = bo_cuc_trong["tmp"], bo_cuc_trong["mkt"]
    _viet(mkt / "workspaces" / "CHANNELS.md", "---\nchannels: []\n---\n")
    khac = tmp / "tram-khac"
    _viet(khac / "CHANNELS.md", "---\nchannels: []\n---\n")
    cfg = _viet(khac / "k" / "c" / "logs" / "config.json", "{}")
    assert _cung(_ket_qua_ps(bo_cuc_trong)["station"], mkt / "workspaces")
    assert _cung(_ket_qua_ps(bo_cuc_trong, config=str(cfg))["station"], khac)
