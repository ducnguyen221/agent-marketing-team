#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vòng đời một bản cài: `update` · `backup` · `migrate --to separate` · `uninstall`.

Bốn lệnh cho bốn lúc trong đời một bản cài, và cả bốn viết ra vì cùng một lý do: người dùng
chế độ `embedded` có nội dung nằm TRONG thư mục repo, nên những thao tác quen thuộc với
repo (xoá đi clone lại, `git clean`, chép tay) sẽ ăn mất nội dung của họ.

    update   = `git pull --ff-only`, KHÔNG BAO GIỜ xoá gì; checkout có file sửa chưa commit
               thì dừng trước khi kéo. Tài liệu nói thẳng: đừng xoá folder repo để cài lại.
    uninstall = gỡ đúng phần bộ cài tạo (`studio.local.json`, hook pre-commit của nó);
               GIỮ trạm, `.env` và repo.
    backup   = zip cả trạm. Mặc định KHÔNG kèm `.env`; kèm thì phải xin rõ `--with-env`.
    migrate  = đường ra khi người dùng lớn lên: dời `<repo>/workspaces/` ra ngoài repo và
               `.env` về kho secret của máy, rồi ghi lại lựa chọn. Đích KHÔNG có mặc định
               ngầm: không khai `--station` thì hỏi (có gợi ý, cho thấy số file/dung lượng,
               xin y/N); không có người ngồi thì bắt buộc `--station`.

`export/import` gói chuyển máy (có manifest + sha256, chọn file theo danh sách khai rõ) là
việc của `station.py` — khác mục đích: `backup` là ảnh chụp cho chính mình, `export` là gói
bàn giao sang máy khác.

Mã thoát theo `scripts/lib/studio_contract.py`: 0 · 1 · 2 · 3.
"""
from __future__ import annotations

import argparse
import errno
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import station_manifest as SM  # noqa: E402
import studio_contract as SC  # noqa: E402
import studio_paths as SP  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

PROG = "studio"
KHO_SECRET_MAC_DINH = Path.home() / ".secret" / "marketing-studio"

# Tên nhìn giống secret: không bao giờ tự động vào gói. Bộ mẫu khai ở `station_manifest`
# và dùng chung với `station.py export` — hai bản sao của một danh sách secret sẽ lệch
# nhau, và cái lệch là cái rò.
MAU_GIONG_SECRET = SM.MAU_GIONG_SECRET
_giong_secret = SM.giong_secret
BO_QUA_THU_MUC = {".git", "__pycache__", ".venv", "venv", ".tmp", ".pytest_cache"}
BO_QUA_FILE = ("*.pyc", "~$*")


def _bo_qua_file(ten: str) -> bool:
    return any(fnmatch.fnmatch(os.path.basename(ten), m) for m in BO_QUA_FILE)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


# ── update ────────────────────────────────────────────────────────────────────────────

def _sua_doi_cuc_bo(repo: Path) -> list[str]:
    """File ĐÃ TRACK đang có sửa đổi chưa commit. File bị ignore (`workspaces/`, `.env`,
    `studio.local.json`) không tính — đó là dữ liệu của người dùng, không phải mã."""
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=60)
    if r.returncode != 0:
        raise SC.EngineError("`git status` không chạy được: " + (r.stderr or r.stdout).strip())
    return [d[3:] for d in (r.stdout or "").splitlines() if d.strip()]


def update() -> dict:
    repo = SP.repo_root()
    if not repo or not (repo / ".git").exists():
        raise SC.ContractError("không thấy bản clone git của repo — `update` chỉ chạy trên "
                               "bản clone (git clone, đừng tải zip).")
    # Kiểm TRƯỚC khi kéo: `pull --ff-only` vẫn chạy khi file sửa tay không đụng file mới về,
    # và người dùng không hề biết bản mình đang chạy là "mã mới + sửa cũ". Có sửa đổi thì
    # dừng; KHÔNG stash, KHÔNG reset, KHÔNG clean — chỗ sửa đó có thể là công việc của họ.
    ban = _sua_doi_cuc_bo(repo)
    if ban:
        raise SC.ContractError(
            f"checkout có {len(ban)} file đã sửa mà chưa commit: {', '.join(ban[:6])}. "
            "Commit hoặc tự cất chúng đi rồi chạy lại — `update` không bao giờ tự bỏ sửa "
            "đổi của bạn. Chưa kéo gì.")
    r = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise SC.EngineError(
            "`git pull --ff-only` không chạy được (nhánh lệch, hoặc có sửa đổi cục bộ). "
            "KHÔNG xoá gì cả — xử lý tay rồi chạy lại.\n" + (r.stderr or r.stdout).strip())
    return {"repo": str(repo), "output": (r.stdout or "").strip()}


# ── uninstall ─────────────────────────────────────────────────────────────────────────
#
# Gỡ ĐÚNG phần bộ cài sở hữu, không hơn. Bộ cài (`init_station.py`) tạo ra bốn thứ:
#
#   studio.local.json   lựa chọn chế độ + đường trạm        → GỠ
#   hook pre-commit     rào lớp hai của embedded            → GỠ nếu đúng là hook của bộ cài
#   .env                chép từ .env.example rồi BẠN điền   → GIỮ (cấu hình của bạn)
#   trạm                workspaces/ hoặc thư mục ngoài      → GIỮ (nội dung của bạn)
#
# Xoá nội dung không bao giờ là một phần của gỡ công cụ. Skill và adapter host là file
# được git theo dõi trong repo — gỡ chúng là xoá repo, việc đó người dùng tự làm.

DAU_HOOK = "Hook pre-commit của chế độ cài `embedded`"


def _hook_pre_commit(repo: Path) -> Path | None:
    """Đường hook THẬT theo git (worktree có `.git` là file). Không tạo gì."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    p = Path((r.stdout or "").strip())
    return (p if p.is_absolute() else repo / p) / "pre-commit"


