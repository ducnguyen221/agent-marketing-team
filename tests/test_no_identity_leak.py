# -*- coding: utf-8 -*-
r"""Cổng chống rò rỉ danh tính máy/người vào repo PUBLIC.

Phân biệt hai thứ hay bị gộp làm một:

1. **Danh tính máy & người** — đường dẫn thư mục nhà của người dùng, email cá nhân, token.
   Đây là rò rỉ THẬT, và cổng này chặn CỨNG trên toàn cây git-tracked.
   Lịch sử: 14 file từng mang đường dẫn home của tác giả sau đợt cutover 04/09, lọt qua
   vì lệnh kiểm lúc đó nhét thẳng đường dẫn Windows vào regex — dấu gạch chéo ngược đứng
   trước chữ hoa bị hiểu là escape, nên pattern không khớp chữ literal và trả về "sạch".
   Âm tính giả. (Cố ý KHÔNG viết lại đường dẫn đó ở đây: file này cũng bị chính nó quét.)
   ⇒ Ở đây dùng so khớp CHUỖI THẲNG (`in`), không dùng regex, để không tái lập lỗi đó.

2. **Tên thương hiệu / tổ chức** của chủ repo — có mặt hợp lệ ở nhiều nơi: `content/` là
   instance mẫu cố ý đưa vào git, `output_styles/*.md` là hồ sơ giọng của chính thương
   hiệu đó. Cổng này KHÔNG chặn chúng trên toàn cây; chỉ giữ sạch `fixtures/`, nơi số liệu
   phải trung tính để dùng làm mốc đối chứng.
3. **Cổng ĐẾM** (cuối file) — bắc cầu giữa hai loại trên. Nó quét CẢ CÂY và miễn trừ
   **theo số đếm chính xác**, không miễn cả file: mỗi mục ghi số lần kỳ vọng hôm nay.
   Nhét thêm một chỗ vào file đã được miễn cũng đỏ. Cùng khuôn với cổng của
   `agent-voice-studio`/`agent-video-studio` để ba repo đọc như nhau.
"""
import re
import subprocess
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# So khớp chuỗi thẳng — KHÔNG regex (xem docstring).
# Backslash dựng bằng chr(92) thay vì viết literal: chuỗi này đi qua nhiều tầng
# (heredoc shell -> file -> parser Python), mỗi tầng ăn một lớp escape khác nhau.
# Đây không phải cẩn thận thừa: đúng lỗi đó vừa làm hỏng dòng $ATLAS trong
# publish-<tên kênh>.ps1 ( thành ký tự BEL) và làm file này không parse được 2 lần.
_BS = chr(92)
CAM_TUYET_DOI = [
    "C:" + _BS + "Users" + _BS,   # bất kỳ đường home Windows nào, không riêng của ai
    "/" + "home" + "/",           # tương đương trên Linux
    "/" + "Users" + "/",          # tương đương trên macOS — máy ĐÍCH của cuộc di trú này
    # Ba chuoi tren deu DUNG TU MANH, khong viet literal: file nay nam trong cay
    # git-tracked nen chinh no bi quet. Viet literal = cong luon do vi chinh no.
    # Luat cua macOS vang mat toi tan 20/09 (REVIEW-P2 N10): ca pha nay la de chay tren
    # macOS va repo la PUBLIC da push, nen lo do se mo ra dung luc bat dau dung. Test nao
    # can mot duong nha macOS GIA lam du lieu thi cung ghep tu manh nhu o day.
]
# Email cá nhân: dùng MẪU chứ không viết literal. Bản trước ghi thẳng địa chỉ vào đây rồi
# tự miễn trừ chính file này — tức cổng mang sẵn thứ nó đi tìm, và không bao giờ thấy.
# Tổng quát hoá (RQ-136): MỌI địa chỉ email (tên + a-còng + tên miền), không riêng 5 webmail `.com` —
# địa chỉ công ty/trường học/tên miền riêng rò ra cũng là rò thật. Ngoại lệ duy nhất theo
# MẪU (không theo file): placeholder thuộc miền DÀNH RIÊNG (RFC 2606/6761) — `example.com|net|org`
# hoặc tên miền kết thúc bằng `.test|.example|.invalid|.localhost`. `example.vn` KHÔNG nằm trong đó.
MAU_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
MAU_EMAIL_GIU_CHO = re.compile(
    r"@(?:example\.(?:com|net|org)|[a-z0-9.-]+\.(?:test|example|invalid|localhost))$", re.I)
# Miễn trừ thêm, cũng theo MẪU (không theo file, không nới EMAIL_MIEN_TRU):
#   · remote SSH `git@<host>:` — hình dạng email nhưng là địa chỉ kho mã;
#   · tên file ảnh nhiều độ phân giải, đúng dạng `<tên>@<số>x.<đuôi ảnh>` (ví dụ logo@2x.png) —
#     CHỈ dạng này; địa chỉ thật bọc trong tên file ảnh (avatar-<email>.png) vẫn đỏ.
# KHÔNG miễn `noreply@`/`no-reply@`: cây hiện không có chuỗi nào như vậy, và hộp thư riêng
# đặt tên noreply vẫn là hộp thư — muốn cho phép thì phải thêm miễn trừ có số đếm.
MAU_EMAIL_SSH = re.compile(r"\bgit@[A-Za-z0-9.-]+:")
MAU_EMAIL_ASSET = re.compile(r"@\d+x\.(?:png|jpe?g|gif|svg|webp)$", re.I)
# Email liên hệ của tác giả: chủ dự án chủ động công khai ở khối author/owner của manifest
# và mục Tác giả của README. Chỉ miễn ĐÚNG địa chỉ này (dựng bằng ghép chuỗi để file test
# không tự chứa nó), đếm chính xác từng file; mọi địa chỉ khác đếm từ 0 ở mọi file.
EMAIL_TG = "ducng" + "uyen.ams" + "@" + "gmail" + ".com"
EMAIL_MIEN_TRU = {
    ".claude-plugin/plugin.json": 1,
    ".claude-plugin/marketplace.json": 1,
    ".codex-plugin/plugin.json": 1,
    "README.md": 1,
}
# Token: cái này buộc phải là regex vì bắt theo hình dạng.
MAU_TOKEN = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{24,}"),
    re.compile(r"(?:AIza)[A-Za-z0-9_\-]{30,}"),
    re.compile(r"\bEAA[A-Za-z0-9]{40,}"),          # Facebook Graph token
]
NHI_PHAN = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".mp3", ".mp4", ".woff", ".woff2", ".pdf"}


