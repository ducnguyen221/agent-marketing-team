# -*- coding: utf-8 -*-
"""standalone_blog.py — chấm 24 cổng cho một bài blog NGOÀI chiến dịch, một lệnh, tự dọn.

Vì sao có: ca blog thật buộc người viết tự dựng thư mục bài đúng bố cục
(`atlas/blog.md`...) rồi đoán cờ `--home-domain` mới chấm được. Script này làm hộ phần đó.

Sơ đồ: kiểm đầu vào -> tạo thư mục tạm -> chép -> blog_gates.main -> in -> (finally) dọn/giữ.

CLI:
  python scripts/pipeline/standalone_blog.py --blog BAI.md [--research R.md]
         (--home-domain MIEN | --brand CHANNEL.yml) [--stage write] [--keep] [--json-only]

Thư mục tạm luôn nằm dưới `.tmp/standalone-blog/` của cwd (KHÔNG có cờ đổi gốc) và chỉ
thư mục do chính script vừa tạo mới bị xoá. Mã thoát = mã của blog_gates (0 / 1 / 2).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import blog_gates as G  # noqa: E402
import post_paths as PP  # noqa: E402

OUT_ROOT = Path(".tmp") / "standalone-blog"


def dung_thu_muc(blog: Path, research: Path | None) -> Path:
    """Tạo thư mục bài tạm mới (không bao giờ dùng lại thư mục có sẵn) và chép đầu vào vào."""
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    goc = f"{blog.stem}-{time.strftime('%H%M%S')}"
    n = 1
    while True:
        d = OUT_ROOT / (goc if n == 1 else f"{goc}-{n}")
        try:
            d.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            n += 1
    try:
        PP.make_dirs(d)
        shutil.copyfile(blog, PP.p(d, "blog"))
        if research is not None:
            shutil.copyfile(research, PP.p(d, "research"))
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)    # d do CHÍNH hàm này vừa mkdir: chép lỗi thì gỡ
        raise
    return d


def _don_goc_neu_script_tao(tao_goc: bool, tao_tmp: bool) -> None:
    """Xoá `.tmp/standalone-blog/` (và `.tmp/`) chỉ khi script tạo ra chúng và còn rỗng."""
    for thu_muc, do_tao in ((OUT_ROOT, tao_goc), (OUT_ROOT.parent, tao_tmp)):
        if do_tao:
            try:
                thu_muc.rmdir()
            except OSError:
                pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Chấm 24 cổng cho một bài blog độc lập, tự dọn.")
    ap.add_argument("--blog", required=True, type=Path, help="file blog markdown")
    ap.add_argument("--research", type=Path, default=None, help="research.md để G05 đối chiếu")
    ap.add_argument("--home-domain", default=None, help="tên miền nhà")
    ap.add_argument("--brand", default="", help="file khai khối `brand:` (json/yml)")
    ap.add_argument("--stage", choices=G.GIAI_DOAN, default="write")
    ap.add_argument("--keep", action="store_true", help="giữ thư mục tạm và in đường")
    ap.add_argument("--json-only", action="store_true", help="chỉ in JSON")
    a = ap.parse_args(argv)

    if not a.home_domain and not a.brand:
        sys.stderr.write("standalone_blog: cần --home-domain <tên miền nhà> hoặc --brand "
                         "<channel.yml>; không có channel.yml thì truyền giá trị giữ chỗ và "
                         "nói rõ trong báo cáo\n")
        return 2
    for f in (a.blog, a.research):
        if f is not None and not f.is_file():
            sys.stderr.write(f"standalone_blog: không thấy file bài: {f}\n")
            return 2

    tao_tmp, tao_goc = not OUT_ROOT.parent.exists(), not OUT_ROOT.exists()
    d, buf = None, io.StringIO()
    try:
        d = dung_thu_muc(a.blog, a.research)
        args = [str(d), "--stage", a.stage]
        if a.home_domain:
            args += ["--home-domain", a.home_domain]
        if a.brand:
            args += ["--brand", a.brand]
        if a.json_only:
            args.append("--json-only")
        # Thư mục tạm sắp bị xoá thì bảng không được chỉ người dùng tới gates.json: gom bảng, sửa dòng cuối.
        with contextlib.redirect_stdout(buf if not (a.keep or a.json_only) else sys.stdout):
            rc = G.main(args)
    finally:
        sys.stdout.write(buf.getvalue().replace(
            "\n  -> gates.json\n",
            "\n  (thư mục tạm đã xoá; thêm --keep để giữ gates.json)\n"))
        if d is not None and a.keep:
            out = sys.stderr if a.json_only else sys.stdout
            out.write(f"GIỮ {d.resolve()}\n")
        elif d is not None and d.resolve().is_relative_to(OUT_ROOT.resolve()) \
                and d.resolve() != OUT_ROOT.resolve():
            shutil.rmtree(d)
        if not a.keep or d is None:
            _don_goc_neu_script_tao(tao_goc, tao_tmp)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
