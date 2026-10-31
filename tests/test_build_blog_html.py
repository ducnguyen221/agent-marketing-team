# -*- coding: utf-8 -*-
"""Test cho bộ dựng markdown → HTML của trang atlas.

Ba lỗi dưới đây đều bị bắt trên bài thật AST-001, không phải nghĩ ra: trang xuất bản ra
có 6 khối <ol> cho 2 danh sách (mục nào cũng đánh số "1."), in nguyên hai dấu sao của mọi
cụm nghiêng, và có 2 đoạn văn chỉ chứa ba dấu gạch. Không cổng nào bắt được vì cổng chỉ
đếm thẻ og:, không đọc phần thân trang.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
from build_blog_html import md_to_html  # noqa: E402


def test_muc_list_xuong_dong_khong_bi_cat():
    """Một mục list dài xuống dòng phải nằm trong CÙNG <li>, không tách ra <p> lẻ."""
    h = md_to_html("1. **Một** dòng đầu\n   dòng nối\n2. Hai\n\nĐoạn sau.")
    assert h.count("<ol>") == 1, "danh sách bị cắt thành nhiều khối -> mọi mục đánh số 1."
    assert h.count("<li>") == 2
    assert "dòng đầu dòng nối" in h, "phần nối rơi ra ngoài <li>"
    assert "<p>Đoạn sau.</p>" in h, "đoạn văn sau danh sách vẫn phải là đoạn văn riêng"


def test_bullet_list_cung_gom_dong_noi():
    h = md_to_html("- Mục một\n  phần nối\n- Mục hai\n")
    assert h.count("<ul>") == 1 and h.count("<li>") == 2
    assert "Mục một phần nối" in h


def test_nghieng_don_va_duong_ke_ngang():
    h = md_to_html('Theo X: *"trích"* xong.\n\n---\n\n*Ghi chú.*')
    assert "<em>" in h, "cụm *nghiêng* in ra nguyên dấu sao trên trang xuất bản"
    assert "<hr>" in h
    assert "<p>---</p>" not in h, "dấu ngắt là đường kẻ, không phải đoạn văn ba dấu gạch"


def test_dau_sao_phep_nhan_khong_thanh_nghieng():
    """Ranh giới: đừng chữa một lỗi bằng cách tạo ra lỗi khác."""
    assert "<em>" not in md_to_html("2 * 3 * 4")
    assert "<em>" not in md_to_html("a*b*c")


def test_dam_van_chay_va_khong_bi_nghieng_an_mat():
    h = md_to_html("**đậm** và *nghiêng* trong một dòng")
    assert "<strong>đậm</strong>" in h and "<em>nghiêng</em>" in h


# ══ REVIEW-P2 N15 — lỗi `brand:` phải là mã 2 ở MỌI nhánh ═══════════════════
# `BR.doc()` nằm trong `try` nên thiếu khoá bắt buộc ra mã 2 đúng như commit tuyên bố.
# Nhưng `BR.socials()` / `BR.icon()` chạy bên TRONG `build_html_full()`, và lời gọi đó
# nằm NGOÀI `try` — nên `icon: linkedin` (không có trong kho) hay `socials[0]` thiếu
# `url` cho exit 1 = "thử lại được", và lịch chạy retry mãi một lỗi `channel.yml`.

import json as _json  # noqa: E402
import subprocess as _sp  # noqa: E402
import sys as _sys  # noqa: E402

import pytest as _pt  # noqa: E402

_BBH = ROOT / "scripts" / "pipeline" / "build_blog_html.py"


def _du_an(tmp_path, brand_them: dict, meta_them=None, tieu_de="Tieu de"):
    brand = {"site_name": "Trang Thu", "author": "Nguoi Viet",
             "site_base": "https://vi-du.test", **brand_them}
    (tmp_path / "brand.json").write_text(_json.dumps({"brand": brand}), encoding="utf-8")
    (tmp_path / "bai.md").write_text(f"# {tieu_de}\n\nMot doan.\n", encoding="utf-8")
    meta = {"slug": "bai", "title": "Tieu de"}
    meta.update(meta_them or {})
    meta = {k: v for k, v in meta.items() if v is not None}
    (tmp_path / "meta.json").write_text(_json.dumps(meta), encoding="utf-8")
    return _sp.run([_sys.executable, str(_BBH), "--blog-md", str(tmp_path / "bai.md"),
                    "--meta", str(tmp_path / "meta.json"),
                    "--brand", str(tmp_path / "brand.json"),
                    "--out", str(tmp_path / "ra.html")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")


@_pt.mark.parametrize("brand_them, vi_sao", [
    ({"socials": [{"icon": "linkedin", "url": "https://vi-du.test/x"}]}, "icon la"),
    ({"socials": [{"icon": "website"}]}, "socials thieu url"),
])
def test_brand_sai_o_socials_la_ma_2_khong_phai_1(tmp_path, brand_them, vi_sao):
    r = _du_an(tmp_path, brand_them)
    assert r.returncode == 2, f"{vi_sao}: mã {r.returncode}\n{r.stderr}"
    assert not (tmp_path / "ra.html").exists(), "đã hỏng mà vẫn ghi ra file"


def test_brand_du_thi_van_dung_duoc(tmp_path):
    r = _du_an(tmp_path, {"socials": [{"icon": "website", "url": "https://vi-du.test"}]})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ra.html").is_file()


# ══ SPR-04 TK7 (RQ-012) — JSON-LD `Article` và canonical khi thiếu slug ════════
import re as _re  # noqa: E402

_LD = _re.compile(r'<script type="application/ld\+json">(.*?)</script>', _re.S)


def _html(tmp_path) -> str:
    return (tmp_path / "ra.html").read_text(encoding="utf-8")


def _khoi_jsonld(html: str) -> str:
    khoi = _LD.findall(html)
    assert len(khoi) == 1, f"phải có đúng một khối JSON-LD, thấy {len(khoi)}"
    return khoi[0]


def test_jsonld_article_co_slug(tmp_path):
    r = _du_an(tmp_path, {"og_image": "https://vi-du.test/mac-dinh.jpg"},
               {"angle": "Mot goc nhin", "schedule_date": "2026-11-01"})
    assert r.returncode == 0, r.stderr
    html = _html(tmp_path)
    ld = _json.loads(_khoi_jsonld(html))
    url = "https://vi-du.test/content/ai/bai.html"
    assert ld["@context"] == "https://schema.org" and ld["@type"] == "Article"
    assert ld["headline"] == "Tieu de" and ld["description"] == "Mot goc nhin"
    assert ld["mainEntityOfPage"]["@id"] == url and ld["url"] == url
    assert ld["image"] == ["https://vi-du.test/content/ai/bai.jpg"]
    assert ld["author"] == {"@type": "Person", "name": "Nguoi Viet"}
    assert ld["publisher"] == {"@type": "Organization", "name": "Trang Thu"}
    assert ld["datePublished"] == "2026-11-01" and ld["inLanguage"] == "vi"
    assert f'<link rel="canonical" href="{url}">' in html
    assert f'<meta property="og:url" content="{url}">' in html


def test_thieu_slug_khong_canonical(tmp_path):
    r = _du_an(tmp_path, {"og_image": "https://vi-du.test/mac-dinh.jpg"}, {"slug": ""})
    assert r.returncode == 0, r.stderr
    assert "thiếu slug" in r.stderr
    html = _html(tmp_path)
    assert 'rel="canonical"' not in html
    assert 'property="og:url"' not in html, "bỏ cả og:url, không trỏ về trang chủ"
    ld = _json.loads(_khoi_jsonld(html))
    assert "mainEntityOfPage" not in ld and "url" not in ld
    assert 'property="og:image" content="https://vi-du.test/mac-dinh.jpg"' in html


def test_jsonld_thoat_dong_script(tmp_path):
    xau = "Tieu de </script><!--<script>x"
    r = _du_an(tmp_path, {}, tieu_de=xau)
    assert r.returncode == 0, r.stderr
    khoi = _khoi_jsonld(_html(tmp_path))
    assert "<" not in khoi and ">" not in khoi, "ký tự < > thô trong khối JSON-LD"
    assert _json.loads(khoi)["headline"] == xau


def test_jsonld_giu_nguyen_chuoi_goc(tmp_path):
    xau = 'A & B "C"'
    r = _du_an(tmp_path, {}, tieu_de=xau)
    assert r.returncode == 0, r.stderr
    html = _html(tmp_path)
    khoi = _khoi_jsonld(html)
    assert "&" not in khoi
    assert _json.loads(khoi)["headline"] == xau
    assert "A &amp; B" in html, "<title> vẫn phải được _esc"


# ══ Chèn mã qua MỌI trường đi vào JSON-LD, gọi hàm trực tiếp (đo coverage được) ═══════════
import html.parser as _hp  # noqa: E402
from build_blog_html import _article_jsonld, build_html_full  # noqa: E402

_PAYLOAD = [
    "X </script><script>alert(1)</script>",
    "<!--<script>x",
    'A & B "C" \'D\'',
    "</SCRIPT >",
    "]]> <![CDATA[",
    "&amp; pre",
    "dòng một\u2028dòng hai",
]


class _DemScript(_hp.HTMLParser):
    def __init__(self):
        super().__init__()
        self.n = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.n += 1


def _gia_tri_goc(ld, truong):
    return {"headline": ld["headline"], "description": ld["description"],
            "author": ld["author"]["name"], "site_name": ld["publisher"]["name"],
            "schedule_date": ld.get("datePublished")}[truong]


@_pt.mark.parametrize("truong", ["headline", "description", "author", "site_name", "schedule_date"])
@_pt.mark.parametrize("xau", _PAYLOAD)
def test_jsonld_chong_chen_ma_qua_moi_truong(truong, xau):
    """Payload nằm ở từng trường (title, angle, author, site_name, schedule_date): khối JSON-LD
    không có `<` `>` `&` thô, trang chỉ có đúng một thẻ <script>, `json.loads` trả đúng chuỗi gốc."""
    brand = {"site_name": "Trang Thu", "author": "Nguoi Viet", "site_base": "https://vi-du.test"}
    meta = {"slug": "bai", "angle": "mo ta"}
    md = "# Tieu de\n\nMot doan.\n"
    if truong == "headline":
        md = f"# {xau}\n\nMot doan.\n"
    elif truong == "description":
        meta["angle"] = xau
    elif truong == "author":
        brand["author"] = xau
    elif truong == "site_name":
        brand["site_name"] = xau
    else:
        meta["schedule_date"] = xau
    html = build_html_full(md, meta, "", brand=brand)
    khoi = _LD.findall(html)
    assert len(khoi) == 1
    assert not any(c in khoi[0] for c in "<>&"), "ký tự < > & thô trong khối JSON-LD"
    dem = _DemScript()
    dem.feed(html)
    assert dem.n == 1, "payload mở thêm thẻ <script>"
    ld = _json.loads(khoi[0])
    goc = xau.strip() if truong == "headline" else xau
    assert _gia_tri_goc(ld, truong) == goc


def test_article_jsonld_bo_khoa_khong_co_du_lieu():
    """Gọi thẳng: thiếu URL/ảnh/ngày thì bỏ khoá, không ghi rỗng."""
    ld = _json.loads(_LD.findall(_article_jsonld("T", "D", "A", "S", "", "", ""))[0])
    assert set(ld) == {"@context", "@type", "headline", "description", "author", "publisher", "inLanguage"}
    day_du = _json.loads(_LD.findall(_article_jsonld("T", "D", "A", "S", "https://x.test/a.html",
                                                     "https://x.test/a.jpg", "2026-11-01"))[0])
    assert day_du["url"] == day_du["mainEntityOfPage"]["@id"] == "https://x.test/a.html"
    assert day_du["image"] == ["https://x.test/a.jpg"] and day_du["datePublished"] == "2026-11-01"