def _tracked() -> list[Path]:
    ra = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [ROOT / p for p in ra.stdout.decode().split("\0") if p]


def _doc(p: Path) -> str:
    """Trả về nội dung đọc được. .xlsx là zip -> phải mở ra đọc XML bên trong."""
    if p.suffix.lower() == ".xlsx":
        try:
            with zipfile.ZipFile(p) as z:
                return "\n".join(
                    z.read(n).decode("utf-8", "ignore")
                    for n in z.namelist() if n.endswith((".xml", ".rels"))
                )
        except zipfile.BadZipFile:
            return ""
    if p.suffix.lower() in NHI_PHAN:
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


FILES = [(p, _doc(p)) for p in _tracked()]


def test_co_file_de_quet():
    """Cổng quét 0 file là cổng luôn xanh — vô dụng. Chặn ngay tại đây."""
    assert len(FILES) > 20, f"chỉ thấy {len(FILES)} file git-tracked, nghi lỗi môi trường"
    assert any(p.suffix == ".xlsx" for p, _ in FILES), "phải có ít nhất 1 .xlsx để chứng minh nhánh đọc zip có chạy"


@pytest.mark.parametrize("campaign", CAM_TUYET_DOI)
def test_khong_ro_ri_danh_tinh(campaign):
    dinh = []
    for p, text in FILES:
        if campaign in text:
            row = text[:text.index(campaign)].count("\n") + 1
            dinh.append(f"{p.relative_to(ROOT).as_posix()}:{row}")
    assert not dinh, f"chuỗi {campaign!r} xuất hiện trong repo public tại: {dinh[:12]}"


def test_khong_lo_token():
    dinh = []
    for p, text in FILES:
        rel = p.relative_to(ROOT).as_posix()
        for mau in MAU_TOKEN:
            if mau.search(text):
                dinh.append(f"{rel} ({mau.pattern[:18]}…)")
        dinh.extend(vi_pham_email(rel, text))
    assert not dinh, f"có chuỗi hình dạng token: {dinh}"


def _email_la(text: str) -> list[str]:
    """Mọi chuỗi hình dạng email còn lại sau khi trừ các miễn trừ theo MẪU (viết thường)."""
    text = MAU_EMAIL_SSH.sub(" ", text)
    return [m.group(0).lower() for m in MAU_EMAIL.finditer(text)
            if not MAU_EMAIL_GIU_CHO.search(m.group(0))
            and not MAU_EMAIL_ASSET.search(m.group(0))]


def vi_pham_email(rel: str, text: str) -> list[str]:
    """Email lạ: cấm ở mọi file. Email của tác giả: phải đúng số lần đã ghi cho file đó
    (thừa lẫn thiếu đều đỏ — mục miễn trừ dư là cửa mở sẵn)."""
    tim = _email_la(text)
    n_tg = tim.count(EMAIL_TG)
    n_la = len(tim) - n_tg
    loi = []
    if n_la:
        loi.append(f"{rel}: {n_la} địa chỉ email không phải của tác giả")
    mong = EMAIL_MIEN_TRU.get(rel, 0)
    if n_tg != mong:
        loi.append(f"{rel}: email tác giả x{n_tg}, kỳ vọng x{mong}")
    return loi


def test_email_mien_tru_co_that():
    """Mỗi file được miễn phải có trong cây git — không thì số đếm không bao giờ được so."""
    co = {p.relative_to(ROOT).as_posix() for p, _ in FILES}
    assert set(EMAIL_MIEN_TRU) <= co, f"file miễn trừ email không còn: {set(EMAIL_MIEN_TRU) - co}"


@pytest.mark.parametrize("rel", sorted(EMAIL_MIEN_TRU))
def test_dot_bien_email_tac_gia(rel):
    """Đột biến: đổi email tác giả thành email lạ, hoặc thêm lần thứ hai, thì cổng phải ĐỎ."""
    text = dict((p.relative_to(ROOT).as_posix(), t) for p, t in FILES)[rel]
    assert vi_pham_email(rel, text) == [], "bản thật phải xanh"
    la = "stran" + "ger" + "@" + "gmail" + ".com"
    assert vi_pham_email(rel, text.replace(EMAIL_TG, la)), "đổi sang email lạ mà cổng vẫn xanh"
    assert vi_pham_email(rel, text + "\n" + EMAIL_TG), "thêm lần thứ hai mà cổng vẫn xanh"
    assert vi_pham_email(rel, text + "\n" + la), "thêm email lạ cạnh email thật mà cổng vẫn xanh"
    assert vi_pham_email("docs/khac.md", EMAIL_TG), "email tác giả ở file không được miễn phải đỏ"


def test_fixtures_trung_tinh():
    """`fixtures/` là mốc đối chứng — số liệu phải dùng được mà không lộ ai là ai."""
    name = re.compile("|".join(_TO_CHUC), re.I)
    dinh = [p.relative_to(ROOT).as_posix()
            for p, text in FILES
            if p.parts[len(ROOT.parts):][:1] == ("fixtures",) and name.search(text)]
    assert not dinh, f"fixtures/ phải trung tính, còn tên tổ chức ở: {dinh}"