def uninstall(dry_run: bool = False) -> dict:
    repo = SP.repo_root()
    if not repo:
        raise SC.ContractError("không xác định được gốc repo (đặt MARKETING_STUDIO_HOME).")
    try:
        lc = SP.local_config(repo)
    except SP.StudioPathsError:
        lc = {}                      # file hỏng vẫn là file của bộ cài — gỡ được
    try:
        tram, nguon = SP.resolve_station()
    except SP.StudioPathsError:
        tram, nguon = None, None
    go, giu = [], []

    f = repo / SP.LOCAL_CONFIG
    if f.is_file():
        go.append(str(f))
        if not dry_run:
            f.unlink()

    hook = _hook_pre_commit(repo)
    if hook and hook.is_file():
        try:
            cua_bo_cai = DAU_HOOK in hook.read_text(encoding="utf-8", errors="replace")
        except OSError:
            cua_bo_cai = False
        if cua_bo_cai:
            go.append(str(hook))
            if not dry_run:
                hook.unlink()
        else:
            giu.append(f"{hook} — không phải hook của bộ cài, không đụng")

    env = repo / ".env"
    if env.is_file():
        giu.append(f"{env} — cấu hình bạn đã điền (xoá tay nếu chắc không cần)")
    if tram is not None and tram.is_dir():
        giu.append(f"{tram} — trạm nội dung (nguồn: {nguon}); gỡ công cụ KHÔNG xoá nội dung")
    if (os.environ.get("MARKETING_STUDIO_DATA") or "").strip():
        giu.append("biến MARKETING_STUDIO_DATA vẫn đặt ở máy — gỡ tay nếu không dùng trạm đó nữa")
    return {"repo": str(repo), "dry_run": bool(dry_run), "mode": lc.get("mode"),
            "station": str(tram) if tram else None, "removed": go, "kept": giu}


# ── backup ────────────────────────────────────────────────────────────────────────────

def _liet_ke(st: Path):
    for dp, dn, fn in os.walk(st):
        dn[:] = [d for d in dn if d not in BO_QUA_THU_MUC]
        for n in sorted(fn):
            f = Path(dp) / n
            rel = f.relative_to(st).as_posix()
            if not _bo_qua_file(rel):
                yield f, rel


