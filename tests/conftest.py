# -*- coding: utf-8 -*-
"""Ép UTF-8 cho MỌI tiến trình con mà test sinh ra.

Vì sao cần: test chạy script bằng `subprocess.run(..., encoding="utf-8")` rồi đọc
`stderr`. Trên Windows máy sạch (không có `PYTHONUTF8`/`PYTHONIOENCODING` trong môi
trường), tiến trình con ghi stderr bằng cp1252 — `…` thành byte `0x85`, tiếng Việt vỡ —
và `r.stderr` về `None`, test nổ `TypeError` ở chỗ chẳng liên quan gì tới thứ nó đang kiểm.

Đây KHÔNG phải cách vá lỗi encoding của script: mỗi entrypoint đã tự
`sys.stderr.reconfigure(encoding="utf-8")`. File này chỉ khiến bộ test **giống máy sạch
hơn**, và có một test riêng (`test_no_env_dependency_utf8`) khẳng định script chạy đúng
NGAY CẢ KHI biến môi trường bị gỡ sạch.

Đã trả giá một lần: bộ test xanh suốt vì phiên làm việc export `PYTHONIOENCODING=utf-8`
ở mọi lệnh, trong khi người clone về chạy `pytest` thì 6 test đỏ.
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

_REPO_THAT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_THAT / "scripts" / "lib"))
import studio_paths as _SP  # noqa: E402


@pytest.fixture(autouse=True)
def _utf8_cho_tien_trinh_con(monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")


@pytest.fixture(autouse=True)
def _khong_cham_secret_that(monkeypatch):
    """P1-18 (30/09/2026): test KHÔNG BAO GIỜ thấy con trỏ secret của máy đang chạy.

    Máy chạy lịch (embedded) có `<repo>/.env` điền `TG_CONFIG`, `YT_TOKEN_PATH`… trỏ vào
    `~/.secret/**` thật. Mac mini: điền `.env` xong thì `pytest` trần đỏ 5 ca, một thông điệp
    assert in ra mẩu cấu hình Telegram thật, và một test chạy `notify_run.py` như tiến trình
    con đã có đường gửi tin thật. Hai lớp chặn, cả hai đi theo môi trường nên phủ luôn tiến
    trình con:
      · gỡ mọi biến con trỏ bí mật (kể cả hậu tố theo kênh) và `TG_*` của phiên;
      · `studio_paths.BIEN_CHAN_ENV_FILE` = bản clone đang test ⇒ `.env` CỦA NÓ không được
        đọc; repo giả trong thư mục tạm vẫn đọc `.env` của chính nó như thường.
    Test cần con trỏ thì tự `monkeypatch.setenv` sau fixture này. Cổng: job CI "cài embedded
    rồi pytest" dựng `.env` + `~/.secret` GIẢ trước khi chạy."""
    for ten in list(os.environ):
        if _SP.la_con_tro_bi_mat(ten) or ten.startswith("TG_"):
            monkeypatch.delenv(ten, raising=False)
    monkeypatch.setenv(_SP.BIEN_CHAN_ENV_FILE, str(_REPO_THAT))


@pytest.fixture(autouse=True)
def _khong_thay_tram_that(monkeypatch):
    """Test KHÔNG BAO GIỜ thấy trạm thật của máy đang chạy.

    Biến User trên máy chạy thật (`MARKETING_STUDIO_DATA`, `MARKETING_STUDIO_HOME`,
    `OPCOS_WORKSPACES`…) trỏ trạm và checkout thật; fixture trên chỉ gỡ secret. Gỡ sạch bốn
    biến rồi đặt `MARKETING_STUDIO_HOME` = bản clone đang test, nên `repo_root()` luôn về đúng
    worktree này chứ không về checkout chính. Test cần biến nào thì tự `setenv` sau fixture này."""
    for ten in ("MARKETING_STUDIO_DATA", "MARKETING_STUDIO_HOME", "OPCOS_WORKSPACES",
                "OPCOS_ROOT"):
        monkeypatch.delenv(ten, raising=False)
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(_REPO_THAT))


# Biến trạm/OpcOS mà `sandbox_home` gỡ (cùng danh sách với video/voice).
_BIEN_TRAM_SANDBOX = ("VIDEO_STATION", "VIDEO_ROOT", "VOICE_STATION", "OMNIVOICE_DIR",
                      "MARKETING_STUDIO_DATA", "MARKETING_STUDIO_HOME", "VIDEO_STUDIO_REPO",
                      "VOICE_STUDIO_REPO", "OPCOS_WORKSPACES", "OPCOS_ROOT")


