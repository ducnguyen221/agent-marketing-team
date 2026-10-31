# -*- coding: utf-8 -*-
"""Subagent của plugin (`agents/`) phải chỉ-đọc, khai `tools` rõ, và tự kích hoạt (SPR-04 TK8, RQ-011).

Claude Code nạp mọi `*.md` trong `agents/` thành một subagent (kể cả README.md), nên thư mục này chỉ
được chứa file agent. Thiếu khoá `tools` là nhận MỌI công cụ (kể cả Write, Bash): hàm kiểm dưới đây
coi thiếu hoặc rỗng là lỗi, và có một ca âm để chứng minh hàm kiểm bắt được điều đó.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
TOOL_CHI_DOC = {"Read", "Grep", "Glob", "WebSearch", "WebFetch"}
TOOL_GHI = {"Edit", "Write", "Bash", "NotebookEdit"}
MODEL_HOP_LE = {"sonnet", "opus", "haiku", "inherit"}
_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _frontmatter(text: str) -> dict:
    """Khối frontmatter dạng `khoá: giá trị` (một dòng; `>` hay `'...'` được bóc thô)."""
    m = _FM.match(text.replace("\r\n", "\n"))
    if not m:
        return {}
    out, khoa = {}, None
    for dong in m.group(1).split("\n"):
        k = re.match(r"^([A-Za-z_-]+):\s*(.*)$", dong)
        if k:
            khoa = k.group(1)
            out[khoa] = k.group(2).strip().strip("'\"")
        elif khoa and dong.strip():
            out[khoa] = (out[khoa] + " " + dong.strip().strip("'\"")).strip()
    return out


def kiem_frontmatter(text: str, ten: str) -> list[str]:
    fm = _frontmatter(text)
    loi = []
    for khoa in ("name", "description", "tools", "model"):
        if khoa not in fm:
            loi.append(f"thiếu {khoa}")
    if "name" in fm and fm["name"] != ten:
        loi.append(f"name {fm['name']!r} khác tên file {ten!r}")
    if len(fm.get("description", "")) > 1024:
        loi.append("description quá 1024 ký tự")
    if "tools" in fm:
        tools = [t.strip() for t in fm["tools"].split(",") if t.strip()]
        if not tools:
            loi.append("tools rỗng")
        ngoai = set(tools) - TOOL_CHI_DOC
        if ngoai:
            loi.append(f"tools ngoài danh sách chỉ-đọc: {sorted(ngoai)}")
    if "model" in fm and fm["model"] not in MODEL_HOP_LE:
        loi.append(f"model không hợp lệ: {fm['model']!r}")
    return loi


def _agents() -> list[Path]:
    return sorted(AGENTS.glob("*.md"))


def test_thu_muc_agents_co_that_va_khong_README():
    assert AGENTS.is_dir()
    ten = [p.name for p in _agents()]
    assert ten, "agents/ không có file nào"
    assert "README.md" not in [n for n in ten], "README.md trong agents/ sẽ bị nạp thành một agent"
    assert sorted(p.name for p in AGENTS.iterdir()) == ten, "agents/ chỉ chứa file agent *.md"


def test_moi_agent_frontmatter_hop_le():
    for p in _agents():
        assert kiem_frontmatter(p.read_text(encoding="utf-8"), p.stem) == [], p.name


def test_co_agent_tu_kich_hoat():
    assert any("PROACTIVELY" in p.read_text(encoding="utf-8") for p in _agents())


def test_agent_khong_co_quyen_ghi():
    for p in _agents():
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        assert tools, f"{p.name}: tools rỗng hoặc thiếu = nhận mọi công cụ"
        assert not (tools & TOOL_GHI), (p.name, sorted(tools & TOOL_GHI))


def test_kiem_bat_duoc_thieu_tools():
    """Ca âm: frontmatter không có `tools` phải bị hàm kiểm báo lỗi."""
    text = "---\nname: x\ndescription: mô tả\nmodel: sonnet\n---\nThân.\n"
    assert "thiếu tools" in kiem_frontmatter(text, "x")
    text_rong = "---\nname: x\ndescription: mô tả\ntools:\nmodel: sonnet\n---\nThân.\n"
    assert "tools rỗng" in kiem_frontmatter(text_rong, "x")
    text_ghi = "---\nname: x\ndescription: d\ntools: Read, Write\nmodel: sonnet\n---\n"
    assert any("ngoài danh sách chỉ-đọc" in e for e in kiem_frontmatter(text_ghi, "x"))


def test_manifest_khong_khai_agents():
    """Claude Code nạp thư mục mặc định `agents/`; khai thêm có thể nạp trùng (RF13).

    Nếu kiểm khói phiên mới không thấy subagent thì khai `agents` và đổi test này (ghi Phán quyết).
    """
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "agents" not in manifest
