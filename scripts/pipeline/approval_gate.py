#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Kho CỔNG DUYỆT — nơi DUY NHẤT ghi ba cổng, và mặt tiền TRONG PHIÊN.

## Vì sao có file này

Trước 12/09/2026, người ghi `g1` và `g3` duy nhất là `approve_bus.py` — mặt tiền Telegram.
Nghĩa là **Telegram không phải tuỳ chọn, nó là con đường duy nhất**: không có điện thoại
thì cả chiến dịch đứng. Mà cách làm việc mặc định lại là người ngồi cùng agent trong một
phiên, đọc file trên máy rồi gật ngay tại chỗ.

Nên tách làm hai tầng:

```
        mặt tiền                       kho cổng                  chỗ ở thật
  approve_bus.py  (Telegram) ─┐
                              ├─► approval_gate.open_gate() ─► campaign.md · publish.json
  approval_gate.py   (trong phiên)┘
```

Hai mặt tiền NGANG HÀNG. Cái nào cũng ghi vào đúng một chỗ, đúng một cách, cùng để lại
dấu vết trong `logs/events.jsonl`. Thêm mặt tiền thứ ba (web, CLI khác) chỉ cần gọi vào
đây, không được đẻ kho cổng riêng.

## Cổng ở đâu

| Cổng | Chỗ ở thật | Hàm ghi |
|---|---|---|
| **g1** — duyệt đề tài | cột `g1` + `status=approved` trong bảng Content của `campaign.md` | `write_g1` |
| **g2** — duyệt trước khi đăng | `publish.json → posts[].review` (+ ô `g2` mirror) | `write_g2` → gọi `register_publish approve` |
| **g3** — duyệt BẢN THẬT trên web | cột `g3` trong bảng Content | `write_column` |

Không đẻ kho phê duyệt thứ hai. Hai nguồn sự thật thì sớm muộn chúng nói khác nhau.

## Hai điều bắt buộc khi mở cổng

1. **`boi`** — AI duyệt. Cổng không có tên người là cổng vô chủ.
2. **`quote`** — NGUYÊN VĂN câu người nói. Không phải để đẹp hồ sơ: đây là thứ ngăn
   agent tự đóng dấu thay người. Agent chép được câu của người thì câu đó phải đã tồn tại.
   Cùng luật với `register_publish approve --note`, đặt ra từ 04/09/2026.

⚠️ **KHÔNG xếp việc.** Mở cổng xong có chạy tiếp hay không là quyết định của MẶT TIỀN:
Telegram xếp việc cho thợ chạy nền, còn agent trong phiên thường chạy bước kế tiếp ngay.
Gộp hai thứ vào đây thì một trong hai đường sẽ làm việc hai lần.

## Lệnh (dùng trong phiên, không cần Telegram)

```
approval_gate.py <chiến dịch> waiting --gate g1|g2|g3 [--json]
approval_gate.py <chiến dịch> open    --gate g1|g2|g3 --post A,B --by "<tên>" --quote "..."
approval_gate.py <chiến dịch> reject  --gate g1|g2|g3 --post A   --by "<tên>" --quote "..."
```

`waiting` in kèm **đường dẫn file để mở** — đó là thứ người cần để duyệt thật thay vì gật bừa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
import post_content  # noqa: E402
import md_io  # noqa: E402
import event_log as EV  # noqa: E402

GATES = ("g1", "g2", "g3")
_DELIVERY_FORBIDDEN_ATTRIBUTES = (
    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    | getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
    | 0x00040000 | 0x00400000  # recall-on-open / recall-on-data-access
)

# Tên file giữ tiền tố `tg-` vì LÝ DO DỮ LIỆU: chiến dịch đang chạy có sẵn file này, đổi
# tên là bỏ lại toàn bộ phản hồi cũ. Nội dung thì không riêng của Telegram nữa — phản hồi
# gõ trong phiên cũng vào đây, và vòng viết lại đọc chung một chỗ.
FEEDBACK_FILE = "feedback.json"


def loi(m: str) -> None:
    sys.stderr.write(f"approval_gate: {m}\n")


# ── Bảng Content ────────────────────────────────────────────────────────────

def read_content_table(campaign: Path):
    fm, than = md_io.read_fm(Path(campaign) / "campaign.md")
    col, row = md_io.read_table(than, "CONTENT")
    return fm, than, col, row


