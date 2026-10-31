# -*- coding: utf-8 -*-
"""Test cho standalone_blog.py (SPR-04 TK3, RQ-007): dựng thư mục tạm, chấm cổng, tự dọn.

Mọi ca chạy trong `tmp_path` sau `monkeypatch.chdir`, nên `.tmp/standalone-blog` của cwd là
thư mục của test — không ghi vào cây repo. Bảy ca, mỗi hành vi của PLAN một ca (PLAN viết
«6 test» cho 7 hành vi; ở đây viết đủ 7, không ghép).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import standalone_blog as SB  # noqa: E402
import blog_gates as G  # noqa: E402
import post_paths as PP  # noqa: E402

HOME = "vidu.vn"


def _bai_xanh_md() -> str:
    """Nội dung blog của fixture `bai_xanh` ở test_blog_gates.py (chỉ phần blog.md)."""
    than = "\n\n".join(
        [f"## Mục {i}\n\nMột đoạn nội dung. " * 3 for i in range(1, 9)]
    )
    return (
        "# Tiêu đề\n\n" + than + "\n\n"
        + "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        + "".join(f"> 💡 Callout số {i}\n\n" for i in range(1, 5))
        + "> **Góc nhìn:** " + "chính kiến của tác giả nói rõ ra. " * 12 + "\n\n"
        + "Theo Reuters, số liệu như vậy. Theo mình thì khác.\n\n"
        + "\n## Nguồn tham khảo\n\n"
        + "\n".join(f"- Nguồn {i}: https://vidu{i}.com/bai-viet (truy cập 04/09/2026)"
                    for i in range(1, 5))
        + "\n\n" + "thêm chữ cho đủ dài. " * 500
    )


def _research_md() -> str:
    return ("---\nkey_sources: bảng nguồn\n---\n\n"
            + "\n".join(f"| {i} | https://vidu{i}.com/goc | tác giả {i} |" for i in range(1, 5)))


@pytest.fixture
def vung(tmp_path, monkeypatch):
    """cwd = tmp_path; trả về (thư mục làm việc, gốc thư mục tạm của script)."""
    monkeypatch.chdir(tmp_path)
    blog = tmp_path / "bai-moi.md"
    blog.write_text(_bai_xanh_md(), encoding="utf-8", newline="\n")
    return tmp_path, tmp_path / ".tmp" / "standalone-blog"


def _con(goc: Path) -> list:
    return list(goc.glob("*")) if goc.exists() else []


def test_bai_xanh_in_bang_va_don_sach(vung, capsys):
    tmp, goc = vung
    rc = SB.main(["--blog", str(tmp / "bai-moi.md"), "--home-domain", HOME])
    out = capsys.readouterr().out
    assert rc == 0
    assert "G01" in out and "G24" in out, "phải in bảng 24 cổng"
    assert _con(goc) == [], "không --keep thì thư mục tạm phải được xoá"
    assert not goc.exists() and not (tmp / ".tmp").exists(), \
        "gốc/.tmp do script tạo và đã rỗng thì phải dọn luôn (RF6)"


def test_keep_json_only_giu_thu_muc_va_stdout_la_json(vung, capsys):
    tmp, goc = vung
    rc = SB.main(["--blog", str(tmp / "bai-moi.md"), "--home-domain", HOME,
                  "--keep", "--json-only"])
    cap = capsys.readouterr()
    assert rc == 0
    json.loads(cap.out)                      # stdout vẫn là JSON thuần
    dong = [x for x in cap.err.splitlines() if x.startswith("GIỮ ")]
    assert len(dong) == 1, "dòng GIỮ phải ra stderr, đúng một lần"
    d = Path(dong[0][len("GIỮ "):])
    assert d.is_dir() and d.is_relative_to(goc.resolve())
    assert PP.p(d, "gates").exists(), "gates.json phải nằm trong thư mục giữ lại"


def test_thieu_mien_va_brand_thoat_2_khong_tao_thu_muc(vung, capsys):
    tmp, goc = vung
    rc = SB.main(["--blog", str(tmp / "bai-moi.md")])
    assert rc == 2
    assert "--home-domain" in capsys.readouterr().err
    assert _con(goc) == [] and not goc.exists()


def test_blog_hoac_research_khong_co_thoat_2_khong_tao_thu_muc(vung, capsys):
    tmp, goc = vung
    rc = SB.main(["--blog", str(tmp / "khong-co.md"), "--home-domain", HOME])
    assert rc == 2
    assert "không thấy file bài" in capsys.readouterr().err
    rc = SB.main(["--blog", str(tmp / "bai-moi.md"), "--research", str(tmp / "khong-co.md"),
                  "--home-domain", HOME])
    assert rc == 2
    assert "không thấy file bài" in capsys.readouterr().err
    assert not goc.exists()


def test_research_duoc_chep_cho_G05(vung, capsys):
    tmp, goc = vung
    (tmp / "r.md").write_text(_research_md(), encoding="utf-8", newline="\n")
    rc = SB.main(["--blog", str(tmp / "bai-moi.md"), "--research", str(tmp / "r.md"),
                  "--home-domain", HOME, "--keep", "--json-only"])
    cap = capsys.readouterr()
    assert rc == 0
    ket = json.loads(cap.out)
    g05 = {r["id"]: r for r in ket["gates"]}["G05"]
    assert "thiếu research.md" not in g05["note"]
    # đối chứng: không --research thì G05 nói thiếu
    rc = SB.main(["--blog", str(tmp / "bai-moi.md"), "--home-domain", HOME, "--json-only"])
    ket = json.loads(capsys.readouterr().out)
    assert "thiếu research.md" in {r["id"]: r for r in ket["gates"]}["G05"]["note"]


def test_khong_xoa_bai_dau_vao(vung, capsys):
    """`--blog` nằm sẵn trong OUT_ROOT: script chỉ xoá thư mục CHÍNH NÓ vừa tạo."""
    tmp, goc = vung
    goc.mkdir(parents=True)
    bai = goc / "bai-cua-toi.md"
    bai.write_text(_bai_xanh_md(), encoding="utf-8", newline="\n")
    SB.main(["--blog", str(bai), "--home-domain", HOME])
    assert bai.is_file(), "bài đầu vào bị xoá"
    assert _con(goc) == [bai]


def test_blog_gates_nem_loi_van_don(vung, monkeypatch):
    tmp, goc = vung

    def hong(_argv):
        raise RuntimeError("blog_gates hỏng giữa chừng")

    monkeypatch.setattr(G, "main", hong)
    with pytest.raises(RuntimeError):
        SB.main(["--blog", str(tmp / "bai-moi.md"), "--home-domain", HOME])
    assert _con(goc) == [], "lỗi lan ra ngoài nhưng thư mục tạm phải đã dọn"


def test_loi_khi_chep_sau_mkdir_khong_bo_lai_thu_muc(vung, monkeypatch):
    """Hồi quy RF1 (review lô A): bước chép lỗi SAU `mkdir` thì thư mục tạm không được sót."""
    tmp, goc = vung
    (tmp / "r.md").write_text(_research_md(), encoding="utf-8", newline="\n")
    that = SB.shutil.copyfile
    dem = {"n": 0}

    def hong_o_lan_hai(src, dst, *a, **k):
        dem["n"] += 1
        if dem["n"] == 2:
            raise PermissionError("tệp đang bị khoá")
        return that(src, dst, *a, **k)

    monkeypatch.setattr(SB.shutil, "copyfile", hong_o_lan_hai)
    with pytest.raises(PermissionError):
        SB.main(["--blog", str(tmp / "bai-moi.md"), "--research", str(tmp / "r.md"),
                 "--home-domain", HOME])
    assert dem["n"] == 2
    assert _con(goc) == [], "thư mục tạm bị bỏ lại khi chép lỗi"
    assert not goc.exists(), "gốc rỗng do script tạo phải được dọn (RF6)"