def test_prompt_MAU_khong_khoa_vao_mot_nguoi():
    """Repo public. Prompt mở đầu bằng tên thật thì ai clone về cũng viết bằng danh tính
    của người khác — template hỏng, không phải secret rò rỉ.

    Danh tính phải là chỗ trống lấy từ `brand.md` của kênh, đúng hợp đồng mà `new_post.py`
    đã ghi. Tên ở đây dựng bằng mã ký tự để CHÍNH FILE TEST không chứa thứ nó đi săn —
    một cổng tự miễn trừ mình là cổng vô dụng.
    """
    import unicodedata
    campaign = [unicodedata.normalize("NFC", x) for x in
           ("Nguy" + chr(0x1EC5) + "n Quang " + chr(0x110) + chr(0x1EE9) + "c",
            _TO_CHUC[1] + " Class", "T" + "obi", "KP" + "IM")]
    folder = ROOT / ".agents" / "prompts"
    assert folder.is_dir(), "không thấy .agents/prompts — đường dẫn đổi?"

    dinh = []
    for f in sorted(folder.glob("*.txt")):
        t = unicodedata.normalize("NFC", f.read_text(encoding="utf-8"))
        for x in campaign:
            if x in t:
                dinh.append(f"{f.name} còn {x!r}")
    assert not dinh, ("prompt mẫu bị khoá vào một người/tổ chức:\n  " + "\n  ".join(dinh))


def test_prompt_MAU_co_du_cho_trong_va_co_dan_cach_dien():
    """Bỏ tên mà không để chỗ trống thì agent sẽ tự bịa một cái tên."""
    folder = ROOT / ".agents" / "prompts"
    for f in sorted(folder.glob("*.txt")):
        t = f.read_text(encoding="utf-8")
        if "{{AUTHOR}}" in t or "{{CHANNEL}}" in t:
            assert "ĐIỀN TRƯỚC KHI DÙNG" in t, \
                f"{f.name} có chỗ trống danh tính nhưng không dặn cách điền"
            assert "brand.md" in t, f"{f.name} không chỉ ra nguồn của danh tính"