def post_has_content(campaign: Path, row: dict) -> bool:
    """Bài của DÒNG này đã có chữ thật chưa. Không khai `folder` = chưa viết (fail-closed)."""
    f = (row.get("folder") or "").strip()
    if not f:
        return False
    return post_content.has_content(Path(campaign) / f.lstrip("./"))


def why_not_ready(campaign: Path, row: dict) -> str:
    """Lý do bài này CHƯA được phép đem ra hỏi ở Cổng 2. Chuỗi rỗng = được hỏi.

    FAIL-CLOSED ba nhánh (chủ repo chốt 11/09/2026):
      · chưa viết          — không có gì để đọc
      · chưa chấm cổng nào — KHÔNG ĐO ĐƯỢC nghĩa là *chưa biết*, không phải *đã qua*
      · máy chấm ĐỎ        — máy đã nói không thì đừng đem hỏi người

    Vì sao nhánh giữa quan trọng ngang nhánh cuối: `content.md` đầy đủ **không** chứng minh
    bài đã qua kiểm. Ca thật NEN-002 — gọi thẳng bộ viết, nhảy cóc bước chấm B4, file bài
    trông hoàn hảo mà chưa một cổng nào chạy.

    Trả LÝ DO chứ không trả bool: bỏ qua im lặng thì người vận hành không biết vì sao bài
    của mình không bao giờ tới cổng.
    """
    if not post_has_content(campaign, row):
        return "CHƯA VIẾT"

    f = (row.get("folder") or "").strip()
    p = Path(campaign) / f.lstrip("./") / "gates.json"
    if not p.is_file():
        return "CHƯA CHẤM cổng nào (thiếu gates.json) — chạy blog_gates.py trước"
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "gates.json HỎNG — coi như chưa chấm"

    if (g.get("verdict") or "").lower() == "fail":
        do = [c.get("id", "?") for c in (g.get("gates") or [])
              if c.get("status") == "fail" and c.get("level") != "warn"]
        return (f"máy chấm ĐỎ ({g.get('fail_block', '?')} cổng chặn"
                + (f": {', '.join(do[:8])}" if do else "") + ")")
    return ""


def waiting_at(campaign: Path, gate: str) -> list[dict]:
    """Bài đang chờ đúng cổng đó. g1: chưa có g1. g2: có g1, chưa có g2."""
    _, _, _, row = read_content_table(campaign)
    if gate == "g1":
        return [d for d in row if not (d.get("g1") or "").strip()]
    if gate == "g3":
        # Cổng 3 duyệt BẢN THẬT: phải đã lên web mới có gì để xem. Và chỉ hỏi khi bảng
        # CÓ KHAI cột `g3` — bảng cũ không khai thì không có cổng này.
        return [d for d in row
                if "g3" in d and (d.get("web") or "").strip()
                and not (d.get("g3") or "").strip()]
    return [d for d in row
            if (d.get("g1") or "").strip() and not (d.get("g2") or "").strip()]


def post_files(campaign: Path, row: dict) -> dict:
    """Bài này có những file NÀO ĐANG CÓ THẬT để người mở ra kiểm.

    Đây là phần hay bị bỏ quên nhất của một cổng duyệt: hỏi "duyệt không?" mà không nói
    đọc ở đâu thì người chỉ còn cách gật bừa, và cổng thành con dấu cao su — đúng chỗ
    Cổng 2 đã dính ngày 11/09/2026.

    Chỉ liệt kê file **tồn tại**. Kê một đường dẫn không có thật còn tệ hơn không kê:
    người mở không được sẽ tưởng máy hỏng chứ không hiểu là bước đó chưa chạy.
    """
    campaign = Path(campaign)
    f = (row.get("folder") or "").strip().lstrip("./")
    ho_so: dict = {"content_id": row.get("content_id", ""),
                   "content_name": row.get("content_name", ""),
                   "folder": f, "file": {}, "web": (row.get("web") or "").strip()}
    if not f:
        return ho_so
    post = campaign / f
    for label, tuong_doi in (("bài", "content.md"),
                            ("nghiên cứu", "research.md"),
                            ("chấm cổng", "gates.json"),
                            ("blog tách kênh", "atlas/blog.md"),
                            ("trang dựng sẵn", "atlas/atlas.html"),
                            ("facebook", "facebook/post.txt"),
                            ("youtube", "youtube/description.txt")):
        p = post / tuong_doi
        if p.is_file():
            ho_so["file"][label] = str(p)
    return ho_so