@pytest.fixture
def sandbox_home(tmp_path, monkeypatch):
    """Nhà GIẢ không junction: `tmp_path/home` có một thư mục ẩn kiểu cũ mang `CHANNELS.md` MỒI
    (một trạm giả; tên ghép bằng phép cộng chuỗi để test chống chữ cũ không bắt chính nó).

    Đặt cả bốn biến nhà — Python `expanduser` đọc `HOME`/`USERPROFILE`, tiến trình con PowerShell
    5.1 tính lại từ `HOMEDRIVE`+`HOMEPATH` — và gỡ mọi biến trạm/`OPCOS_*`. Dùng để chứng minh
    không đường nào dò thư mục trong nhà làm trạm. Đặt TRƯỚC `repo_gia` khi dùng chung (fixture này
    gỡ `MARKETING_STUDIO_HOME`; `repo_gia` đặt lại). Không symlink/junction."""
    nha = tmp_path / "home"
    nha.mkdir()
    ve, duoi = os.path.splitdrive(str(nha))
    monkeypatch.setenv("HOME", str(nha))
    monkeypatch.setenv("USERPROFILE", str(nha))
    monkeypatch.setenv("HOMEDRIVE", ve)
    monkeypatch.setenv("HOMEPATH", duoi)
    for ten in _BIEN_TRAM_SANDBOX:
        monkeypatch.delenv(ten, raising=False)
    # Hai biến checkout ĐẶT (không gỡ) trỏ thư mục rỗng trong nhà giả: gỡ thì resolver tự dò ra checkout thật.
    for ten, con in (("VIDEO_STUDIO_REPO", "no-video-repo"), ("VOICE_STUDIO_REPO", "no-voice-repo")):
        (nha / con).mkdir()
        monkeypatch.setenv(ten, str(nha / con))
    moi = nha / ("." + "marketing")
    moi.mkdir()
    (moi / "CHANNELS.md").write_text("---\nschema: channels/1\nchannels: []\n---\n",
                                    encoding="utf-8")
    return nha


def pytest_report_header(config):
    return (f"encoding máy: PYTHONUTF8={os.environ.get('PYTHONUTF8', '(không đặt)')} · "
            f"PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING', '(không đặt)')}")


def pytest_configure(config):
    """CI đòi PowerShell THẬT: thiếu thì dừng cả lượt, không để test tự `skip`.

    Ba file test (`test_run_args`, `test_runner_stderr`, `test_ps1_portable`) tự bỏ qua khi
    máy không có PowerShell — hợp lý cho người clone về chạy thử, nhưng trên CI thì "bỏ qua"
    trông y hệt "xanh": runner macOS thiếu `pwsh` sẽ báo CI qua mà chưa chạy một dòng `.ps1`
    nào. Workflow đặt `MARKETING_STUDIO_REQUIRE_POWERSHELL=1` để biến im lặng đó thành lỗi.
    """
    if os.environ.get("MARKETING_STUDIO_REQUIRE_POWERSHELL") == "1" and not (
            shutil.which("powershell") or shutil.which("pwsh")):
        raise pytest.UsageError(
            # Khong dau co chu dich: pytest in loi nay qua console cp1252 cua runner Windows.
            "MARKETING_STUDIO_REQUIRE_POWERSHELL=1 nhung khong thay `powershell`/`pwsh` "
            "tren PATH - cai PowerShell 7 truoc khi chay test (cac test .ps1 se bi skip).")


@pytest.fixture
def repo_gia(tmp_path, monkeypatch):
    """Bản clone GIẢ, cô lập: `MARKETING_STUDIO_HOME` trỏ vào nó nên `studio_paths.repo_root()`
    — và mọi thứ suy từ đó (`workspaces/`, `studio.local.json`, `<repo>/.env`, repo anh em cùng
    thư mục cha) — đều nằm trong cây tạm.

    Vì sao cần (P1-8, 30/09/2026): test nào để `repo_root()` rơi về bản clone THẬT (nơi chính
    file test nằm) thì đọc `workspaces/` + `studio.local.json` của máy đang chạy. CI checkout
    sạch xanh, còn máy đã `install.sh --mode embedded` — tức mọi máy chạy thật — đỏ 12 ca.
    Và từ khi trạm giọng/video được suy từ repo anh em, một bản clone thật nằm cạnh
    `agent-voice-studio` sẽ "có" trạm giọng trong mọi test không cô lập.

    Đặt dưới `tmp_path/xyz/` (tên bất kỳ, không có anh em nào): test cần anh em thì tự dựng
    cạnh nó. Mốc tối thiểu để `repo_root()` nhận: `scripts/lib/` + `install.ps1`."""
    r = tmp_path / "xyz" / "agent-marketing-team"
    (r / "scripts" / "lib").mkdir(parents=True)
    (r / "install.ps1").write_text("", encoding="utf-8")
    monkeypatch.setenv("MARKETING_STUDIO_HOME", str(r))
    return r