def test_TEMPLATE_khong_mang_nhan_dien_that():
    """`templates/station/` là khuôn mọi kênh mọc ra từ đó — nó phải TRUNG TÍNH.

    Cạm bẫy đã suýt trả giá (07/09/2026): bốn script cấp kênh (`build-index.ps1`,
    `send_newsletter.py`, `build_yt_desc.py`, `subscribe.gs`) được chưng cất từ bản đang
    chạy thật, và mang theo nguyên tên miền, email, tên người và **id Meta Pixel** vào một
    repo MIT công khai. Hai hậu quả khác nhau, đều nặng:

    · Rò rỉ: email và id pixel là dữ liệu thật, push lên là công khai vĩnh viễn.
    · Khuôn hỏng: ai clone về cũng xuất bản dưới danh nghĩa người khác và gửi dữ liệu
      người đọc tới một tài khoản quảng cáo lạ — mà không hề biết.

    Cổng `test_prompt_MAU_khong_khoa_vao_mot_nguoi` ở trên chỉ soi `.agents/prompts/`,
    nên nó không bắt được. Cổng này soi cả cây khuôn.

    Chuỗi cấm dựng bằng mã ký tự để CHÍNH FILE TEST không chứa thứ nó đi săn.
    """
    import re
    import unicodedata

    tm = ROOT / "templates"
    assert tm.is_dir(), "không thấy templates/ — đường dẫn đổi?"

    # Tên miền, email, tên người, id pixel của kênh đầu tiên.
    campaign = [
        "ducng" + "uyen.vn", "ducng" + "uyen221", "ducng" + "uyen.ams",
        _s(68, 117, 99) + " Ngu" + "yen", "17170417" + "32866196",
        "C:" + chr(92) + "Users" + chr(92) + _s(68, 117, 99) + "Nguyen",
    ]
    campaign = [unicodedata.normalize("NFC", x) for x in campaign]
    # Tên kênh thật: bắt cả hai kênh của chủ repo mà không đụng chữ "news" chung.
    mau_kenh = re.compile(r"\b(AI|Data)\s+News\b")

    dinh = []
    for f in sorted(tm.rglob("*")):
        if not f.is_file() or f.suffix.lower() in {".xlsx", ".png", ".jpg", ".svg"}:
            continue
        try:
            t = unicodedata.normalize("NFC", f.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
        name = f.relative_to(ROOT).as_posix()
        for x in campaign:
            if x in t:
                dinh.append(f"{name} còn {x!r}")
        m = mau_kenh.search(t)
        if m:
            dinh.append(f"{name} còn tên kênh thật {m.group()!r}")

    assert not dinh, (
        "khuôn trong templates/ mang nhận diện thật — sửa thành khoá cấu hình "
        "hoặc chỗ trống:\n  " + "\n  ".join(dinh))


# ══════════════════════════════════════════════════════════════════════════════
# Cổng ĐẾM — quét cả cây, miễn trừ theo SỐ ĐẾM CHÍNH XÁC
#
# Vì sao thêm cổng thứ ba khi đã có hai cổng trên: hai cổng kia hoặc chặn cứng một
# chuỗi trên toàn cây (không chừa chỗ cho LICENSE, CODEOWNERS, trang giới thiệu repo),
# hoặc chỉ soi đúng một thư mục (`templates/`, `fixtures/`). Giữa hai thái cực đó là
# phần lớn repo — và `scripts/` nằm đúng ở giữa: nó là MÁY mà ai clone về cũng chạy,
# nên nó phải sạch tuyệt đối, trong khi `docs/index.html` là trang giới thiệu của chính
# chủ repo, mang tên miền thật là đúng chức năng.
#
# Miễn trừ theo SỐ, không theo file: thêm một chỗ vào file đã miễn cũng đỏ. Sửa nội
# dung làm số đổi thì phải sửa con số ở đây — người sửa buộc phải nhìn thấy mình đang
# đổi gì. Mục miễn trừ nào không còn khớp gì thì `test_mien_tru_khong_han` bắt gỡ.
# ══════════════════════════════════════════════════════════════════════════════
def _s(*ma: int) -> str:
    return "".join(map(chr, ma))


def _bo_dau(s: str) -> str:
    """Chuẩn hoá để so khớp không phân biệt dấu: NFD, bỏ dấu tổ hợp, Đ/đ -> D/d, chữ thường,
    gạch ngược -> gạch xuôi (đường dẫn kiểu Windows). Áp cho CẢ văn bản lẫn mẫu."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace(chr(0x110), "D").replace(chr(0x111), "d").lower()
    return s.replace(chr(92), "/")


_ENT_DEC = re.compile(r"&#([0-9]{1,7});")
_ENT_HEX = re.compile(r"&#[xX]([0-9a-fA-F]{1,6});")
_JSON_U = re.compile(r"\\u([0-9a-fA-F]{4})")


def _giai_ma(s: str) -> str:
    """Giải mã entity số (`&#NNN;`, `&#xHH;`) và escape JSON dạng gạch-ngược-u-bốn-chữ-số-hex: tên viết dưới dạng
    mã hoá vẫn là tên. Áp cho mọi file văn bản, không phân biệt .html/.json. Mã nằm ngoài
    Unicode hợp lệ hoặc là nửa cặp thay thế thì để nguyên."""
    def doi(m, co_so):
        n = int(m.group(1), co_so)
        return chr(n) if 0 < n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else m.group(0)
    s = _ENT_DEC.sub(lambda m: doi(m, 10), s)
    s = _ENT_HEX.sub(lambda m: doi(m, 16), s)
    return _JSON_U.sub(lambda m: doi(m, 16), s)


def _chuan(s: str) -> str:
    """Chuẩn hoá đầy đủ cho các khoá bỏ dấu: giải mã rồi bỏ dấu."""
    return _bo_dau(_giai_ma(s))


def _bd(s: str) -> str:
    """Literal đã bỏ dấu, thoát ký tự đặc biệt — dùng dựng mẫu."""
    return re.escape(_bo_dau(s))


# Mọi chuỗi cấm dựng bằng mã ký tự: file này bị chính nó quét ở hai cổng trên, và một
# cổng mang sẵn thứ nó đi tìm là cổng vô dụng.
_TEN_TG = _s(100, 117, 99) + _s(110, 103, 117, 121, 101, 110)          # tài khoản tác giả
_TEN_VN = (_s(0x4E, 0x67, 0x75, 0x79, 0x1EC5, 0x6E) + " " + _s(0x51, 0x75, 0x61, 0x6E, 0x67)
           + " " + _s(0x110, 0x1EE9, 0x63))                            # tên đầy đủ, có dấu
_PIXEL = _s(49, 55, 49, 55, 48, 52, 49, 55) + _s(51, 50, 56, 54, 54, 49, 57, 54)
_TO_CHUC = (_s(75, 80, 73, 77), _s(67, 79, 77, 80, 65), _s(84, 111, 98, 105))
# Đường thư mục instance mẫu — cũng dựng bằng mã ký tự, vì chính tên thư mục mang tên
# tổ chức và file này nằm trong vùng bị quét.
# Ba nhóm chuỗi cấm TOÀN CÂY (SPR-01, đợt dọn private): thứ đã bị gỡ khỏi repo và không
# được quay lại ở bất kỳ file nào, kể cả `content/**`. Đều dựng bằng mã ký tự.
#   · hashtag thương hiệu cũ (3 thẻ, gốc ở output_styles/multichannel-style.md bản c895903)
#   · tên thư mục bộ mẫu cũ: tiền tố `content/` + tên tổ chức
#   · tên Page Facebook cũ (tên hiển thị): tên thương hiệu + họ tên viết hoa dấu
_HASHTAG = (
    "#" + _s(67, 79, 77, 80, 65, 67, 108, 97, 115, 115),
    "#" + _s(72, 0x1ECD, 99, 67, 0xF9, 110, 103, 65, 73),
    "#" + _s(78, 103, 104, 0x1EC1, 67, 0x1EE7, 97, 0x110, 0x1EE9, 99),
)
_BO_MAU_CU = "content/" + _TO_CHUC[0]

_SEP = r"[\s_-]+"           # họ–tên cách nhau bằng khoảng trắng / gạch nối / gạch dưới
_HASHTAG_TRAN = tuple(h[1:] for h in _HASHTAG)      # tên thẻ, không có dấu thăng
_HO, _LOT, _TEN_DUC = (_s(78, 103, 117, 121, 0x1EC5, 110), _s(0x51, 0x75, 0x61, 0x6E, 0x67),
                         _s(0x110, 0x1EE9, 99))
_TEN_NGUOI_BD = ("(?:" + _bd(_HO) + _SEP + _bd(_LOT) + _SEP + _bd(_TEN_DUC) + "|"
                 + _bd(_s(68, 117, 99)) + _SEP + _bd(_HO) + ")")
# Không có lookahead sau tên: thẻ có hậu tố chữ/số (`<thẻ>room`, `<thẻ>2026`) vẫn là thẻ cũ.
_HASHTAG_BD = r"(?<![a-z0-9_])#?(?:" + "|".join(_bd(h) for h in _HASHTAG_TRAN) + r")"
_TEN_PAGE_BD = _bd(_TO_CHUC[2]) + r"[\s_-]*" + _bd(_HO)
# Tên gọi riêng đứng MỘT MÌNH (dạng có dấu hoặc không dấu, chữ đứng riêng, PHÂN BIỆT hoa/thường
# dù cổng truyền IGNORECASE — nhóm cờ cục bộ). Lookbehind loại tên đầy đủ (ghi công; khoá `ten-nguoi` lo).
# Không bỏ dấu: bỏ dấu + hạ chữ thường sẽ bắt nhầm từ thường mang đúng chữ ấy.
# Loại trừ chỉ khi đứng trước là ĐỦ họ + lót (có dấu hoặc không dấu, ba kiểu nối): «<lót> <tên>» hai
# từ không phải ghi công và không khoá nào khác bắt (TK12 RF2).
_HO_LOT = tuple(ho + sep + _LOT + sep for ho in (_HO, _bo_dau(_HO).capitalize()) for sep in (" ", "_", "-"))
_TEN_GOI = ("(?-i:" + "".join("(?<!" + re.escape(x) + ")" for x in _HO_LOT) + r"(?<![^\W\d_])(?:"
            + _s(0x110, 0x1EE9, 99) + "|" + _s(68, 117, 99) + r")(?![^\W\d_]))")

MAU_DANH_TINH = {
    "ten-mien":  re.escape(_TEN_TG + ".vn"),
    "handle":    re.escape(_TEN_TG + "221"),
    "ten-nguoi": _TEN_NGUOI_BD,
    "pixel":     _PIXEL,
    "to-chuc":   r"\b(?:" + "|".join(_TO_CHUC) + r")\b",
    "kenh-that": r"\b(?:AI|Data)\s+News\b",
    # Ba khoá dưới áp TOÀN CÂY (KHOA_CUNG) và KHÔNG có mục miễn trừ nào.
    "hashtag-thuong-hieu": _HASHTAG_BD,
    "bo-mau-cu": _bd(_BO_MAU_CU),
    "ten-page":  _TEN_PAGE_BD,
    "ten-goi":   _TEN_GOI,
}

# Bốn khoá so khớp trên văn bản ĐÃ BỎ DẤU (mẫu cũng đã bỏ dấu, xem _bd): bỏ dấu là cách
# lách rẻ nhất, và đường cũ viết gạch ngược cũng phải đỏ. Các khoá còn lại giữ so khớp cũ
# (to-chuc bắt từ thường nếu hạ về chữ không dấu, nên KHÔNG đưa vào đây).
KHOA_BO_DAU = ("ten-nguoi", "hashtag-thuong-hieu", "bo-mau-cu", "ten-page")


def _khop(khoa: str, van_ban: str):
    """Một lần so khớp đúng cách cổng đếm so: khoá bỏ dấu thì chuẩn hoá văn bản trước."""
    t = _chuan(van_ban) if khoa in KHOA_BO_DAU else unicodedata.normalize("NFC", van_ban)
    return re.search(MAU_DANH_TINH[khoa], t, flags=re.IGNORECASE)

# Khoá CỨNG: áp cho cả cây. Đây là danh tính của MỘT người / MỘT máy — tên miền, tài
# khoản, tên thật, id pixel quảng cáo. Ở đâu cũng là rò rỉ, trừ những chỗ ghi công đã
# liệt kê trong MIEN_TRU.
KHOA_CUNG = ("ten-mien", "handle", "ten-nguoi", "pixel",
             "hashtag-thuong-hieu", "bo-mau-cu", "ten-page", "ten-goi")

# Vùng MÁY: phần repo mà người clone đem đi chạy. Ở đây cấm thêm cả tên tổ chức và tên
# kênh thật — chúng không phải secret, nhưng để trong máy thì khuôn hỏng: người khác
# xuất bản dưới thương hiệu của chủ repo mà không hề biết.
VUNG_MAY = ("scripts/", "templates/", "fixtures/", "examples/", ".agents/", "tests/")

# (đường file, khoá) → số lần được phép. Mỗi dòng phải có LÝ DO.
MIEN_TRU = {
    # Ghi công tác giả + định tuyến review trên GitHub: đúng chức năng của hai file này.
    ("LICENSE", "ten-nguoi"): 1,
    (".github/CODEOWNERS", "handle"): 8,
    # Trang giới thiệu repo (GitHub Pages của chính chủ) + ảnh og của nó.
    ("docs/index.html", "ten-mien"): 8,
    ("docs/index.html", "handle"): 8,
    ("docs/index.html", "ten-nguoi"): 1,
    ("docs/og-image.svg", "ten-mien"): 1,
    # Ghi công tác giả + URL repo trong manifest phát hành: host (Claude, Codex) hiển thị
    # đúng hai trường này khi người dùng xem plugin — đúng chức năng, như LICENSE.
    (".claude-plugin/plugin.json", "ten-nguoi"): 1,
    (".claude-plugin/plugin.json", "handle"): 2,
    (".claude-plugin/marketplace.json", "ten-nguoi"): 1,
    (".codex-plugin/plugin.json", "ten-nguoi"): 1,
    (".codex-plugin/plugin.json", "handle"): 2,
    ("pyproject.toml", "handle"): 1,
    # URL repo công khai — nguồn DUY NHẤT mà hướng dẫn cài bảo agent tin (clone, kiểm
    # `git remote -v`, đọc INSTALL.md thô). Bỏ nó đi là bỏ luôn phép kiểm nguồn.
    ("INSTALL.md", "handle"): 8,
    ("README.md", "handle"): 4,         # +2: GitHub trong mục Tác giả
    # Bản chép ĐÚNG prompt của INSTALL.md (cổng test_install_docs giữ nguyên văn):
    # START-HERE = prompt VI (2 URL); trang /install/ = 2 prompt × 2 URL + link INSTALL,
    # START-HERE, troubleshooting trên GitHub.
    ("START-HERE.md", "handle"): 2,
    ("docs/install/index.html", "handle"): 7,
    # Dòng Copyright của repo trong NOTICE — cùng chức năng với LICENSE.
    ("NOTICE", "ten-nguoi"): 2,         # +1: dòng Author
    # Tên đầy đủ, website, GitHub của tác giả: chủ dự án chủ động công khai (18/10) ở khối
    # author/owner của manifest, NOTICE và mục Tác giả của README. Đếm chính xác từng file.
    ("NOTICE", "ten-mien"): 1,
    (".claude-plugin/plugin.json", "ten-mien"): 1,
    (".claude-plugin/marketplace.json", "ten-mien"): 1,
    (".codex-plugin/plugin.json", "ten-mien"): 1,
    ("README.md", "ten-mien"): 1,
    ("README.md", "ten-nguoi"): 1,
    # Hồ sơ giọng của chính chủ, và các file trỏ tới TÊN FILE đó. Đổi tên file hồ sơ
    # giọng là việc của đợt docs (P2-G5): nó kéo theo README + 5 chỗ tham chiếu.
    ("examples/example-studio/channel.yml", "to-chuc"): 1,
    (".agents/roles/content-strategist.md", "to-chuc"): 1,
    (".agents/roles/creative-producer.md", "to-chuc"): 1,
    (".agents/roles/qa-reviewer.md", "to-chuc"): 1,
    (".agents/skills/hook-writer/SKILL.md", "to-chuc"): 1,
}


def _ap_dung(rel: str, khoa: str) -> bool:
    return khoa in KHOA_CUNG or rel.startswith(VUNG_MAY)


def dem_danh_tinh() -> Counter:
    hits: Counter = Counter()
    for p, text in FILES:
        rel = p.relative_to(ROOT).as_posix()
        if not text:
            continue
        t = unicodedata.normalize("NFC", text)
        t_bd = _chuan(text)
        for khoa, mau in MAU_DANH_TINH.items():
            if not _ap_dung(rel, khoa):
                continue
            n = len(re.findall(mau, t_bd if khoa in KHOA_BO_DAU else t, flags=re.IGNORECASE))
            if n:
                hits[(rel, khoa)] = n
    return hits


def vi_pham_duong(duong: list[str]) -> list[str]:
    """Tên file/thư mục cũng là nội dung công khai: mỗi đường khớp một khoá toàn cây = vi phạm
    (không miễn trừ). Khoá bỏ dấu so trên đường đã chuẩn hoá (gạch ngược gấp thành gạch xuôi)."""
    loi = []
    for rel in duong:
        t, t_bd = unicodedata.normalize("NFC", rel), _chuan(rel)
        for khoa in KHOA_CUNG:
            if re.search(MAU_DANH_TINH[khoa], t_bd if khoa in KHOA_BO_DAU else t, flags=re.IGNORECASE):
                loi.append(f"{rel} [{khoa}] 1 > 0")
    return loi


def test_ten_duong_khong_mang_danh_tinh():
    duong = [p.relative_to(ROOT).as_posix() for p, _ in FILES]
    assert vi_pham_duong(duong) == [], "tên đường dẫn mang danh tính: " + "; ".join(vi_pham_duong(duong)[:8])


def test_dem_danh_tinh_khong_vuot_mien_tru():
    vuot = {k: n for k, n in dem_danh_tinh().items() if n > MIEN_TRU.get(k, 0)}
    assert vuot == {}, "rò danh tính / vượt số miễn trừ:\n  " + "\n  ".join(
        f"{f} [{k}] {n} > {MIEN_TRU.get((f, k), 0)}" for (f, k), n in sorted(vuot.items()))


def test_mien_tru_khong_han():
    """Mục miễn trừ không còn khớp gì thì phải gỡ — cửa mở sẵn là cửa sẽ bị dùng lại."""
    hits = dem_danh_tinh()
    han = [k for k in MIEN_TRU if k not in hits and (ROOT / k[0]).exists()]
    assert han == [], f"mục MIEN_TRU không còn khớp gì, gỡ đi: {han}"


def test_mien_tru_bang_so_that():
    """Số miễn trừ phải BẰNG số thật: mục dư (cửa mở sẵn) cũng đỏ như mục thiếu."""
    hits = dem_danh_tinh()
    lech = {k: (n, hits.get(k, 0)) for k, n in MIEN_TRU.items()
            if (ROOT / k[0]).exists() and hits.get(k, 0) != n}
    assert lech == {}, f"MIEN_TRU lệch số thật (cho phép, thật): {lech}"


def test_mau_bat_dung_muc_tieu():
    """Đột biến: mỗi mẫu phải bắt được chuỗi nó nhắm tới, và KHÔNG bắt chuỗi lành."""
    mau_thu = {
        "ten-mien":  "https://" + _TEN_TG + ".vn/atlas",
        "handle":    _TEN_TG + "221.github.io",
        "ten-nguoi": "tác giả " + _TEN_VN + " viết",
        "pixel":     "fbq('init', '" + _PIXEL + "')",
        "to-chuc":   "đăng ở " + _TO_CHUC[1] + " Class",
        "kenh-that": "kênh " + _s(65, 73) + " " + _s(78, 101, 119, 115) + " hằng tuần",
        "hashtag-thuong-hieu": "Chốt bài: " + _HASHTAG[1] + " " + _HASHTAG[2].lower(),
        "bo-mau-cu": "xem " + _BO_MAU_CU + "/02_campaigns/x.md",
        "ten-page": "Page " + _TO_CHUC[2] + " " + _s(78, 103, 117, 121, 0x1EC5, 110) + " đăng",
    }
    for khoa, mau in mau_thu.items():
        assert _khop(khoa, mau), khoa
    # Ranh giới: không bắt chữ lành đang có sẵn trong repo.
    assert not re.search(MAU_DANH_TINH["to-chuc"], "x.localeCompare(y)", flags=re.IGNORECASE)
    assert not _khop("ten-nguoi", _TEN_TG)
    assert not re.search(MAU_DANH_TINH["kenh-that"], "news/ai", flags=re.IGNORECASE)
    # Tên tổ chức thứ hai phải đứng một mình: nó là tiền tố của từ thường như Compatible
    # (`app.xml` của .xlsx) hay compare (docs) — các từ đó không được bị bắt.
    for lanh in ("Compatible", _TO_CHUC[1] + "RE", "compat-mode", "x." + _TO_CHUC[1] + "RE(y)"):
        assert not re.search(MAU_DANH_TINH["to-chuc"], lanh, flags=re.IGNORECASE), lanh
    assert re.search(MAU_DANH_TINH["to-chuc"], "lớp " + _TO_CHUC[1] + ".", flags=re.IGNORECASE)
    # Ba khoá toàn cây không được bắt chữ lành: tên tổ chức trần, hashtag chung, "content/".
    for khoa in ("hashtag-thuong-hieu", "bo-mau-cu", "ten-page"):
        for lanh in (_TO_CHUC[2], "#AI #hoc", "content/sample-course/", "Page " + _TO_CHUC[2] + "as"):
            assert not _khop(khoa, lanh), (khoa, lanh)


def test_dot_bien_bo_dau_va_khong_thang():
    """Đột biến lách: bỏ dấu, bỏ dấu thăng, viết slug, đảo thứ tự, gạch ngược — phải ĐỎ.
    Ca lành cùng hình dạng — phải XANH. Chuỗi cấm dựng từ mã ký tự như phần trên."""
    tren_ten = _s(78, 103, 117, 121, 0x1EC5, 110)
    do = {
        "hashtag-thuong-hieu": [
            "#" + _bo_dau(_HASHTAG_TRAN[1]),                 # thẻ #2 bỏ dấu
            "#" + _bo_dau(_HASHTAG_TRAN[2]).upper(),         # thẻ #3 bỏ dấu, chữ hoa
            "kênh " + _HASHTAG_TRAN[0] + " dạy",             # tên thương hiệu KHÔNG dấu thăng
            "#" + _HASHTAG_TRAN[0] + "room",                 # hậu tố chữ
            "#" + _HASHTAG_TRAN[1] + "2026",                 # hậu tố số
        ],
        "ten-page": [
            "Page " + _bo_dau(_TO_CHUC[2] + " " + tren_ten) + " đăng",     # bỏ dấu
            _TO_CHUC[2].lower() + "-" + _bo_dau(tren_ten),                 # slug gạch nối
            _TO_CHUC[2].lower() + _bo_dau(tren_ten),                       # slug liền
            _TO_CHUC[2].lower() + "_" + _bo_dau(tren_ten),                 # slug gạch dưới
        ],
        "ten-nguoi": [
            _bo_dau(_TEN_VN).title(),                                      # họ–tên–đệm, không dấu
            _bo_dau(_TEN_VN).replace(" ", "-"),                            # slug
            _s(68, 117, 99) + " " + _bo_dau(tren_ten).title(),             # tên–họ ASCII
        ],
        "bo-mau-cu": [
            "content" + _BS + _TO_CHUC[0] + _BS + "x",                      # đường cũ gạch ngược
            "Content/" + _TO_CHUC[0].lower() + "/x",                       # khác hoa/thường
        ],
    }
    for khoa, ca in do.items():
        for x in ca:
            assert _khop(khoa, x), (khoa, "bỏ lọt ca lách", len(x))
    # Ca lành: từ thường chứa tiền tố, hoặc cùng hình dạng nhưng không phải thứ cấm.
    lanh = ("Compatible", _TO_CHUC[1] + "RE", "Page " + _TO_CHUC[2] + "as", _TO_CHUC[2] + "as",
            "x" + _HASHTAG_TRAN[0], _TEN_TG, "content/sample-course/x.md")
    for khoa in KHOA_BO_DAU:
        for x in lanh:
            assert not _khop(khoa, x), (khoa, "bắt nhầm ca lành", len(x))


def test_dot_bien_ten_goi_rieng():
    """Khoá `ten-goi`: tên gọi riêng đứng một mình phải ĐỎ; từ thường và tên đầy đủ (ghi công) XANH."""
    ten, ten_a = _s(0x110, 0x1EE9, 99), _s(68, 117, 99)
    do = ('by="' + ten + '"', ten + " chốt 10/09", ten_a, "Máy " + ten, "(" + ten + " hỏi)",
          "Chủ " + ten_a + ".", _LOT + " " + ten, _LOT + "_" + ten, _LOT + "-" + ten_a)
    for x in do:
        assert _khop("ten-goi", x), ("bỏ lọt", len(x))
    xanh = ("đạo " + ten.lower(), "có " + ten.lower(), "Đạo " + ten.lower(), _TEN_VN,
            _HO + " " + _LOT + " " + ten, _HO + "_" + _LOT + "_" + ten, _HO + "-" + _LOT + "-" + ten,
            _bo_dau(_HO).capitalize() + " " + _LOT + " " + ten_a,
            ten_a + "Nguyen", "x" + ten_a.lower(), ten_a.lower(), ten.lower(), "#" + _HASHTAG_TRAN[0],
            "Chủ kênh", "Chủ kênh (Telegram)", "chủ repo")
    for x in xanh:
        assert not _khop("ten-goi", x), ("bắt nhầm", len(x))
    assert "ten-goi" not in KHOA_BO_DAU


def test_dot_bien_giai_ma_entity_va_json():
    """Tên dạng entity số hoặc escape JSON vẫn phải đỏ; chuỗi mã hoá vô hại vẫn xanh."""
    tren_ten = _s(78, 103, 117, 121, 0x1EC5, 110)
    ten_page = _TO_CHUC[2] + " " + tren_ten
    thuc_the = "".join("&#%d;" % ord(c) for c in ten_page)                  # entity thập phân
    thuc_hex = "".join("&#x%X;" % ord(c) for c in _HASHTAG_TRAN[1])          # entity thập lục
    json_the = "#" + "".join(_BS + "u%04x" % ord(c) if ord(c) > 127 else c for c in _HASHTAG_TRAN[2])
    assert _khop("ten-page", "<b>" + thuc_the + "</b>"), "tên Page dạng entity bị bỏ lọt"
    assert _khop("hashtag-thuong-hieu", "#" + thuc_hex), "hashtag dạng entity thập lục bị bỏ lọt"
    assert _khop("hashtag-thuong-hieu", '{"tag": "' + json_the + '"}'), "hashtag dạng \\u bị bỏ lọt"
    lanh = "&#169; 2026 &amp; &#x2014; &#0; &#xD800; " + _BS + "u00e9 " + _BS + "ud83d x"
    for khoa in KHOA_BO_DAU:
        assert not _khop(khoa, lanh), (khoa, "bắt nhầm chuỗi mã hoá vô hại")


def test_dot_bien_duong_dan():
    """Đường chứa tên thư mục bộ mẫu cũ / tên Page / thẻ cũ phải đỏ (danh sách đường trong bộ nhớ)."""
    do = [
        "content/" + _TO_CHUC[0] + "/02_campaigns/x.md",
        "content" + _BS + _TO_CHUC[0] + _BS + "x.md",
        "docs/" + _TO_CHUC[2] + "-" + _bo_dau(_s(78, 103, 117, 121, 0x1EC5, 110)) + ".md",
        "docs/" + _HASHTAG_TRAN[1] + ".md",
    ]
    for x in do:
        assert vi_pham_duong([x]), ("đường mang danh tính mà cổng xanh", len(x))
    sach = ["content/sample-course/CAMPAIGNS.md", "output_styles/multichannel-style.md", "tests/conftest.py"]
    assert vi_pham_duong(sach) == []


def test_khoa_toan_cay_khong_co_mien_tru():
    """Ba khoá cấm mới là cấm TUYỆT ĐỐI: thêm mục miễn trừ cho chúng là mở cửa lại."""
    moi = {"hashtag-thuong-hieu", "bo-mau-cu", "ten-page", "ten-goi"}
    assert moi <= set(KHOA_CUNG), "khoá cấm mới phải nằm trong KHOA_CUNG (áp toàn cây)"
    assert not [k for k in MIEN_TRU if k[1] in moi], "khoá cấm toàn cây không được có miễn trừ"


def test_email_tong_quat_va_placeholder():
    """RQ-136: mọi email lạ đỏ; placeholder `example` được miễn theo MẪU, không theo file."""
    la = "ten" + "." + "ho" + "@" + "congty" + "." + "vn"
    assert vi_pham_email("docs/x.md", la), "email tên miền riêng mà cổng vẫn xanh"
    assert vi_pham_email("docs/x.md", "a" + "@" + "truong" + ".edu" + ".vn")
    for ok in ("you" + "@" + "example" + ".com", "a" + "@" + "example" + ".org", "x" + "@" + "mail" + ".example",
               "x" + "@" + "example" + ".com", "u" + "@" + "host" + ".test", "u" + "@" + "a" + ".invalid"):
        assert vi_pham_email("docs/x.md", ok) == [], ok
    assert vi_pham_email("docs/x.md", "you" + "@" + "notexample" + ".com")
    assert vi_pham_email("docs/x.md", "a" + "@" + "example" + ".vn"), "example.vn không thuộc miền dành riêng"
    assert vi_pham_email("docs/x.md", "a" + "@" + "example" + ".co" + ".uk")


def test_email_mien_theo_mau_khong_theo_file():
    """Ba miễn trừ theo MẪU phải xanh; email thật che dưới dạng khác vẫn phải đỏ."""
    xanh = (
        "git" + "@" + "github" + ".com:" + "owner/repo.git",      # remote SSH
        "logo" + "@" + "2x" + ".png", "anh" + "@" + "3x" + ".webp",   # tên file asset
    )
    for ok in xanh:
        assert vi_pham_email("docs/x.md", ok) == [], ok
    thuc = "ten" + "." + "ho" + "@" + "congty" + ".vn"
    do = (
        "mailto:" + thuc,                                          # bọc mailto
        "<" + thuc + ">",                                          # bọc ngoặc nhọn
        "ten" + "." + "ho" + "@" + "congty" + ".png" + ".vn",      # đuôi ảnh chỉ ở GIỮA tên miền
        "12345+" + "ten" + "@" + "users" + ".noreply" + ".github" + ".com",   # noreply nhưng phần tên là người
        "git" + "@" + "congty" + ".vn",                            # giống SSH nhưng không có dấu hai chấm
        "avatar-" + thuc + ".png",                                 # địa chỉ thật bọc trong tên file ảnh
        "avatar-" + "ten" + "@" + "congty" + ".png",               # đuôi ảnh không có dạng <số>x
        "noreply" + "@" + "congty" + ".vn", "no-reply" + "@" + "congty" + ".vn",   # không còn miễn noreply
    )
    for x in do:
        assert vi_pham_email("docs/x.md", x), x


def test_vung_may_duoc_quet_that():
    """Cổng-của-cổng: không file nào thuộc vùng máy được quét thì cổng luôn xanh."""
    trong_vung = [p.relative_to(ROOT).as_posix() for p, t in FILES
                  if t and p.relative_to(ROOT).as_posix().startswith(VUNG_MAY)]
    assert len(trong_vung) > 50, f"chỉ thấy {len(trong_vung)} file trong vùng máy"
    for tien_to in VUNG_MAY:
        assert any(r.startswith(tien_to) for r in trong_vung), f"không quét gì dưới {tien_to}"
