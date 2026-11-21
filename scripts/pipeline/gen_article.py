# -*- coding: utf-8 -*-
r"""gen_article.py — TÁCH content.md ra các file kênh, theo bố cục post_paths.LAYOUT.

`content.md` là nguồn DUY NHẤT của mọi text đem đăng. Script này tách nó thành các file
mà công cụ đăng thật sự ăn được (mọi tool đăng nhận ĐƯỜNG DẪN FILE, không nhận chuỗi):

  atlas/blog.md            <- ## post:blog_article
  facebook/post.txt        <- ## post:facebook_post      (thân bài, 0 URL)
  facebook/comment.txt     <- ### comment_1              (nơi DUY NHẤT chứa link)
  youtube/description.txt  <- ## post:youtube_desc
  facebook/reel.txt        <- ## post:reel   — CHỈ khi có cờ --with-reel

CLI:
  python gen_article.py --content-md F --meta meta.json --out-dir FOLDER [--with-reel]
→ in JSON các path + dòng cuối `OK <abs_path out-dir>`.

Tách theo NEO `## post:<tên>`, không theo số mục: số mục xê dịch theo từng bài, neo thì
không. Vẫn nhận dạng cũ (`## 3) Blog`) để bài cũ không vỡ.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "lib"))
import post_paths as PP  # noqa: E402

# Heading mục cấp section: "## 3) Blog", "### 4. FB post", "## 5 - YouTube desc"...
# Bắt: dấu #, số mục (1-9), dấu ngăn tùy ý, phần nhãn còn lại.
_SECTION_RE = re.compile(
    r"^\s{0,3}(#{2,3})\s*(\d{1,2})\s*[\).:\-–—]?\s*(.*)$"
)

# Nhãn (fallback khi heading không đánh số): map keyword -> khóa kênh.
# Thứ tự ưu tiên check: cụ thể trước (youtube/desc) rồi chung.
_LABEL_PATTERNS = [
    ("fb_group_share", re.compile(r"group.*share|share.*group", re.I)),
    ("youtube_desc", re.compile(r"youtube", re.I)),
    ("fb_desc",      re.compile(r"\bfb\b.*\b(desc|caption|mô\s*tả)\b|facebook.*\b(desc|caption|mô\s*tả)\b", re.I)),
    ("fb_post",      re.compile(r"\bfb\b.*post|facebook.*post|\bpost\b.*facebook|bài.*facebook", re.I)),
    ("blog",         re.compile(r"\bblog\b|bài\s*viết", re.I)),
]

# Số mục chuẩn theo mẫu content -> khóa kênh.
_NUM_TO_KEY = {3: "blog", 4: "fb_post", 5: "youtube_desc", 6: "fb_desc"}

# NEO kiểu repo: "## post:facebook_post". Đây là dạng content.md hiện dùng.
# Trước bản vá này script CHỈ hiểu heading có ĐÁNH SỐ ("## 3) Blog"), nên khi cho ăn
# đúng template của chính repo thì tách ra 0 khối. Tách theo NEO chứ không theo SỐ MỤC
# là điều kiện bắt buộc: số mục xê dịch theo từng bài, neo thì không.
_ANCHOR_RE = re.compile(r"^\s{0,3}(#{2,4})\s*post:\s*([a-z0-9_]+)\s*$", re.I)
_SUFFIXED_ANCHOR_RE = re.compile(r"^\s{0,3}#{2,4}\s*post:\s*[a-z0-9_]+#[0-9]+", re.I)
_POST_HEADING_PREFIX = re.compile(r"^\s{0,3}#{2,4}\s*post:", re.I)
_ANCHOR_TO_KEY = {
    "blog_article": "blog", "blog": "blog",
    "facebook_post": "fb_post",
    "youtube_desc": "youtube_desc", "youtube_video": "youtube_desc",
    "reel": "fb_desc", "fb_desc": "fb_desc", "fb_caption": "fb_desc",
    "group_share": "fb_group_share", "fb_group_share": "fb_group_share", "share_group": "fb_group_share",
}
# Comment đầu tiên của bài Facebook — nơi DUY NHẤT được chứa link (luật 04/09/2026).
# Nằm lồng bên trong khối facebook_post nên phải bắt riêng, nếu không nó bị nuốt vào
# thân post và biến thành đúng cái lỗi "link trong thân bài" mà cổng G09 đang chặn.
_COMMENT_RE = re.compile(r"^\s{0,3}(#{2,4})\s*comment_1\s*$", re.I)
# Prompt tạo ảnh Facebook — cũng lồng trong khối facebook_post, cũng phải bắt riêng: lọt
# vào thân post là cả trang prompt lên feed; lọt vào comment là prompt nằm dưới link.
_IMAGE_PROMPT_RE = re.compile(r"^\s{0,3}(#{2,4})\s*image_prompt\s*$", re.I)

# Marker phân mục của mẫu content (vd "<!-- BEGIN BLOG -->", "<!-- END FB_POST -->")
# — KHÔNG được lọt vào file kênh (sẽ vào narration/HTML).
_MARKER_RE = re.compile(r"^\s*<!--\s*(BEGIN|END)\b.*?-->\s*$", re.I)


def _strip_markers(text):
    return "\n".join(ln for ln in text.split("\n") if not _MARKER_RE.match(ln)).strip("\n")


# Khóa kênh -> tên file output.
# Tên file lấy từ post_paths.LAYOUT — một nguồn sự thật. Đường dẫn có thư mục con
# (vd "facebook/post.txt") nên write_outputs phải tạo thư mục cha.
_OUT_FILES = {
    "blog": PP.LAYOUT["blog"],
    "fb_post": PP.LAYOUT["fb_post"],
    "fb_comment": PP.LAYOUT["fb_comment"],
    "fb_image_prompt": PP.LAYOUT["fb_prompt"],
    "youtube_desc": PP.LAYOUT["yt_desc"],
    "fb_group_share": PP.LAYOUT.get("fb_group_share", "facebook/group_share.txt"),
}
# reel CHỈ sinh khi bài có short.mp4 — bài thường không dùng tới, sinh ra là rác và còn
# chứa link blog (trái luật "thân bài Facebook 0 URL").
_OUT_REEL = {"fb_desc": PP.LAYOUT["fb_reel"]}


def _read(path):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"Không thấy file: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _classify_heading(num, label):
    """Trả về khóa kênh ('blog'/'fb_post'/'youtube_desc'/'fb_desc') hoặc None."""
    # Ưu tiên nhãn cụ thể (để không nhầm '## 3 Core argument' của brief cũ).
    for key, pat in _LABEL_PATTERNS:
        if pat.search(label or ""):
            return key
    # Fallback: theo số mục chuẩn.
    return _NUM_TO_KEY.get(num)


def _bo_huong_dan_dau_khoi(text):
    """Bỏ khối trích dẫn HƯỚNG DẪN nằm ngay đầu một khối, trả `(nội_dung, phần_đã_bỏ)`.

    Mẫu `content.md` đặt hướng dẫn viết bài trong một khối `>` ngay dưới mỗi neo
    `## post:`. Đó là chỉ dẫn cho người viết, KHÔNG phải nội dung — để lọt là nó đăng
    thẳng lên blog và YouTube. Bài đầu tiên của xưởng thoát nạn chỉ vì người viết xoá tay;
    thứ gì phụ thuộc vào việc nhớ xoá tay thì sớm muộn cũng quên.

    Chỉ bỏ khối `>` đứng NGAY ĐẦU, trước mọi nội dung khác — trích dẫn giữa bài giữ nguyên.
    Phần bỏ được TRẢ VỀ để ghi vào báo cáo: bỏ im lặng thì một trích dẫn mở bài hợp lệ
    biến mất mà không ai biết.
    """
    row = text.split("\n")
    i = 0
    while i < len(row) and not row[i].strip():
        i += 1
    if i >= len(row) or not row[i].lstrip().startswith(">"):
        return text, ""
    start = i
    while i < len(row) and row[i].lstrip().startswith(">"):
        i += 1
    return "\n".join(row[i:]).strip("\n"), "\n".join(row[start:i]).strip("\n")


def _split_legacy_frontmatter(content):
    from delivery_anchors import _split_frontmatter
    """Preserve Unicode separators in V1 bodies while retaining V2 source guards."""
    if not isinstance(content, str) or not any(char in content for char in '\u2028\u2029'):
        return _split_frontmatter(content)
    if len(content) > 32 * 1024 * 1024:
        raise ValueError('invalid or oversized source content')
    try:
        if len(content.encode('utf-8')) > 32 * 1024 * 1024:
            raise ValueError('invalid or oversized source content')
    except UnicodeError:
        raise ValueError('invalid source encoding') from None
    if any(char in content for char in '\v\f\x1c\x1d\x1e\x85'):
        raise ValueError('unsupported content line separator')
    content = content.removeprefix('\ufeff')
    lines = re.split(r'(?<=\n)|(?<=\r)(?!\n)', content)
    if not lines or lines[0].rstrip('\r\n') != '---':
        return None, content
    size = 0
    for index, line in enumerate(lines[1:], 1):
        if any(char in line for char in '\u2028\u2029'):
            raise ValueError('Dấu phân cách Unicode không được dùng trong frontmatter.')
        if line.rstrip('\r\n') == '---':
            return ''.join(lines[1:index]), ''.join(lines[index + 1:])
        size += len(line.encode('utf-8'))
        if size > 65536:
            raise ValueError('source metadata is oversized')
    raise ValueError('source metadata is incomplete')


def split_content(md_text, da_bo=None):
    """Tách content.md -> dict {key: text} cho 4 kênh.

    Quét theo heading mục (## / ###). Mỗi heading mục mở 1 'section'; nội dung
    chạy tới heading mục CÙNG CẤP (hoặc cấp nông hơn) tiếp theo.

    `da_bo`: dict tuỳ chọn — nhận phần hướng dẫn đã bỏ của từng kênh, để người gọi báo lại.
    """
    lines = md_text.replace("\r\n", "\n").split("\n")
    sections = []  # list of (key, level, [lines])
    cur = None     # (key, level, list)
    for raw in lines:
        # Thứ tự nhận dạng: neo "## post:x" -> "### comment_1" -> heading đánh số.
        job_id = _ANCHOR_RE.match(raw)
        mc = _COMMENT_RE.match(raw) if job_id is None else None
        if job_id is None and mc is None:
            mi = _IMAGE_PROMPT_RE.match(raw)
            if mi is not None:
                mc, key_con = mi, "fb_image_prompt"
        else:
            key_con = "fb_comment"
        m = _SECTION_RE.match(raw) if (job_id is None and mc is None) else None
        if job_id is not None:
            level = len(job_id.group(1))
            key = _ANCHOR_TO_KEY.get(job_id.group(2).lower())
        elif mc is not None:
            # comment_1 và image_prompt lồng bên trong facebook_post: đóng khối đang mở
            # rồi mở khối riêng, bất kể cấp heading, nên ép level về cấp của khối đang mở.
            level = cur[1] if cur else len(mc.group(1))
            key = key_con
        if m:
            level = len(m.group(1))
            num = int(m.group(2))
            label = m.group(3).strip()
            key = _classify_heading(num, label)
        if job_id is not None or mc is not None or m:
            if key is not None:
                # Đóng section hiện tại nếu heading mới cùng cấp hoặc nông hơn.
                if cur and level <= cur[1]:
                    cur = None
                if cur is None:
                    cur = (key, level, [])
                    sections.append(cur)
                    continue  # bỏ dòng heading mục khỏi nội dung
                # heading mục lồng sâu hơn trong 1 section đang mở -> giữ nguyên dòng.
            else:
                # Heading đánh số nhưng KHÔNG phải mục kênh (vd '## 7) Ghi chú').
                # Nếu cùng cấp/nông hơn section đang mở -> đóng section.
                if cur and level <= cur[1]:
                    cur = None
                    continue
        if cur is not None:
            cur[2].append(raw)

    out = {}
    for key, _level, buf in sections:
        text = "\n".join(buf).strip("\n")
        text, bo = _bo_huong_dan_dau_khoi(text)
        # Giữ bản đầy đủ nhất nếu mục lặp (lấy bản dài hơn).
        if key not in out or len(text) > len(out[key]):
            if text.strip():
                out[key] = text
                if bo and da_bo is not None:
                    da_bo[key] = bo
    return out



def split_content_strict(md_text, da_bo=None):
    import studio_paths as SP
    """Tách content.md -> dict {key: text} cho 4 kênh.

    Quét theo heading mục (## / ###). Mỗi heading mục mở 1 'section'; nội dung
    chạy tới heading mục CÙNG CẤP (hoặc cấp nông hơn) tiếp theo.

    `da_bo`: dict tuỳ chọn — nhận phần hướng dẫn đã bỏ của từng kênh, để người gọi báo lại.
    """
    _, body = _split_legacy_frontmatter(md_text)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise ValueError("Thiếu bộ phân tích Markdown cần thiết để tách nội dung.") from None
    protected = bytearray(len(lines))
    code_protected = bytearray(len(lines))
    for token in MarkdownIt('commonmark', {'html': True}).parse(body):
        if token.type in {'fence', 'code_block', 'html_block'} and token.map is not None:
            start, end = token.map
            if token.type == 'fence':
                # The parser removes container prefixes and excludes a real
                # closing fence from content, while retaining an unclosed
                # fence's final line as content.
                content_lines = token.content.count('\n') + bool(token.content and not token.content.endswith('\n'))
                if end <= start + 1 or content_lines != end - start - 2:
                    raise ValueError("Khối code chưa đóng; không thể tách nội dung an toàn.")
            if token.type == 'html_block' and token.content.lstrip().startswith('<!--'):
                if '-->' not in token.content:
                    raise ValueError("Chú thích HTML chưa đóng; không thể tách nội dung an toàn.")
            if token.type == 'html_block' and any(
                    _POST_HEADING_PREFIX.match(line) or _SECTION_RE.match(line)
                    or _COMMENT_RE.match(line) or _IMAGE_PROMPT_RE.match(line)
                    for line in lines[start:end]):
                raise ValueError("Khối HTML chứa ranh giới kênh có thể bị che; cần kiểm tra nguồn.")
            protected[start:end] = b'\x01' * (end - start)
            if token.type in {'fence', 'code_block'}:
                code_protected[start:end] = b'\x01' * (end - start)
        elif (token.type in {'heading_open', 'paragraph_open'}
              and token.level != 0 and token.map is not None):
            start, end = token.map
            protected[start:end] = b'\x01' * (end - start)
    for i, line in enumerate(lines):
        if code_protected[i] or not any(char in line for char in '\u2028\u2029'):
            continue
        if (_POST_HEADING_PREFIX.match(line) or _SECTION_RE.match(line)
                or _COMMENT_RE.match(line) or _IMAGE_PROMPT_RE.match(line)):
            raise ValueError('Ranh giới nội dung Unicode không rõ; cần xuống dòng thật.')
        for part in re.split('[\u2028\u2029]', line):
            part = re.sub(r'^(?:[ \t]*>[ \t]?|[ \t]*[-+*][ \t]+|[ \t]*[0-9]{1,9}[.)][ \t]+)*', '', part)
            if (_POST_HEADING_PREFIX.match(part) or _SECTION_RE.match(part)
                    or _COMMENT_RE.match(part) or _IMAGE_PROMPT_RE.match(part)
                    or part.strip() == '---'):
                raise ValueError('Ranh giới nội dung Unicode không rõ; cần xuống dòng thật.')
    # The legacy output layout has one file per channel, so a second post
    # cannot be written without overwriting or mixing content. Refuse before
    # write_outputs runs. Code and HTML blocks are not section headings.
    if any(_SUFFIXED_ANCHOR_RE.match(line) for i, line in enumerate(lines) if not protected[i]):
        raise ValueError("Neo post có hậu tố chưa được hỗ trợ bởi bộ tách file kênh; "
                         "cần tách riêng theo từng post trước khi ghi.")
    seen_anchor_keys = set()
    for i, line in enumerate(lines):
        if protected[i]:
            continue
        match = _ANCHOR_RE.match(line)
        if match is None and _POST_HEADING_PREFIX.match(line):
            raise ValueError("Cú pháp neo post không được bộ tách file kênh hỗ trợ.")
        key = _ANCHOR_TO_KEY.get(match.group(2).lower()) if match else None
        if (match is not None and key is None
                and match.group(2).lower() != 'facebook'
                and f"post:{match.group(2).lower()}" not in SP.NEO.values()):
            raise ValueError("Neo post không có file kênh tương ứng trong bộ tách này.")
        if key is not None:
            if key in seen_anchor_keys:
                raise ValueError("Nhiều neo cùng trỏ đến một file kênh; "
                                 "cần tách riêng theo từng post trước khi ghi.")
            seen_anchor_keys.add(key)
    sections = []  # list of (key, level, [lines])
    cur = None     # (key, level, list)
    ignored_level = None  # A known post with no output in this legacy layout.
    facebook_level = None
    for i, raw in enumerate(lines):
        if protected[i]:
            if ignored_level is None and cur is not None:
                cur[2].append(raw)
            continue
        # Thứ tự nhận dạng: neo "## post:x" -> "### comment_1" -> heading đánh số.
        job_id = _ANCHOR_RE.match(raw)
        mc = _COMMENT_RE.match(raw) if job_id is None else None
        if job_id is None and mc is None:
            mi = _IMAGE_PROMPT_RE.match(raw)
            if mi is not None:
                mc, key_con = mi, "fb_image_prompt"
        else:
            key_con = "fb_comment"
        m = _SECTION_RE.match(raw) if (job_id is None and mc is None) else None
        heading = re.match(r'^ {0,3}(#{1,6})(?:[ \t]+|$)', raw)
        heading_level = len(heading.group(1)) if heading else None
        if job_id is not None:
            heading_level = len(job_id.group(1))
        if ignored_level is not None:
            if heading_level is None or heading_level > ignored_level:
                continue
            ignored_level = None
        if (facebook_level is not None and heading_level is not None
                and heading_level <= facebook_level and job_id is None and mc is None and m is None):
            raise ValueError("Heading ngang cấp làm ranh giới bài Facebook không rõ; "
                             "cần kiểm tra nguồn trước khi ghi.")
        if job_id is not None:
            level = len(job_id.group(1))
            key = _ANCHOR_TO_KEY.get(job_id.group(2).lower())
            if cur and level > cur[1]:
                raise ValueError("Neo post lồng trong mục khác không được hỗ trợ.")
            facebook_level = level if key == "fb_post" else None
            if key is None:
                cur = None
                ignored_level = level
                continue
        elif mc is not None:
            if (facebook_level is None or cur is None or cur[0] not in {"fb_post", "fb_comment", "fb_image_prompt"}
                    or len(mc.group(1)) <= facebook_level):
                raise ValueError("Mục Facebook phải thuộc khối bài Facebook.")
            # comment_1 và image_prompt lồng bên trong facebook_post: đóng khối đang mở
            # rồi mở khối riêng, bất kể cấp heading, nên ép level về cấp của khối đang mở.
            level = cur[1] if cur else len(mc.group(1))
            key = key_con
        if m:
            level = len(m.group(1))
            num = int(m.group(2))
            label = m.group(3).strip()
            key = _classify_heading(num, label)
            if key == "fb_post" and (cur is None or level <= cur[1]):
                facebook_level = level
            elif facebook_level is not None and level <= facebook_level:
                facebook_level = None
        if job_id is not None or mc is not None or m:
            if key is not None:
                # Đóng section hiện tại nếu heading mới cùng cấp hoặc nông hơn.
                if cur and level <= cur[1]:
                    cur = None
                if cur is None:
                    cur = (key, level, [])
                    sections.append(cur)
                    continue  # bỏ dòng heading mục khỏi nội dung
                # heading mục lồng sâu hơn trong 1 section đang mở -> giữ nguyên dòng.
            else:
                # Heading đánh số nhưng KHÔNG phải mục kênh (vd '## 7) Ghi chú').
                # Nếu cùng cấp/nông hơn section đang mở -> đóng section.
                if cur and level <= cur[1]:
                    cur = None
                    continue
        if cur is not None:
            cur[2].append(raw)

    out = {}
    if len({key for key, _level, _buf in sections}) != len(sections):
        raise ValueError("Nhiều mục cùng trỏ đến một file kênh; cần tách riêng trước khi ghi.")
    for key, _level, buf in sections:
        text = "\n".join(buf).strip("\n")
        text, bo = _bo_huong_dan_dau_khoi(text)
        if text.strip():
            out[key] = text
            if bo and da_bo is not None:
                da_bo[key] = bo
    return out


def write_outputs(parts, out_dir, with_reel=False):
    """Ghi 4 file (chỉ ghi file có nội dung). Trả về dict key->abs_path đã ghi."""
    os.makedirs(out_dir, exist_ok=True)
    written = {}
    bang = dict(_OUT_FILES)
    if with_reel:
        bang.update(_OUT_REEL)
    for key, fname in bang.items():
        text = _strip_markers(parts.get(key, ""))
        # Bỏ dấu ngắt "---" mà content.md dùng để tách khối. Nó là ký hiệu CỦA FILE NGUỒN,
        # không thuộc về bản giao cho kênh — để sót thì nó lên thẳng phần mô tả YouTube và
        # vào comment Facebook nguyên văn ba dấu gạch.
        text = re.sub(r"(?:\n\s*(?:-{3,}|\*{3,}|_{3,})\s*)+$", "", text).strip()
        if not text or not text.strip():
            # Chỉ dọn dẹp riêng file fb_group_share nếu section đó bị gỡ
            if key == "fb_group_share":
                old_p = os.path.join(out_dir, fname)
                if os.path.isfile(old_p):
                    try:
                        os.remove(old_p)
                    except OSError:
                        pass
            continue
        path = os.path.join(out_dir, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # blog.md: chuẩn hoá xuống dòng cuối; .txt: 1 newline cuối.
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.rstrip("\n") + "\n")
        written[key] = os.path.abspath(path)
    return written


def main(argv=None, *, strict=False):
    ap = argparse.ArgumentParser(
        description="Tách content.md (mẫu content) -> blog.md/fb_post.txt/youtube_desc.txt/fb_desc.txt")
    ap.add_argument("--content-md", required=True, help="instance content.md (mục 1-7)")
    ap.add_argument("--meta", required=True, help="meta.json của bài (giữ tương thích CLI)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--with-reel", action="store_true",
                    help="sinh thêm facebook/reel.txt — CHỈ dùng khi bài có short.mp4")
    args = ap.parse_args(argv)

    md_text = _read(args.content_md)
    # meta đọc để validate tồn tại + tương thích contract (chưa dùng trực tiếp khi tách).
    with open(args.meta, encoding="utf-8-sig") as f:
        json.load(f)

    da_bo = {}
    parts = (split_content_strict if strict else split_content)(md_text, da_bo)
    if "blog" not in parts:
        raise ValueError(
            "Không tách được khối blog từ content.md — cần neo '## post:blog_article' "
            "(hoặc heading đánh số '## 3) Blog' theo kiểu cũ).")
    written = write_outputs(parts, args.out_dir, args.with_reel)

    # fb_group_share là tuỳ chọn (sinh khi có neo ## post:group_share), không tính là thiếu
    missing = [k for k in _OUT_FILES if k not in written and k != "fb_group_share"]
    print(json.dumps({"out_dir": os.path.abspath(args.out_dir),
                      "written": written,
                      "missing_sections": missing,
                      # Hướng dẫn của mẫu đã được bỏ khỏi bản đăng. Liệt kê ra để nếu
                      # người viết mở bài BẰNG một trích dẫn thật thì thấy ngay là nó mất.
                      "guidance_stripped": {k: v.splitlines()[0][:70] + " …"
                                            for k, v in da_bo.items()}},
                     ensure_ascii=False, indent=2))
    print(f"OK {os.path.abspath(args.out_dir)}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(1)