# ── Phản hồi của người ──────────────────────────────────────────────────────

def read_feedback(campaign: Path, cid: str) -> list[dict]:
    """Mọi phản hồi của người cho một bài, theo thứ tự thời gian.

    GIỮ ĐỦ, không ghi đè: vòng viết lại có thể lặp, và ghi đè lần trước là mất dấu vết vì
    sao bài thành ra như thế. Sáu tháng sau đọc lại còn hiểu được.
    """
    p = Path(campaign) / "logs" / FEEDBACK_FILE
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text(encoding="utf-8")) or {}).get(cid, [])
    except json.JSONDecodeError:
        loi(f"{p} hỏng — coi như chưa có phản hồi nào.")
        return []


def write_feedback(campaign: Path, cid: str, text: str) -> None:
    p = Path(campaign) / "logs" / FEEDBACK_FILE
    d = {}
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            pass
    d.setdefault(cid, []).append(
        {"at": datetime.now().astimezone().isoformat(), "text": text})
    p.parent.mkdir(parents=True, exist_ok=True)
    md_io.write_atomic(p, json.dumps(d, ensure_ascii=False, indent=2) + "\n")


# ── Ghi cổng ────────────────────────────────────────────────────────────────

def write_g1(campaign: Path, cids: list[str], day: str) -> list[str]:
    """Ghi cột g1 + status. IDEMPOTENT: bài đã có g1 thì bỏ qua, không ghi đè."""
    campaign = Path(campaign)
    fm, than, _, row = read_content_table(campaign)
    hien = {d["content_id"]: d for d in row}
    done = []
    for cid in cids:
        d = hien.get(cid)
        if d is None:
            loi(f"{cid}: không có trong bảng Content — bỏ qua.")
            continue
        if (d.get("g1") or "").strip():
            continue                       # đã duyệt rồi, không ghi lại
        than = md_io.upsert_row(than, "CONTENT", "content_id",
                                {"content_id": cid, "g1": day, "status": "approved"},
                                chi_cap_nhat=True)
        done.append(cid)
    if done:
        md_io.write_fm(campaign / "campaign.md", fm, than)
    return done


def write_column(campaign: Path, cids: list[str], col: str, gia_tri: str) -> list[str]:
    """Ghi một cột ngày duyệt. IDEMPOTENT: đã có thì bỏ qua, không ghi đè."""
    campaign = Path(campaign)
    fm, than, _, row = read_content_table(campaign)
    hien = {d["content_id"]: d for d in row}
    done = []
    for cid in cids:
        d = hien.get(cid)
        if d is None:
            loi(f"{cid}: không có trong bảng Content — bỏ qua.")
            continue
        if (d.get(col) or "").strip():
            continue
        than = md_io.upsert_row(than, "CONTENT", "content_id",
                                {"content_id": cid, col: gia_tri}, chi_cap_nhat=True)
        done.append(cid)
    if done:
        md_io.write_fm(campaign / "campaign.md", fm, than)
    return done