def backup(out, station=None, with_env=False) -> dict:
    st = SP.root(station)
    if not st.is_dir():
        raise SC.StationMissing(f"không có trạm ở {st} — chạy init_station.py trước. "
                                + SC.GOI_Y_DU_LIEU_CU)
    files = list(_liet_ke(st))
    xau = [rel for _, rel in files if _giong_secret(rel)]
    if xau:
        raise SC.ContractError(
            "từ chối đóng gói — trong trạm có file trông giống secret: " + ", ".join(xau) +
            ". Dời chúng về kho secret của máy rồi chạy lại (biến chỉ giữ ĐƯỜNG DẪN).")
    repo = SP.repo_root()
    if with_env and repo and (repo / ".env").is_file():
        files.append((repo / ".env", ".env"))
    manifest = {"kind": "backup", "station": str(st), "with_env": bool(with_env),
                "files": [rel for _, rel in files]}
    out = Path(out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tam = out.with_suffix(out.suffix + ".part")
    try:
        with zipfile.ZipFile(tam, "w", zipfile.ZIP_DEFLATED) as z:
            for f, rel in files:
                z.write(f, rel)
            z.writestr("marketing-studio-backup.json",
                       json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(tam, out)
    finally:
        if tam.exists():
            tam.unlink()
    return {"out": str(out), "files": manifest["files"], "station": str(st),
            "with_env": bool(with_env)}


# ── migrate --to separate ─────────────────────────────────────────────────────────────

def _doi_cay(nguon: Path, dich: Path):
    """Dời thư mục an toàn. Cùng ổ: `os.rename` — hỏng thì hỏng SẠCH, chưa đụng gì.
    Khác ổ: chép → đối chiếu sha256 từng file → mới xoá nguồn (ba bước rời).

    KHÔNG dùng `shutil.move` cho thư mục: khi `rename` bị từ chối (một chương trình đang
    giữ file) nó âm thầm rơi về copytree + rmtree, và rmtree dừng giữa chừng ⇒ cây nằm hai
    nơi, trông y như mất dữ liệu.
    """
    try:
        os.rename(nguon, dich)
        return
    except OSError as e:
        khac_o = e.errno == errno.EXDEV or getattr(e, "winerror", None) == 17
        if not khac_o:
            raise SC.ContractError(
                f"không dời được {nguon} → {dich} ({e}). Có thể một chương trình đang mở file "
                "trong trạm — đóng nó rồi chạy lại. CHƯA đụng gì.")
    shutil.copytree(nguon, dich)
    for dp, _dn, fn in os.walk(nguon):
        for n in fn:
            a = Path(dp) / n
            b = dich / a.relative_to(nguon)
            if not b.is_file() or _sha256(a) != _sha256(b):
                raise SC.EngineError(
                    f"bản chép sang {dich} không khớp ở {b} — nguồn {nguon} GIỮ NGUYÊN. "
                    "Xoá bản chép dở ở đích rồi chạy lại.")
    try:
        shutil.rmtree(nguon)
    except OSError as e:
        raise SC.EngineError(
            f"đã chép đủ và khớp sang {dich}, nhưng xoá nguồn {nguon} dở dang ({e}). Phần còn "
            "lại ở nguồn là BẢN SAO — đừng chạy lại lệnh; đóng chương trình đang giữ file rồi "
            "xoá tay.")


def _doi_file(nguon: Path, dich: Path):
    try:
        os.rename(nguon, dich)
    except OSError:
        shutil.copy2(nguon, dich)
        if _sha256(nguon) != _sha256(dich):
            dich.unlink()
            raise SC.EngineError(f"chép {nguon} → {dich} không khớp; giữ nguyên nguồn")
        nguon.unlink()


def _link_or_reparse(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def goi_y_dich(repo: Path) -> Path | None:
    """Đích GỢI Ý (người dùng vẫn được chọn khác): `<OPCOS_WORKSPACES>/marketing` khi biến có,
    luôn là đường tuyệt đối. Không có biến thì KHÔNG gợi ý (None): đoán từ vị trí của repo là
    sai khi clone nằm trong một repo git khác — nội dung sẽ bị dời vào cây repo đó.
    Biến chỉ đọc từ môi trường thật, qua đúng một điểm đọc (`SP.goc_opcos`)."""
    d = SP.goc_opcos("marketing")
    return Path(d[1]).resolve() if d else None


def _kiem_dich_trong_nguon(dich: Path, ws: Path) -> None:
    """Đích nằm TRONG (hoặc trùng) trạm nguồn: dời một cây vào chính nó là vô nghĩa và để lại
    thư mục rỗng/nửa vời. Từ chối trước khi đụng byte nào."""
    nguon = ws.resolve()
    if dich == nguon or nguon in dich.parents:
        raise SC.ContractError(
            f"thư mục đích {dich} nằm trong chính trạm nguồn {nguon} — chọn chỗ NGOÀI repo "
            "(--station). Chưa đụng gì.")


def _co_nguoi_tra_loi() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:            # noqa: BLE001 — stdin bị thay (pytest, dịch vụ nền)
        return False


def _hoi_ban_phim(nhac: str) -> str:
    sys.stderr.write(nhac)
    sys.stderr.flush()
    return input()


def _do_cay(ws: Path):
    """-> (số file, tổng byte) của cây sẽ dời."""
    n = b = 0
    for dp, _dn, fn in os.walk(ws):
        for t in fn:
            n += 1
            try:
                b += (Path(dp) / t).stat().st_size
            except OSError:
                pass
    return n, b


def _dung_luong(b: int) -> str:
    for don_vi in ("B", "KB", "MB", "GB"):
        if b < 1024 or don_vi == "GB":
            return f"{b} B" if don_vi == "B" else f"{b:.1f} {don_vi}"
        b /= 1024


def kiem_dich_doi(ws: Path, dich: Path) -> None:
    """Đích dời hợp lệ? Nằm trong chính trạm nguồn / là FILE / không rỗng ⇒ mã 2, chưa đụng gì.
    Dùng chung cho `migrate` (hỏi nơi dời) và `init` (người dùng chọn CHUYỂN trạm cũ)."""
    _kiem_dich_trong_nguon(dich, ws)
    if dich.exists() and not dich.is_dir():
        raise SC.ContractError(f"đích {dich} là một FILE, không phải thư mục — chọn chỗ khác "
                               "(--station). Chưa đụng gì.")
    if dich.exists() and any(dich.iterdir()):
        raise SC.ContractError(f"thư mục đích không rỗng: {dich} — chọn chỗ khác (--station).")


def kiem_env_doi(repo: Path, kho: Path):
    """-> đường `.env` sẽ sang kho secret (hoặc None nếu repo không có `.env`). Kho đã có `.env` ⇒ mã 2,
    chưa đụng gì. Chỉ xét sự tồn tại, không mở file nào."""
    f_env = repo / ".env"
    env_stat = os.lstat(f_env) if os.path.lexists(f_env) else None
    if env_stat and (_link_or_reparse(env_stat) or not stat.S_ISREG(env_stat.st_mode)):
        raise SC.ContractError(f"{f_env} không phải file thường — chưa dời gì.")
    env_dich = (kho / ".env") if env_stat else None
    if env_dich and os.path.lexists(env_dich):
        dest_stat = os.lstat(env_dich)
        if _link_or_reparse(dest_stat) or not stat.S_ISREG(dest_stat.st_mode):
            raise SC.ContractError(f"{env_dich} đã là liên kết/điểm nối hoặc không phải file thường — chưa dời gì.")
        raise SC.ContractError(
            f"{env_dich} đã có — gộp tay rồi xoá {f_env}, sau đó chạy lại. Chưa đụng gì.")
    return env_dich


def hoi_xac_nhan_doi(ws: Path, dich: Path, ask) -> bool:
    """Câu `y/N` của `migrate`: cho thấy số file/dung lượng; True khi gõ y/yes. `EOFError` lan ra cho
    người gọi quyết (migrate: mã 2; init: giữ trạm cũ)."""
    n, b = _do_cay(ws)
    xn = (ask(f"Sẽ dời {n} file ({_dung_luong(b)}) từ {ws.resolve()}\n"
              f"                          tới {dich}\n"
              "Dời thật? [y/N]: ") or "").strip().lower()
    return xn in ("y", "yes")


def _hoi_noi_doi(repo: Path, ws: Path, ask, non_interactive: bool) -> Path:
    """Không có `--station`: hỏi người dùng nơi dời. Không hỏi được ⇒ mã 2, không đoán."""
    goi_y = goi_y_dich(repo)
    if ask is None:
        if non_interactive or not _co_nguoi_tra_loi():
            raise SC.ContractError(
                "không có người ngồi để hỏi nơi dời trạm — phải khai rõ đích: "
                "`studio.py migrate --to separate --station <thư-mục-đích>`"
                + (f" (gợi ý: {goi_y})" if goi_y else "") + ". Chưa đụng gì.")
        ask = _hoi_ban_phim
    try:
        if goi_y:
            tra = SP.duong_nguoi_go(
                ask(f"Dời trạm ra ngoài repo. Gợi ý: {goi_y}\n"
                    "Nơi dời [Enter = nhận gợi ý, hoặc gõ đường dẫn khác]: "))
        else:
            tra = SP.duong_nguoi_go(
                ask("Dời trạm ra ngoài repo. Chưa có gợi ý nào (đặt OPCOS_WORKSPACES nếu muốn).\n"
                    "Nơi dời [gõ đường dẫn thư mục đích; Enter rỗng = dừng]: "))
    except EOFError:
        raise SC.ContractError(
            "không đọc được câu trả lời (stdin không có người) — chạy lại với "
            "`--station <thư-mục-đích>`. Chưa đụng gì.")
    if not tra and not goi_y:
        raise SC.ContractError("chưa nhập nơi dời nên dừng — chưa đụng gì. Chạy lại và nhập "
                               "đường, hoặc dùng `--station <thư-mục-đích>`.")
    dich = Path(tra).expanduser().resolve() if tra else goi_y
    kiem_dich_doi(ws, dich)
    try:
        dong_y = hoi_xac_nhan_doi(ws, dich, ask)
    except EOFError:
        raise SC.ContractError("không đọc được xác nhận — chưa đụng gì. Chạy lại với --station.")
    if not dong_y:
        raise SC.ContractError("không xác nhận (cần gõ y) — chưa đụng gì.")
    return dich


def migrate_sang_separate(station=None, kho_secret=None, ask=None, non_interactive=False) -> dict:
    repo = SP.repo_root()
    if not repo:
        raise SC.ContractError("không xác định được gốc repo (đặt MARKETING_STUDIO_HOME).")
    if SP.mode(repo) != "embedded":
        raise SC.ContractError(
            f"máy này không ở chế độ embedded (đang: {SP.mode(repo) or 'chưa cài'}) — "
            "không có gì để dời.")
    ws, _nguon = SP.tram_nhung(repo)
    if not ws.is_dir():
        raise SC.StationMissing(f"không có {ws} — chưa có trạm nào nằm trong repo.")

    if station:
        requested_target = Path(station).expanduser()
        if os.path.lexists(requested_target):
            requested_stat = os.lstat(requested_target)
            if _link_or_reparse(requested_stat):
                raise SC.ContractError(f"đích {requested_target} là liên kết/điểm nối — chọn đường khác; chưa đụng gì.")
        dich = requested_target.resolve()
    else:
        dich = _hoi_noi_doi(repo, ws, ask, non_interactive)
    _kiem_dich_trong_nguon(dich, ws)
    if os.path.lexists(dich):
        target_stat = os.lstat(dich)
        if _link_or_reparse(target_stat):
            raise SC.ContractError(f"đích {dich} là liên kết/điểm nối — chọn chỗ khác; chưa đụng gì.")
        if not stat.S_ISDIR(target_stat.st_mode):
            raise SC.ContractError(f"đích {dich} là một FILE, không phải thư mục — chọn chỗ khác "
                                   "(--station). Chưa đụng gì.")
        if any(dich.iterdir()):
            raise SC.ContractError(f"thư mục đích không rỗng: {dich} — chọn chỗ khác (--station).")
    kho_input = Path(kho_secret).expanduser() if kho_secret else KHO_SECRET_MAC_DINH
    if os.path.lexists(kho_input):
        secret_stat = os.lstat(kho_input)
        if _link_or_reparse(secret_stat) or not stat.S_ISDIR(secret_stat.st_mode):
            raise SC.ContractError(f"thư mục kho secret {kho_input} là liên kết/điểm nối hoặc không phải thư mục thường.")
    kho = kho_input.resolve()

    f_env = repo / ".env"
    env_dich = kiem_env_doi(repo, kho)
    da_co_thu_muc_rong = os.path.lexists(dich)
    target_before = os.lstat(dich) if da_co_thu_muc_rong else None
    target_id = (target_before.st_dev, target_before.st_ino) if target_before else None
    local_path = repo / SP.LOCAL_CONFIG

    def identity(st):
        return st.st_dev, st.st_ino

    def unsupported_entry(st):
        return _link_or_reparse(st)

    def snapshot_file(path: Path):
        if not os.path.lexists(path):
            return {"exists": False, "identity": None, "bytes": None}
        lst = os.lstat(path)
        if unsupported_entry(lst) or not stat.S_ISREG(lst.st_mode):
            raise SC.ContractError(f"metadata path is not a plain file: {path}")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if identity(opened) != identity(lst):
                raise SC.ContractError(f"metadata changed while being inspected: {path}")
            return {"exists": True, "identity": identity(lst), "bytes": stream.read()}

    def tree_snapshot(root: Path):
        root_stat = os.lstat(root)
        if unsupported_entry(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            raise SC.ContractError(f"trạm chứa điểm nối/liên kết mềm hoặc không phải thư mục thường: {root}")
        state = {}

        def visit(directory, relative):
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    path = Path(entry.path)
                    rel = f"{relative}/{entry.name}" if relative else entry.name
                    item_stat = os.lstat(path)
                    if unsupported_entry(item_stat):
                        raise SC.ContractError(
                            f"trạm chứa symlink/junction/reparse không được hỗ trợ: {path} — chưa dời gì.")
                    if stat.S_ISDIR(item_stat.st_mode):
                        state[rel.replace(os.sep, "/")] = ("dir",)
                        visit(path, rel)
                    elif stat.S_ISREG(item_stat.st_mode):
                        state[rel.replace(os.sep, "/")] = ("file", _sha256(path))
                    else:
                        raise SC.ContractError(f"trạm chứa mục không phải file/thư mục thường: {path}")

        visit(root, "")
        return state

    def known_write_states(before, payload, existed, written):
        if not isinstance(written, int) or written < 0 or written > len(payload):
            return set()
        prefix = payload[:written]
        if not existed:
            return {prefix}
        states = {prefix + before["bytes"][written:]}
        if written == len(payload):
            states.add(payload)
        return states

    def read_bytes(path: Path):
        with path.open("rb") as stream:
            return stream.read()

    def write_config(before, payload, record):
        mode = "r+b" if before["exists"] else "x+b"
        record.update(identity=before["identity"], payload=payload, attempted=True,
                      write_count=None, write_state=None)
        try:
            with local_path.open(mode) as stream:
                opened_id = identity(os.fstat(stream.fileno()))
                if before["exists"]:
                    if opened_id != before["identity"]:
                        raise OSError(f"local config identity changed before write: {local_path}")
                    stream.seek(0)
                    if stream.read() != before["bytes"]:
                        raise OSError(f"local config bytes changed before write: {local_path}")
                record["identity"] = opened_id
                stream.seek(0)
                written = stream.write(payload)
                record["write_count"] = written
                if written != len(payload):
                    raise OSError(f"local config short write ({written}/{len(payload)}): {local_path}")
                stream.truncate(len(payload))
                stream.flush()
                stream.seek(0)
                observed = stream.read()
                if observed != payload:
                    raise OSError(f"local config readback mismatch: {local_path}")
                record["write_state"] = observed
                record["written"] = True
        except BaseException:
            try:
                if os.path.lexists(local_path):
                    current_stat = os.lstat(local_path)
                    if (not unsupported_entry(current_stat) and stat.S_ISREG(current_stat.st_mode) and
                            identity(current_stat) == record.get("identity")):
                        observed = read_bytes(local_path)
                        if observed in known_write_states(before, payload, before["exists"],
                                                          record.get("write_count")):
                            record["write_state"] = observed
            except BaseException:
                pass
            raise

    def restore_config(before, record):
        if not os.path.lexists(local_path):
            if not before["exists"]:
                return
            raise OSError(f"local config disappeared during migration: {local_path}")
        current_stat = os.lstat(local_path)
        if unsupported_entry(current_stat) or not stat.S_ISREG(current_stat.st_mode):
            raise OSError(f"local config path became a link or non-file; retained: {local_path}")
        if not before["exists"]:
            raise OSError(f"new local config retained because no pre-migration bytes exist: {local_path}")
        current_id = identity(current_stat)
        if not record.get("attempted"):
            if current_id != before["identity"] or read_bytes(local_path) != before["bytes"]:
                raise OSError(f"local config changed outside migration: {local_path}")
            return
        if current_id != record.get("identity"):
            raise OSError(f"local config identity is no longer operation-owned: {local_path}")
        current = read_bytes(local_path)
        if current == before["bytes"]:
            return
        if record.get("write_state") is None or current != record["write_state"]:
            raise OSError(f"local config bytes are ambiguous; retained for recovery: {local_path}")
        with local_path.open("r+b") as stream:
            if identity(os.fstat(stream.fileno())) != record["identity"]:
                raise OSError(f"local config identity changed before restore: {local_path}")
            stream.seek(0)
            if stream.read() != current:
                raise OSError(f"local config changed before restore: {local_path}")
            stream.seek(0)
            stream.write(before["bytes"])
            stream.truncate(len(before["bytes"]))
            stream.flush()
            stream.seek(0)
            if stream.read() != before["bytes"]:
                raise OSError(f"local config restore readback mismatch: {local_path}")

    source_tree = tree_snapshot(ws)
    config_before = snapshot_file(local_path)
    env_before = snapshot_file(f_env) if env_dich else None
    secret_dir_existed = os.path.lexists(kho) if env_dich else False
    secret_dir_id = identity(os.lstat(kho)) if secret_dir_existed else None
    tree_moved = False
    tree_target_id = None
    env_moved = False
    env_target_id = None
    created_secret_dir_id = None
    config_write = {}

    if da_co_thu_muc_rong:
        current_target = os.lstat(dich) if os.path.lexists(dich) else None
        if (current_target is None or unsupported_entry(current_target) or
                not stat.S_ISDIR(current_target.st_mode) or identity(current_target) != target_id or
                any(dich.iterdir())):
            raise SC.ContractError(f"đích {dich} đã đổi trước khi dời — chưa đụng gì.")
        dich.rmdir()
    dich.parent.mkdir(parents=True, exist_ok=True)
    try:
        if os.path.lexists(dich):
            raise OSError(f"đích {dich} xuất hiện trước khi dời; giữ nguyên.")
        _doi_cay(ws, dich)
        tree_moved = True
        moved_tree_stat = os.lstat(dich)
        if unsupported_entry(moved_tree_stat) or not stat.S_ISDIR(moved_tree_stat.st_mode):
            raise OSError("moved station tree is not a plain directory")
        tree_target_id = identity(moved_tree_stat)
        if os.path.lexists(ws) or tree_snapshot(dich) != source_tree:
            raise OSError("moved station tree does not match its captured source")
        if env_dich:
            if os.path.lexists(kho):
                secret_stat = os.lstat(kho)
                if unsupported_entry(secret_stat) or not stat.S_ISDIR(secret_stat.st_mode):
                    raise OSError(f"secret directory changed before write: {kho}")
                if not secret_dir_existed and identity(secret_stat) != secret_dir_id:
                    raise OSError(f"secret directory appeared during migration: {kho}")
            else:
                kho.mkdir(parents=True, exist_ok=True)
                secret_dir_id = identity(os.lstat(kho))
            _doi_file(f_env, env_dich)
            env_moved = True
            moved_env_stat = os.lstat(env_dich)
            if (unsupported_entry(moved_env_stat) or not stat.S_ISREG(moved_env_stat.st_mode)):
                raise OSError("moved .env is not a plain file")
            env_target_id = identity(moved_env_stat)
            if os.path.lexists(f_env) or read_bytes(env_dich) != env_before["bytes"]:
                raise OSError("moved .env does not match its captured source")

        lc = SP.local_config(repo)
        lc.update({"mode": "separate", "station_path": str(dich), "secrets": str(kho)})
        payload = (json.dumps(lc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        write_config(config_before, payload, config_write)
    except BaseException as cause:
        rollback_errors = []

        def attempt(label, action):
            try:
                action()
            except BaseException as rollback_error:
                rollback_errors.append(f"{label}: {rollback_error}")

        attempt("local config", lambda: restore_config(config_before, config_write))
        if not rollback_errors and env_dich:
            def restore_env():
                if not env_moved:
                    if os.path.lexists(env_dich):
                        raise OSError("partial .env destination has unknown ownership; retained")
                    if os.path.lexists(f_env):
                        source_stat = os.lstat(f_env)
                        if (unsupported_entry(source_stat) or not stat.S_ISREG(source_stat.st_mode) or
                                read_bytes(f_env) != env_before["bytes"]):
                            raise OSError(".env source changed during failed move; retained")
                        return
                    raise OSError(".env source disappeared during failed move; retained")
                if os.path.lexists(f_env):
                    raise OSError(".env source path was recreated; retained for recovery")
                if not os.path.lexists(env_dich):
                    raise OSError("moved .env disappeared; retained for recovery")
                moved_stat = os.lstat(env_dich)
                if (unsupported_entry(moved_stat) or not stat.S_ISREG(moved_stat.st_mode) or
                        identity(moved_stat) != env_target_id or read_bytes(env_dich) != env_before["bytes"]):
                    raise OSError("moved .env is no longer operation-owned; retained for recovery")
                if os.name != "nt":
                    raise OSError("no-clobber .env restore is unavailable on this platform; retained")
                os.rename(env_dich, f_env)
                restored_stat = os.lstat(f_env)
                if (unsupported_entry(restored_stat) or not stat.S_ISREG(restored_stat.st_mode) or
                        identity(restored_stat) != env_target_id or read_bytes(f_env) != env_before["bytes"] or
                        os.path.lexists(env_dich)):
                    raise OSError(".env restore did not verify")
            attempt(".env", restore_env)

        if not rollback_errors and tree_moved:
            def restore_tree():
                if os.path.lexists(ws):
                    source_stat = os.lstat(ws)
                    if unsupported_entry(source_stat):
                        raise OSError("source station path was recreated as a link/reparse point; retained")
                    raise OSError("source station path was recreated; retained")
                if not os.path.lexists(dich):
                    raise OSError("destination tree disappeared; retained for recovery")
                moved_stat = os.lstat(dich)
                if (unsupported_entry(moved_stat) or not stat.S_ISDIR(moved_stat.st_mode) or
                        identity(moved_stat) != tree_target_id or tree_snapshot(dich) != source_tree):
                    raise OSError("destination tree is no longer operation-owned; retained for recovery")
                _doi_cay(dich, ws)
                if tree_snapshot(ws) != source_tree or os.path.lexists(dich):
                    raise OSError("station tree restore did not verify")
            attempt("station tree", restore_tree)

        if not rollback_errors and da_co_thu_muc_rong:
            def restore_empty_target():
                if os.path.lexists(dich):
                    current = os.lstat(dich)
                    if (unsupported_entry(current) or not stat.S_ISDIR(current.st_mode) or
                            any(dich.iterdir())):
                        raise OSError("destination path is occupied; retained")
                    return
                os.mkdir(dich)
            attempt("empty destination", restore_empty_target)

        if not rollback_errors and env_dich and not secret_dir_existed and os.path.lexists(kho):
            def remove_created_secret_dir():
                current = os.lstat(kho)
                if (unsupported_entry(current) or not stat.S_ISDIR(current.st_mode) or
                        identity(current) != secret_dir_id or any(kho.iterdir())):
                    raise OSError("secret directory is no longer operation-owned/empty; retained")
                os.rmdir(kho)
            attempt("empty secret directory", remove_created_secret_dir)

        if rollback_errors:
            detail = "; ".join(rollback_errors)
            raise SC.ContractError(
                f"migrate failed ({cause}); rollback incomplete ({detail}). "
                "Artifacts were retained where ownership could not be verified; recover manually.") from cause
        raise
    return {"mode": "separate", "station": str(dich),
            "env_moved_to": str(env_dich) if env_dich else None}

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=PROG,
                                 description="Vòng đời bản cài: update · backup · migrate · uninstall.")
    con = ap.add_subparsers(dest="lenh", required=True)

    con.add_parser("update", help="git pull --ff-only (không bao giờ xoá gì)")

    b = con.add_parser("backup", help="zip cả trạm (mặc định KHÔNG kèm .env)")
    b.add_argument("--out", required=True, help="file zip đích")
    b.add_argument("--station", help="trạm nguồn (mặc định: trạm đang phân giải)")
    b.add_argument("--with-env", action="store_true", help="kèm <repo>/.env (CHỨA cấu hình bí mật)")

    m = con.add_parser("migrate", help="dời trạm embedded ra ngoài repo")
    m.add_argument("--to", required=True, choices=["separate"])
    m.add_argument("--station", help="thư mục đích; bắt buộc khi không có người ngồi trả lời "
                                     "(không khai thì chương trình hỏi, có gợi ý)")
    m.add_argument("--non-interactive", action="store_true",
                   help="không hỏi: thiếu --station thì dừng mã 2")
    m.add_argument("--secret-dir", help="kho secret nhận .env (mặc định ~/.secret/marketing-studio)")

    u = con.add_parser("uninstall", help="gỡ phần bộ cài sở hữu; GIỮ trạm, .env, repo")
    u.add_argument("--dry-run", action="store_true", help="chỉ liệt kê, không gỡ gì")

    for p in (ap, b, m, u):
        p.add_argument("--json", action="store_true")
    args, ma = SC.parse(ap, argv)
    if args is None:
        return ma
    args.prog = PROG

    def chay(a):
        if a.lenh == "update":
            kq = update()
            SC.log(kq["output"] or "[update] đã mới nhất")
        elif a.lenh == "backup":
            kq = backup(a.out, a.station, a.with_env)
            SC.log(f"[backup] {len(kq['files'])} file → {kq['out']}")
        elif a.lenh == "uninstall":
            kq = uninstall(a.dry_run)
            dau = "(xem trước — chưa gỡ gì) " if kq["dry_run"] else ""
            SC.log(f"[uninstall] {dau}gỡ {len(kq['removed'])} mục của bộ cài")
            for x in kq["removed"]:
                SC.log(f"  - {x}")
            for x in kq["kept"]:
                SC.log(f"  giữ {x}")
        else:
            kq = migrate_sang_separate(a.station, a.secret_dir,
                                       non_interactive=a.non_interactive)
            SC.log(f"[migrate] trạm giờ ở {kq['station']} — đặt MARKETING_STUDIO_DATA trỏ vào đó")
            if kq["env_moved_to"]:
                SC.log(f"[migrate] .env → {kq['env_moved_to']}")
        return kq
    return SC.run(chay, args, getattr(args, "json", False))


if __name__ == "__main__":
    sys.exit(main())