def write_g2(campaign: Path, cids: list[str], by: str, note: str) -> list[str]:
    """Gọi ĐÚNG `register_publish approve` — giữ nguyên dấu vết duyệt đang có."""
    campaign = Path(campaign)
    _, _, _, row = read_content_table(campaign)
    hien = {d["content_id"]: d for d in row}
    rp = _HERE / "register_publish.py"
    done = []
    for cid in cids:
        d = hien.get(cid)
        if d is None:
            loi(f"{cid}: không có trong bảng Content — bỏ qua.")
            continue
        folder = (d.get("folder") or "").strip().lstrip("./")
        post = campaign / folder
        if not post.is_dir():
            loi(f"{cid}: không thấy thư mục bài {post} — bỏ qua.")
            continue
        r = subprocess.run(
            [sys.executable, str(rp), str(post), "approve", "--by", by, "--note", note],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            loi(f"{cid}: register_publish approve thất bại — {r.stdout}{r.stderr}")
            continue
        done.append(cid)
    return done


# ── Mở / từ chối cổng — lối vào DUY NHẤT của mọi mặt tiền ───────────────────

def _require_witness(by: str, quote: str) -> None:
    """Cổng phải biết AI duyệt và người đó nói GÌ. Thiếu một trong hai là ném lỗi.

    Fail-closed chứ không cảnh báo rồi ghi: một cổng ghi được mà không có chứng nhân thì
    hồ sơ nói "đã duyệt" trong khi không ai duyệt, và không gì phát hiện ra sau đó.
    """
    if not (by or "").strip():
        raise ValueError("thiếu `boi`: cổng phải biết AI duyệt.")
    if not (quote or "").strip():
        raise ValueError(
            "thiếu `quote`: chép NGUYÊN VĂN câu duyệt của người. "
            "Đây là thứ ngăn agent tự đóng dấu thay người.")


def open_gate(campaign: Path, gate: str, cids: list[str], *, by: str, quote: str,
            via: str, now: datetime | None = None) -> list[str]:
    """Mở một cổng cho các bài đã nêu. Trả về danh sách bài THỰC SỰ được ghi.

    Idempotent: bài đã qua cổng thì không nằm trong kết quả và không sinh sự kiện mới.
    KHÔNG xếp việc — xem cảnh báo ở đầu file.
    """
    campaign = Path(campaign)
    if gate not in GATES:
        raise ValueError(f"cổng lạ: {gate!r} — chỉ có {', '.join(GATES)}")
    _require_witness(by, quote)
    now = now or datetime.now().astimezone()

    if gate == "g1":
        done = write_g1(campaign, cids, now.date().isoformat())
    elif gate == "g3":
        done = write_column(campaign, cids, "g3", now.date().isoformat())
    else:
        done = write_g2(campaign, cids, by, quote)

    for cid in done:
        EV.write(campaign, f"{gate}_approved", post=cid, by=by, via=via, note=quote[:300])
    return done


def reject(campaign: Path, gate: str, cids: list[str], *, by: str, quote: str,
            via: str) -> list[str]:
    """Ghi từ chối + phản hồi. KHÔNG đụng vào cổng: từ chối là *chưa duyệt*, không phải xoá.

    Phản hồi vào kho chung để vòng viết lại đọc được. Từ chối mà không nói vì sao thì lần
    viết lại sau cũng ra đúng bài cũ.
    """
    campaign = Path(campaign)
    if gate not in GATES:
        raise ValueError(f"cổng lạ: {gate!r} — chỉ có {', '.join(GATES)}")
    _require_witness(by, quote)
    for cid in cids:
        EV.write(campaign, f"{gate}_rejected", post=cid, by=by, via=via, reason=quote[:300])
        write_feedback(campaign, cid, quote)
    return list(cids)


def revoke_delivery_intent(ledger, intent_id: str, expected_generation: int, *,
                           scope: dict, gate: str, by: str, quote: str) -> str:
    """Revoke one explicitly scoped delivery, not the source campaign approval.

    Generation and state changes are serialized by the ledger. Source gate
    revocation and invalidation of future intents require a separate integration.
    """
    from delivery_ledger import KEY_FIELDS

    _require_witness(by, quote)
    if gate not in GATES:
        raise ValueError(f"cổng lạ: {gate!r}")
    if not isinstance(scope, dict) or set(scope) != set(KEY_FIELDS):
        raise ValueError("delivery scope must identify the complete intent")
    current = ledger.get(intent_id)
    if any(current[field] != scope[field] for field in KEY_FIELDS):
        raise ValueError("delivery intent is outside the requested scope")
    return ledger.revoke(intent_id, expected_generation, by=by, quote=quote, gate=gate)


def check_delivery_local_path(path: Path, *, file: bool = False) -> None:
    """Reject links, Windows reparse points and offline placeholders before read.

    Metadata checks are not a handle-based guarantee against concurrent swaps;
    this is an offline guard, not a boundary against another same-account process.
    """
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise ValueError("delivery source path is missing") from exc
        flags = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or flags & _DELIVERY_FORBIDDEN_ATTRIBUTES:
            raise ValueError("delivery source is a link, reparse point or offline placeholder")
    if file and not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("delivery source must be a regular file")


@contextmanager
def delivery_source_lock(station_root: Path):
    """Exclusive cooperative lock; a crash leaves a lock requiring recovery.

    Only callers using this protocol are serialized. Existing direct writers and
    modifications by the same OS user are not excluded by this lock.
    """
    check_delivery_local_path(Path(station_root))
    root = Path(station_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("station root must be an existing directory")
    directory = root
    for name in ("logs", "publishing"):
        candidate = directory / name
        # Resolve BEFORE every mkdir, not after creating a child of a junction.
        if not candidate.resolve(strict=False).is_relative_to(root):
            raise ValueError("delivery lock directory outside station")
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            candidate.mkdir()
            info = candidate.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (stat.S_ISLNK(info.st_mode)
                or attributes & _DELIVERY_FORBIDDEN_ATTRIBUTES
                or not stat.S_ISDIR(info.st_mode)
                or not candidate.resolve(strict=True).is_relative_to(root)):
            raise ValueError("delivery lock directory must be local and not a reparse point")
        directory = candidate
    path = directory / "source.lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    identity = os.fstat(fd)
    try:
        yield
    finally:
        os.close(fd)
        try:
            existing = path.stat(follow_symlinks=False)
            if (existing.st_dev, existing.st_ino) == (identity.st_dev, identity.st_ino):
                path.unlink()
        except FileNotFoundError:
            pass


def delivery_required_gates(content_row: dict, platform: str, *, content_columns: list[str]) -> tuple[str, ...]:
    """Classify gates from a parsed content row; this never grants approval.

    G3 is optional and applies to Facebook/YouTube only when the campaign
    explicitly declares the column. A blank value still means G3 is required.
    Callers must pass the complete header parsed from the same source table and
    independently validate the row, target, approval evidence,
    and any workflow-specific dependencies before using this classification.
    """
    if (not isinstance(content_row, dict)
            or not isinstance(content_row.get("content_id"), str)
            or not content_row["content_id"].strip()):
        raise ValueError("content row is required")
    if (not isinstance(content_columns, list) or not content_columns
            or any(not isinstance(col, str) or not col.strip() for col in content_columns)
            or len(content_columns) != len(set(content_columns))
            or "content_id" not in content_columns
            or set(content_columns) != set(content_row)):
        raise ValueError("complete content table header and row are required")
    if not isinstance(platform, str) or platform not in {"facebook", "youtube", "instagram", "linkedin", "web_blog"}:
        raise ValueError("unsupported delivery platform")
    gates = ("g1", "g2")
    if "g3" in content_columns and platform in {"facebook", "youtube"}:
        gates += ("g3",)
    return gates


def read_delivery_gate_proof(campaign: Path, scope: dict) -> dict:
    """Read existing gate evidence; it does not bind or approve a payload.

    G1/G3 keep only a date in the source table. An event is required as supporting
    evidence, but events can be truncated, absent or forged by the same account.
    Caller must separately establish payload binding and access controls.
    """
    import studio_paths as SP
    import yaml
    from delivery_ledger import SCOPE_FIELDS

    if not isinstance(scope, dict) or set(scope) != set(SCOPE_FIELDS):
        raise ValueError("invalid approval scope")
    if any(not isinstance(scope[k], str) or not scope[k].strip() for k in SCOPE_FIELDS):
        raise ValueError("empty approval scope")
    gate = scope["gate"]
    if gate not in GATES:
        raise ValueError("invalid approval gate")
    check_delivery_local_path(Path(campaign))
    campaign = Path(campaign).resolve()
    check_delivery_local_path(campaign / "campaign.md", file=True)
    fm, _, _, rows = read_content_table(campaign)
    if fm.get("id") != scope["campaign_id"]:
        raise ValueError("campaign scope mismatch")
    channel = SP.channel_of(campaign)
    check_delivery_local_path(channel / "channel.yml", file=True)
    config = yaml.safe_load((channel / "channel.yml").read_text(encoding="utf-8")) or {}
    if config.get("id") != scope["channel_id"]:
        raise ValueError("channel scope mismatch")
    matches = [r for r in rows if r.get("content_id") == scope["content_id"]]
    if len(matches) != 1:
        raise ValueError("content scope is missing or ambiguous")
    row = matches[0]
    day = (row.get(gate) or "").strip()
    if not day:
        raise ValueError("gate has not been approved")
    if gate in ("g1", "g3"):
        if scope["post_id"] != "*":
            raise ValueError("gate is scoped to the content item")
        check_delivery_local_path(EV.log_path(campaign), file=True)
        events = EV.read(campaign, post=scope["content_id"], n=100)
        events = [e for e in events if e.get("job") == f"{gate}_approved"]
        if not events:
            raise ValueError("human gate evidence unavailable")
        e = events[-1]
        by, quote, via = e.get("by"), e.get("note"), e.get("via")
        if (not isinstance(by, str) or not by.strip() or not isinstance(quote, str)
                or not quote.strip() or len(quote) >= 300 or not isinstance(via, str)
                or not via.strip() or via == "autonomy" or str(e.get("at", ""))[:10] != day):
            raise ValueError("gate evidence is automatic, incomplete or inconsistent")
        source = {"day": day, "event_at": e.get("at"), "via": via}
    else:
        if scope["post_id"] == "*":
            raise ValueError("G2 proof requires one exact post")
        folder = (row.get("folder") or "").strip()
        if not folder:
            raise ValueError("post folder missing")
        check_delivery_local_path(campaign / folder)
        post = (campaign / folder).resolve()
        if not post.is_relative_to(campaign) or post == campaign:
            raise ValueError("post folder outside campaign")
        check_delivery_local_path(post / "publish.json", file=True)
        data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
        posts = [p for p in data.get("posts", []) if p.get("post_id") == scope["post_id"]]
        if len(posts) != 1:
            raise ValueError("post scope is missing or ambiguous")
        item = posts[0]
        review = item.get("review") or {}
        by, quote = review.get("approved_by"), review.get("note")
        # This migration note is an editorial summary, not a person's words.
        # Other nonempty notes still require provenance before a real dispatch.
        if __package__:
            from .register_publish import MIGRATED_REVIEW_NOTE
        else:
            from register_publish import MIGRATED_REVIEW_NOTE
        if quote == MIGRATED_REVIEW_NOTE:
            raise ValueError("migrated G2 note is not verbatim approval")
        if (review.get("status") != "approved" or not review.get("approved_at")
                or not isinstance(by, str) or not by.strip()
                or not isinstance(quote, str) or not quote.strip()
                or "autonomy=full" in quote.lower() or "tự động" in by.lower()):
            raise ValueError("human G2 evidence unavailable")
        qa = item.get("quality_check")
        if qa == "failed":
            override = re.search(r"\[override-qa:\s*([^\]]+)\]", quote)
            if override is None or not override.group(1).strip():
                raise ValueError("failed QA has no recorded override")
        elif qa != "passed":
            raise ValueError("QA has not passed")
        source = {"day": day, "review": review, "quality_check": item.get("quality_check")}
    proof_source = {"scope": scope, "gate": gate, "by": by, "quote": quote, "source": source}
    encoded = json.dumps(proof_source, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"scope": dict(scope), "gate": gate, "by": by, "quote": quote,
            "source_digest": hashlib.sha256(encoded).hexdigest()}


def delivery_payload_digest(scope: dict, payload: dict) -> str:
    """Validate identity-bearing preview fields and hash the complete payload."""
    from delivery_contract import canonical_snapshot

    if not isinstance(scope, dict) or scope.get("gate") != "g2" or scope.get("post_id") == "*":
        raise ValueError("payload binding requires an exact G2 scope")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    for key in ("station_id", "channel_id", "campaign_id", "content_id", "post_id"):
        if not isinstance(payload.get(key), str) or not payload[key] or payload[key] != scope.get(key):
            raise ValueError("payload identity does not match approval scope")
    # One explicit posting occurrence per preview approval. Recurrence grants are
    # not implemented; future cycles need their own approved occurrence.
    for key in ("platform", "account_id", "timezone", "privacy", "occurrence_key"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"payload missing {key}")
    if not isinstance(payload.get("text"), str) or not isinstance(payload.get("artifacts"), list):
        raise ValueError("payload preview requires text and artifacts")
    if "scheduled_at" not in payload or not isinstance(payload["scheduled_at"], (str, type(None))):
        raise ValueError("payload preview requires schedule")
    return canonical_snapshot(payload)[1]


def verify_delivery_payload(campaign: Path, scope: dict, payload: dict) -> dict:
    """Compare a prepared snapshot with an explicit source binding, not identity."""
    proof = read_delivery_gate_proof(campaign, scope)
    check_delivery_local_path(Path(campaign) / "campaign.md", file=True)
    _, _, _, rows = read_content_table(campaign)
    row = next(r for r in rows if r.get("content_id") == scope["content_id"])
    check_delivery_local_path(Path(campaign) / row["folder"])
    post = (Path(campaign).resolve() / row["folder"]).resolve()
    check_delivery_local_path(post / "publish.json", file=True)
    data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
    item = next(p for p in data["posts"] if p.get("post_id") == scope["post_id"])
    binding = (item.get("review") or {}).get("delivery_binding") or {}
    digest = delivery_payload_digest(scope, payload)
    if (binding.get("schema") != "delivery-binding/1" or binding.get("scope") != scope
            or binding.get("payload_digest") != digest or not binding.get("event_id")
            or not (binding.get("by") or "").strip() or not (binding.get("quote") or "").strip()):
        raise ValueError("delivery payload has no matching approval binding")
    return {**proof, "payload_digest": digest, "binding_event_id": binding["event_id"]}


# ── CLI trong phiên ─────────────────────────────────────────────────────────

def _print_waiting(campaign: Path, gate: str, *, ra_json: bool) -> int:
    ds = waiting_at(campaign, gate)
    ho_so = []
    for d in ds:
        h = post_files(campaign, d)
        if gate == "g2":
            h["not_ready"] = why_not_ready(campaign, d)
        ho_so.append(h)

    if ra_json:
        print(json.dumps({"gate": gate, "count": len(ho_so), "post": ho_so},
                         ensure_ascii=False, indent=2))
        return 0

    if not ho_so:
        print(f"{gate}: không bài nào đang chờ.")
        return 0

    # TÁCH HAI NHÓM. Cổng 2 gọi là "đang chờ" cả những bài mới chỉ có dòng trong bảng —
    # chúng chưa viết nên không có file nào để mở. Trộn chung thì một lô 20 bài đổ ra 20
    # mục dài, người phải tự dò xem mục nào thật sự cần đọc. Bản JSON giữ nguyên cả hai
    # nhóm: máy không cần được chiều, người thì cần.
    ready = [h for h in ho_so if not h.get("not_ready")]
    chua = [h for h in ho_so if h.get("not_ready")]

    print(f"{gate}: {len(ready)}/{len(ho_so)} bài sẵn sàng hỏi\n")
    for h in ready:
        print(f"· {h['content_id']} — {h['content_name']}")
        for label, p in h["file"].items():
            print(f"    {label:<16} {p}")
        if h["web"]:
            print(f"    {'bản thật':<16} {h['web']}")
        print()
    if chua:
        print(f"Chưa được đem ra hỏi ({len(chua)} bài):")
        for h in chua:
            print(f"  ⛔ {h['content_id']:<10} {h['not_ready']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Cổng duyệt — mặt tiền TRONG PHIÊN, không cần Telegram.")
    ap.add_argument("campaign", help="thư mục chiến dịch")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("waiting", help="bài nào đang chờ cổng, kèm file để mở kiểm")
    pc.add_argument("--gate", choices=list(GATES), required=True)
    pc.add_argument("--json", action="store_true")

    for name, tro in (("open", "mở cổng"), ("reject", "ghi từ chối + phản hồi")):
        p = sub.add_parser(name, help=tro)
        p.add_argument("--gate", choices=list(GATES), required=True)
        p.add_argument("--post", required=True, help="mã bài, phân tách bằng dấu phẩy")
        p.add_argument("--by", required=True, help="ai duyệt")
        p.add_argument("--quote", required=True,
                       help="NGUYÊN VĂN câu người nói — agent KHÔNG được tự bịa")
        p.add_argument("--via", default="phiên", help="mặt tiền nào (mặc định: phiên)")

    a = ap.parse_args(argv)
    campaign = Path(a.campaign)
    if not (campaign / "campaign.md").is_file():
        loi(f"không thấy {campaign / 'campaign.md'}")
        return 2

    if a.cmd == "waiting":
        return _print_waiting(campaign, a.gate, ra_json=a.json)

    cids = [x.strip() for x in a.post.split(",") if x.strip()]
    if not cids:
        loi("--post rỗng")
        return 2
    try:
        if a.cmd == "open":
            done = open_gate(campaign, a.gate, cids, by=a.by,
                           quote=a.quote, via=a.via)
            print(f"{a.gate}: đã mở cho {len(done)}/{len(cids)} bài"
                  + (f" — {', '.join(done)}" if done else " (không bài nào đổi)"))
        else:
            done = reject(campaign, a.gate, cids, by=a.by,
                           quote=a.quote, via=a.via)
            print(f"{a.gate}: đã ghi từ chối {len(done)} bài — {', '.join(done)}")
    except ValueError as e:
        loi(str(e))
        return 2
    # Không bài nào đổi ≠ hỏng: idempotent nghĩa là chạy lại vẫn 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
