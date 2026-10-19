#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dựng trạm nội dung — LÕI của bộ cài, dùng chung cho mọi hệ điều hành.

`install.ps1` (Windows) và `install.sh` (macOS/Linux) chỉ là **vỏ**: chúng dò Python rồi
gọi file này. Mọi quyết định — hỏi gì, tạo gì, ghi gì — nằm ở đây, một chỗ, để hai vỏ
không bao giờ trôi khỏi nhau.

## Hai chế độ cài (F17)

    embedded   trạm = <repo>/workspaces/, biến cấu hình ở <repo>/.env (cả hai bị git bỏ qua)
               — "mở một folder là thấy hết". MẶC ĐỊNH và là khuyến nghị cho người mới. Cùng
               tên thư mục `workspaces` với khi cài cùng OpcOS, khác ở chỗ nằm trong repo nên
               không cần thêm tầng `marketing`.
    separate   trạm ngoài repo — do bạn chọn đường (không có đường mặc định ở thư mục nhà),
               biến đặt ở cấp user, bí mật ở kho secret của máy — cho người nhiều máy,
               hoặc repo public của chính họ

Lựa chọn ghi vào `<repo>/studio.local.json`; `studio_paths.resolve_station()` đọc lại nó
cho MỌI script về sau.

## Ba luật của file này

1. **Bắt buộc hỏi, không tự chọn im lặng — nhưng chỉ hỏi ĐÚNG MỘT câu.** Chế độ quyết
   định nội dung của người dùng nằm trong hay ngoài repo, đó là quyết định của họ; và câu
   hỏi phải đi kèm phân tích, không phải một dấu nhắc trống. Bộ cài **không** hỏi về trạm
   giọng/video: viết bài và đăng là LÕI, chạy được ngay sau bước này. Lời đề nghị cài hai
   trạm kia đến sau, đúng lúc một bước chạm tới chúng (`scripts/lib/voice.py`).
2. **Không có người trả lời thì không đoán.** `stdin` không phải terminal (CI, tác vụ theo lịch,
   pipe) và máy KHÔNG đặt `OPCOS_WORKSPACES` ⇒ in bảng lựa chọn ra stderr rồi thoát **mã 2**,
   chưa ghi một byte nào. Đoán hộ ở đây là dựng trạm sai chỗ, và người dùng chỉ phát hiện ra sau
   khi đã viết vài bài. Máy ĐÃ đặt `OPCOS_WORKSPACES` thì chỗ đặt trạm không còn là điều phải đoán:
   `--yes` hoặc chạy không người ra thẳng `<biến>/marketing` (in một dòng nêu đường) — cùng hành
   vi với `voice-studio init` và `video-studio init`. Riêng khi `<repo>/workspaces` (hoặc
   `<repo>/workspace` cũ) ĐÃ mang dấu trạm mà chưa ghi lựa chọn: dữ liệu có sẵn thắng biến,
   `--yes`/không người GIỮ trạm đó (mã 0, một dòng nêu cách dời sau); có người thì hỏi giữ/chuyển.
3. **Máy đã có trạm ngoài thì tự `separate`, không hỏi, KHÔNG BAO GIỜ tạo `workspaces/`.**
   Hai nguồn sự thật cho cùng một repo là cách mất dữ liệu êm nhất. Đây cũng là thứ bảo vệ
   máy đang chạy lịch thật. Bộ cài MỚI không bao giờ tạo thư mục `workspace/` (số ít); nếu
   bản cài cũ để lại nó (mang `CHANNELS.md`) thì nó vẫn được nhận và được nhắc đổi tên.
   Ngoại lệ duy nhất: máy đặt `OPCOS_WORKSPACES` và `<repo>/workspaces` đã mang dữ liệu mà chưa
   chọn lần nào — dữ liệu có sẵn thắng (xem điểm 2), kể cả khi có thêm biến của trạm giọng/video.

Chạy lại an toàn: không đè file đã có, không xoá gì.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import studio_contract as SC  # noqa: E402
import studio_paths as SP  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):     # stream bị thay (test, pipe lạ) — không phải lỗi
    pass

PROG = "init_station"
# Biến nào đã đặt cũng có nghĩa "máy này đã theo mô hình trạm ngoài" — kể cả biến của hai
# trạm năng lực kia: người đã tách trạm giọng/video ra thì không đời nào muốn trạm nội dung
# chui vào trong repo.
BIEN_NHAN_DIEN = ("MARKETING_STUDIO_DATA", "VOICE_STATION", "VIDEO_STATION",
                  "OMNIVOICE_DIR", "VIDEO_ROOT")
# Giá trị này ĐI VÀO studio.local.json, nên nó phải là ASCII và là một đường dẫn thật:
# một chuỗi mô tả có dấu ("~/.secret/<tài-khoản>/") đọc bằng công cụ khác encoding sẽ hiện
# ra rác, và không ai dán nó vào đâu được. Trùng mặc định của `studio.py migrate`.
KHO_SECRET = "~/.secret/marketing-studio"

BANG_LUA_CHON = """\
Chọn chỗ đặt TRẠM nội dung (nơi chứa kênh, chiến dịch, bài, sản phẩm đã dựng).
Chỉ một câu hỏi này thôi — cài xong là viết bài và đăng được ngay: bản cài này
không bắt buộc trạm giọng/video. Hai trạm đó chỉ cần khi bạn muốn lồng tiếng hoặc dựng
video, và lúc đó chương trình sẽ nói đúng lệnh phải chạy.

  [1] embedded — gọn trong repo   ← KHUYẾN NGHỊ (bấm Enter)
      Là gì : trạm nằm ở <repo>/workspaces/, biến cấu hình ở <repo>/.env (git bỏ qua cả hai).
      Lợi   : mở một folder là thấy hết; không phải đặt biến môi trường; backup một phát.
      Hại   : xoá folder repo là mất luôn nội dung — đừng xoá repo để cài lại, dùng
              `studio.py update`; và nhớ `studio.py backup`.
      Chọn khi: một máy, muốn dùng được ngay, không rành kỹ thuật. Đang phân vân thì
              chọn cái này — đổi sang [2] sau được, đổi ngược lại cũng được.

  [2] separate — trạm ngoài repo (bạn chọn đường; sẽ hỏi ngay sau đây)
      Là gì : trạm ở thư mục riêng; bí mật ở kho secret của máy ({kho}).
      Lợi   : repo luôn sạch (an toàn khi repo là bản public của chính bạn); nhiều máy /
              nhiều repo dùng chung một trạm; cập nhật repo không đụng nội dung.
      Hại   : thêm một chỗ phải nhớ; nên đặt MARKETING_STUDIO_DATA cho lịch chạy thấy trạm.
      Chọn khi: rành kỹ thuật, nhiều máy, hoặc repo là bản public của chính bạn.

Sau này đổi ý được: `python scripts/pipeline/studio.py migrate --to separate`.
""".format(kho=KHO_SECRET)

# Chọn [2] mà chưa biết trạm ở đâu: hỏi đường. Có biến OPCOS_WORKSPACES thì đề xuất sẵn.
CAU_HOI_DUONG = """\
Trạm nội dung (separate) sẽ đặt ở đâu? Nhập đường dẫn thư mục (có thể chưa tồn tại).
Không có đường mặc định ở thư mục nhà — chỗ nào cũng phải do bạn quyết.
"""
# Có OPCOS_WORKSPACES: MỘT câu nhận ĐƯỜNG (Enter = trạm OpcOS), kể cả khi trạm đó đã mang dấu. Câu này
# không có lựa chọn [1]/[2]: trạm nằm trong repo thì chạy lại với `--mode embedded`.
CAU_HOI_DUONG_DE_XUAT = """\
Trạm nội dung (separate) sẽ đặt ở đâu?
Đề xuất (từ OPCOS_WORKSPACES={bien}): {duong}
Enter = nhận đề xuất; hoặc nhập đường dẫn khác. (Muốn trạm nằm trong repo: dừng lại và chạy
lại với --mode embedded. --yes hoặc không có người thì cũng ra đúng trạm đề xuất.)
"""

# Trạm nhúng CŨ mang dấu + máy đặt OPCOS_WORKSPACES + chưa ghi lựa chọn: dữ liệu có sẵn thắng biến.
# Hằng và tên hàm cùng tên với voice-studio/video-studio để ba bộ cài đọc như một.
OLD_STATION_PROMPT = ("Trạm cũ có dữ liệu ở {path}. Enter = giữ và dùng như cũ; "
                      "gõ `chuyen` = dời vào {oc}")
MOVE_WORDS = ("chuyen", "chuyển", "c")
# Ở câu nhận ĐƯỜNG, gõ trần một lựa chọn của bảng [1]/[2] không phải là đường: từ chối thay vì tạo
# thư mục `<cwd>/1`.
STATION_CONFIRM_REJECT = ("1", "2", "embedded", "separate")
CLI_MIGRATE = "python scripts/pipeline/studio.py migrate --to separate --station"


class Choice(NamedTuple):
    """Kết quả chọn chế độ. Vẫn unpack được 3 giá trị `mode, path, why = …` như cũ;
    `then_migrate` (đường trạm OpcOS) chỉ có khi người dùng chọn CHUYỂN trạm cũ — hàm chọn chế độ
    KHÔNG BAO GIỜ dời dữ liệu, `do_init` mới ghi `embedded` rồi xin `y/N` của `migrate`."""
    mode: str
    path: Path
    why: str
    then_migrate: "str | None" = None

    def __iter__(self):
        return iter(tuple.__getitem__(self, slice(0, 3)))


# ── nhận diện máy đã có trạm ngoài (F17.2) ────────────────────────────────────────────

def tram_ngoai_co_san():
    """-> (gốc trạm, lý do) nếu máy này đã theo mô hình trạm ngoài; không thì None.

    Gốc trạm là None khi chỉ biết "đã theo mô hình trạm ngoài" (biến của trạm giọng/video)
    mà không biết trạm nội dung ở đâu — người gọi phải hỏi đường, KHÔNG được đoán.

    KHÔNG ghi gì, không tạo gì — chỉ đọc biến. Không dò thư mục nào trong nhà người dùng.
    """
    ly_do = [b for b in BIEN_NHAN_DIEN if (os.environ.get(b) or "").strip()]
    if ly_do:
        bien_tram = (os.environ.get("MARKETING_STUDIO_DATA") or "").strip()
        goc = Path(bien_tram).expanduser().resolve() if bien_tram else None
        return goc, "biến " + ", ".join(ly_do) + " đã đặt"
    return None


def _co_nguoi_tra_loi() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:            # noqa: BLE001 — stdin bị thay (pytest, dịch vụ nền)
        return False


def _hoi_ban_phim(bang: str) -> str:
    SC.log(bang)
    sys.stderr.write("Chọn [1/2] (Enter = 1, embedded): ")
    sys.stderr.flush()
    return input()


def _hoi_duong_ban_phim(cau: str) -> str:
    SC.log(cau)
    sys.stderr.write("Đường trạm: ")
    sys.stderr.flush()
    return input()


def _hoi_giu_chuyen_ban_phim(cau: str) -> str:
    SC.log(cau)
    sys.stderr.write("Giữ / chuyển [Enter = giữ]: ")
    sys.stderr.flush()
    return input()


def _reject_bare_choice(go: str) -> None:
    """Gõ trần `1`/`2`/`embedded`/`separate` ở câu nhận ĐƯỜNG: mã 2, không tạo `<cwd>/1`."""
    if (go or "").strip().lower() in STATION_CONFIRM_REJECT:
        raise SC.ContractError(
            f"câu này nhận ĐƯỜNG dẫn, không phải lựa chọn {go!r}: Enter = trạm OpcOS. Muốn trạm "
            "nằm trong repo: chạy lại với --mode embedded. Chưa ghi gì.")


def _kiem_bien_opcos(dx) -> None:
    """`OPCOS_WORKSPACES` hoặc `<biến>/marketing` là một FILE: lỗi cấu hình (mã 2), nêu TÊN BIẾN,
    TRƯỚC mọi `mkdir` — không để `OSError` của hệ điều hành lọt ra thành mã 1."""
    if Path(os.path.expanduser(dx[0])).is_file():
        raise SC.ContractError(
            f"OPCOS_WORKSPACES={dx[0]} đang là một FILE, không phải thư mục. Đây là lỗi cấu hình: "
            "sửa hoặc gỡ biến rồi chạy lại (hoặc dùng --station <thư mục>). Chưa ghi gì.")
    p = Path(dx[1])
    while True:                      # `<biến>/marketing` hoặc một thư mục cha còn thiếu nằm dưới một FILE
        if p.is_file():
            raise SC.ContractError(
                f"{p} (từ OPCOS_WORKSPACES={dx[0]}) đang là một FILE, không phải thư mục. Đây là lỗi "
                "cấu hình: sửa hoặc gỡ biến rồi chạy lại (hoặc dùng --station <thư mục>). Chưa ghi gì.")
        if p.exists() or p.parent == p:
            break
        p = p.parent


def chon_duong_separate(ask=None, non_interactive=False, yes=False, hoi_xac_nhan=False):
    """-> (đường trạm tuyệt đối, lý do) cho `separate` khi chưa ai chỉ đường. KHÔNG có đường
    mặc định ở thư mục nhà.

    · Có `OPCOS_WORKSPACES`: đề xuất `<biến>/marketing` (kể cả khi thư mục chưa mang dấu trạm).
      Có người ⇒ hỏi xác nhận/đổi; không có người ⇒ dùng luôn (biến đã là lời khai tường minh)
      và in đúng một dòng. Trạm OpcOS ĐÃ mang dấu và `hoi_xac_nhan=False` (đường `--mode
      separate`) ⇒ dùng thẳng, 0 câu, 0 dòng; luồng tương tác không `--mode` truyền
      `hoi_xac_nhan=True` để vẫn hỏi đúng MỘT câu (không rẽ theo chuỗi lý do hiển thị).
      Hết dữ liệu (EOF) ở câu đường mà có biến = không có người: cùng đường `--yes`.
      Gõ trần `1`/`2`/`embedded`/`separate` ⇒ mã 2.
    · Không có biến: có người ⇒ hỏi đường (Enter rỗng = dừng); không có người ⇒ mã 2, nêu
      `--station`.
    `--yes` nghĩa là "đừng hỏi": nó cũng không được hỏi đường."""
    co_nguoi = not yes and (ask is not None or (not non_interactive and _co_nguoi_tra_loi()))
    dx = SP.goc_opcos()
    if dx:
        _kiem_bien_opcos(dx)
        if not hoi_xac_nhan and (Path(dx[1]) / SP.SO_KENH).is_file():
            return Path(dx[1]), f"trạm OpcOS: OPCOS_WORKSPACES đã đặt và {dx[1]} là một trạm"
    if dx and not co_nguoi:
        SC.log(f"[init] separate: dùng {dx[1]} (từ OPCOS_WORKSPACES={dx[0]}); "
               "muốn nơi khác: --station <đường>.")
        return Path(dx[1]), f"OPCOS_WORKSPACES đã đặt → {dx[1]}"
    if not co_nguoi:
        raise SC.ContractError(
            "chế độ separate cần biết đặt trạm ở đâu và không có người trả lời: không có đường "
            "mặc định. Chạy lại với --station <thư mục> (hoặc đặt OPCOS_WORKSPACES).")
    cau = (CAU_HOI_DUONG_DE_XUAT.format(bien=dx[0], duong=dx[1]) if dx else CAU_HOI_DUONG)
    try:
        tra = SP.duong_nguoi_go((ask or _hoi_duong_ban_phim)(cau))
    except EOFError:
        if dx:      # hết dữ liệu mà có biến = không có người: cùng đường `--yes`, mã 0 (mọi hệ điều hành)
            SC.log(f"[init] separate: dùng {dx[1]} (từ OPCOS_WORKSPACES={dx[0]}; không đọc được câu "
                   "trả lời); muốn nơi khác: --station <đường>.")
            return Path(dx[1]), f"OPCOS_WORKSPACES đã đặt → {dx[1]} (stdin hết dữ liệu)"
        raise SC.ContractError(
            "không đọc được đường trạm (stdin không có người). Chạy lại với --station <thư mục>.")
    if not tra:
        if not dx:
            raise SC.ContractError(
                "chưa nhập đường trạm nên dừng, chưa ghi gì. Chạy lại và nhập đường, hoặc dùng "
                "--station <thư mục>.")
        return Path(dx[1]), f"người dùng nhận đề xuất từ OPCOS_WORKSPACES → {dx[1]}"
    if dx:
        _reject_bare_choice(tra)
    return Path(os.path.abspath(os.path.expanduser(tra))), "người dùng nhập đường trạm"


def _tram_nhung_mang_dau(repo):
    """-> (trạm nhúng đang dùng, `both` mới chưa dấu?) khi trạm nhúng MANG DẤU trên **cả hai** tên
    (`workspaces` và `workspace` cũ, dấu = `CHANNELS.md`); không thì None.

    `both` mới chưa dấu = `workspace` cũ mang dấu còn `workspaces` mới là thư mục chưa dấu: bộ phân
    giải chọn thư mục MỚI rỗng, nên 'trạm đang dùng' ở đây rỗng còn dữ liệu nằm ở `workspace/`."""
    moi, cu = repo / SP.WORKSPACE, repo / SP.WORKSPACE_CU
    moi_dau, cu_dau = (moi / SP.SO_KENH).is_file(), (cu / SP.SO_KENH).is_file()
    if not (moi_dau or cu_dau):
        return None
    st, _nguon = SP.tram_nhung(repo)
    return st, (cu_dau and not moi_dau and moi.is_dir())


def _dong_giu(st, oc: str, hai_tram: bool) -> str:
    if hai_tram:
        return (f"[init] giữ trạm trong repo {st}; {oc} cũng đã là một trạm — có hai trạm mang dấu: "
                f"gộp bằng tay, hoặc chọn một bằng --station {oc}")
    return (f"[init] giữ trạm trong repo {st}; máy có OPCOS_WORKSPACES — dời sau bằng: "
            f"{CLI_MIGRATE} {oc}")


def _giu_hay_chuyen(repo, dx, yes, co_nguoi, ask):
    """Ca trạm cũ có dữ liệu: trạm nhúng đang mang dấu + `OPCOS_WORKSPACES` + chưa ghi lựa chọn ⇒ dữ liệu có sẵn
    THẮNG biến. -> Choice("embedded", …) hoặc None khi không thuộc ca này. KHÔNG dời gì."""
    cu = _tram_nhung_mang_dau(repo)
    if not cu:
        return None
    st, both_moi = cu
    oc = dx[1]
    hai_tram = (Path(oc) / SP.SO_KENH).is_file()
    ly = "trạm trong repo đã mang dấu: dữ liệu có sẵn thắng OPCOS_WORKSPACES"
    if both_moi:             # không hỏi, không gợi `migrate`: dời `workspaces/` rỗng là vô nghĩa
        return Choice("embedded", st.resolve(), ly)
    then = None
    if co_nguoi and not yes:
        cau = OLD_STATION_PROMPT.format(path=st, oc=oc)
        try:
            tra = ((ask or _hoi_giu_chuyen_ban_phim)(cau) or "").strip().lower()
        except EOFError:     # hết dữ liệu = không có người = giữ
            tra = ""
        if tra in MOVE_WORDS:
            then = oc
    if not then:
        SC.log(_dong_giu(st, oc, hai_tram))
    return Choice("embedded", st.resolve(), ly, then)


def chon_che_do(station=None, mode=None, yes=False, ask=None, non_interactive=False):
    """-> Choice(chế độ, gốc trạm, lý do[, then_migrate]); unpack được `mode, path, why = …`. Ném
    ContractError khi cần người chọn mà không hỏi được.

    Thứ tự ưu tiên (một dòng, cùng hình với voice/video):

        --station ─► biến trạm riêng ─► lựa chọn đã ghi ─► --mode ─► (có OPCOS_WORKSPACES?)
           trạm nhúng mang dấu, chưa ghi lựa chọn ─► GIỮ (hỏi giữ/chuyển khi có người; không hỏi khi
                                                      `--yes`/không người/EOF)
           ─► `--yes`/không người ─► trạm OpcOS (đã dấu: dùng thẳng; chưa: dựng + một dòng)
           ─► có người ─► MỘT câu nhận đường (Enter = trạm OpcOS)
        không có OPCOS_WORKSPACES: có người ⇒ bảng [1]/[2]; `--yes` ⇒ embedded; không người ⇒ mã 2.

    Ctrl+C ở mọi câu hỏi **lan ra** (không bắt ở đây): biên CLI `studio_contract.run` đổi nó thành
    mã 2 một dòng. `non_interactive` = người gọi TỰ KHAI "không có ai ngồi đây": thiếu
    `--yes`/`--mode`/`--station` mà KHÔNG có `OPCOS_WORKSPACES` thì vẫn là mã 2 (hai vỏ cài
    `install.ps1 -NonInteractive`, `install.sh --non-interactive` cùng đổ vào đây). `--yes` KHÔNG
    BAO GIỜ hỏi: máy đặt `OPCOS_WORKSPACES` thì ra `<biến>/marketing`, không thì embedded
    `<repo>/workspaces`. Muốn trạm trong repo khi máy có biến: `--mode embedded`. Không dò thư mục
    nào trong nhà người dùng."""
    repo = SP.repo_root()
    ask_duong = ask            # câu hỏi ĐƯỜNG dùng bàn phím riêng, không dùng chung câu hỏi chế độ
    co_nguoi = ask is not None or (not non_interactive and _co_nguoi_tra_loi())
    if station:
        return Choice("separate", Path(station).expanduser().resolve(), "--station")
    dx = SP.goc_opcos()
    # Ca trạm cũ có dữ liệu đứng TRƯỚC nhánh biến "anh em" (`tram_ngoai_co_san`) nhưng SAU `--station`, biến trạm riêng
    # (MARKETING_STUDIO_DATA), lựa chọn đã ghi và `--mode`; chỉ khi có OPCOS_WORKSPACES (nhánh không biến
    # — mã 2, theo thiết kế riêng của marketing — giữ nguyên).
    if (dx and repo and not mode and not (os.environ.get("MARKETING_STUDIO_DATA") or "").strip()
            and SP.mode(repo) is None):
        ca = _giu_hay_chuyen(repo, dx, yes, co_nguoi, ask_duong or _hoi_giu_chuyen_ban_phim)
        if ca:
            nhac = SP.goi_y_doi_bo_cuc(repo)
            if nhac:
                SC.log("[init] " + nhac)
            return ca
    ngoai = tram_ngoai_co_san()
    if ngoai:
        if mode == "embedded":
            raise SC.ContractError(
                f"máy này đã có trạm ngoài ({ngoai[1]}) — tạo thêm {SP.WORKSPACE}/ trong repo "
                "sẽ thành hai nguồn sự thật cho cùng một repo. Bỏ --mode để dùng trạm đó, "
                "hoặc gỡ biến / dời trạm cũ trước.")
        if ngoai[0] is None:                 # biết "trạm ngoài" nhưng không biết ở đâu: hỏi
            goc, ly = chon_duong_separate(ask_duong, non_interactive, yes, hoi_xac_nhan=True)
            return Choice("separate", goc, f"nhận diện trạm có sẵn — {ngoai[1]}; {ly}")
        return Choice("separate", ngoai[0], f"nhận diện trạm có sẵn — {ngoai[1]}")
    hoi_xac_nhan = False
    if mode:
        ly_do = "--mode"
    else:
        truoc = SP.mode(repo) if repo else None
        if truoc == "separate":
            if not str(SP.local_config(repo).get("station_path") or "").strip():
                raise SC.ContractError(
                    f"{SP.LOCAL_CONFIG} ghi 'separate' mà thiếu 'station_path' — bản ghi hỏng, không "
                    "đoán hộ trạm. Chạy lại với --station <đường> (hoặc xoá file đó để chọn lại). "
                    "Chưa ghi gì.")
            return Choice("separate", SP.resolve_station()[0], f"{SP.LOCAL_CONFIG} (lần chọn trước)")
        if truoc:
            mode, ly_do = truoc, f"{SP.LOCAL_CONFIG} (lần chọn trước)"
        elif dx and (yes or not co_nguoi):
            mode, ly_do = "separate", ("--yes + OPCOS_WORKSPACES" if yes
                                       else "không có người + OPCOS_WORKSPACES")
        elif yes:
            mode, ly_do = "embedded", "--yes (nhận khuyến nghị)"
        elif dx:
            # Có người ngồi + máy đặt OPCOS_WORKSPACES: không cần bảng chế độ — đúng MỘT câu nhận đường
            # (Enter = <biến>/marketing), kể cả khi trạm đó đã mang dấu; gõ đường khác = dùng đường đó.
            mode, ly_do, hoi_xac_nhan = "separate", "OPCOS_WORKSPACES đã đặt", True
        else:
            bang = BANG_LUA_CHON
            if ask is None:
                if non_interactive or not _co_nguoi_tra_loi():
                    SC.log(bang)
                    raise SC.ContractError(
                        "cần người dùng chọn chế độ cài. Agent: trình bảng ở trên cho người "
                        "dùng, rồi chạy lại với --mode embedded|separate (hoặc --yes: embedded khi "
                        "máy không đặt OPCOS_WORKSPACES).")
                ask = _hoi_ban_phim
            try:
                tra = (ask(bang) or "").strip().lower()
            except EOFError:
                # Windows: stdin là NUL vẫn báo isatty() = True — hết dữ liệu nghĩa là
                # không có ai ngồi đó.
                raise SC.ContractError(
                    "không đọc được lựa chọn (stdin không có người). Agent: trình bảng lựa "
                    "chọn cho người dùng, rồi chạy lại với --mode embedded|separate.")
            if tra in ("", "1", "embedded"):
                mode = "embedded"
            elif tra in ("2", "separate"):
                mode = "separate"
            else:
                raise SC.ContractError(
                    f"lựa chọn không hợp lệ: {tra!r} (1 = embedded, 2 = separate)")
            ly_do = "người dùng chọn"
    if mode == "embedded":
        if not repo:
            raise SC.ContractError(
                "chế độ embedded cần chạy từ bản clone repo; không xác định được gốc repo "
                "(đặt MARKETING_STUDIO_HOME trỏ vào đó).")
        st, _nguon = SP.tram_nhung(repo)
        nhac = SP.goi_y_doi_bo_cuc(repo)
        if nhac:
            SC.log("[init] " + nhac)
        return Choice("embedded", st.resolve(), ly_do)
    goc, ly = chon_duong_separate(ask_duong, non_interactive, yes, hoi_xac_nhan=hoi_xac_nhan)
    return Choice("separate", goc, f"{ly_do}; {ly}")


# ── dựng cây ──────────────────────────────────────────────────────────────────────────

def cay_mau(repo: Path | None) -> Path | None:
    # Thư mục MẪU giữ tên `templates/workspace` (nguồn chép vào trạm, không phải trạm; tên này
    # nằm trong bảng băm khoá của bộ kiểm skill nên không đổi theo tên trạm).
    t = (repo or Path(__file__).resolve().parents[2]) / "templates" / SP.WORKSPACE_CU
    return t if t.is_dir() else None


def _chep_cay(nguon: Path, dich: Path, da_tao: list):
    """Chép cây mẫu, KHÔNG đè file đã có — chạy lại bộ cài không được ăn mất nội dung."""
    for dp, _dn, fn in os.walk(nguon):
        rel = Path(dp).relative_to(nguon)
        for n in fn:
            f = dich / rel / n
            if f.exists():
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(dp) / n, f)
            da_tao.append(str((rel / n).as_posix()))


def _chep_env(repo: Path, da_tao: list):
    """`embedded`: dọn sẵn `<repo>/.env` từ `.env.example` và khoá quyền 600 trên POSIX."""
    mau, dich = repo / ".env.example", repo / ".env"
    if dich.exists() or not mau.is_file():
        return
    shutil.copyfile(mau, dich)
    da_tao.append(".env")
    if os.name != "nt":
        try:
            os.chmod(dich, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as e:               # hệ tệp không hỗ trợ (exFAT, chia sẻ mạng)
            SC.log(f"[init] không đặt được quyền 600 cho .env ({e}) — kiểm tay.")


def _thu_muc_hook(repo: Path) -> Path | None:
    """`.git/hooks` THẬT — hỏi git, không đoán.

    Trong một `git worktree` thì `.git` là một FILE trỏ sang chỗ khác, nên phép thử
    `(repo/".git"/"hooks").is_dir()` sai và rào lớp hai lặng lẽ vắng mặt đúng ở nơi người
    ta hay thử nghiệm (REVIEW-P2 Ghi nhận 3)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and (r.stdout or "").strip():
            p = Path((r.stdout or "").strip())
            p = p if p.is_absolute() else (repo / p)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except (OSError, subprocess.SubprocessError):
        pass
    hooks = repo / ".git" / "hooks"
    return hooks if hooks.is_dir() else None


def _cai_hook(repo: Path) -> str:
    hooks = _thu_muc_hook(repo)
    if hooks is None:
        return "không có .git/hooks"
    hook = hooks / "pre-commit"
    if hook.exists():
        return "giữ bản có sẵn"
    khuon = repo / "templates" / "hooks" / "pre-commit"
    if not khuon.is_file():
        return "không thấy khuôn"
    noi_dung = (khuon.read_text(encoding="utf-8")
                .replace("__PY__", sys.executable.replace("\\", "/"))
                .replace("__REPO__", str(repo).replace("\\", "/")))
    hook.write_text(noi_dung, encoding="utf-8", newline="\n")
    try:
        os.chmod(hook, 0o755)
    except OSError:
        pass
    return "đã cài"


def _tram_nang_luc_da_co(repo: Path | None) -> dict:
    """Cross-repo (F17.3): máy đã có trạm giọng/video thì ghi lại để `doctor` khỏi dò lại.

    Trạm tìm ra nhờ repo ANH EM cùng thư mục cha thì KHÔNG ghi: ghi đường tuyệt đối vào đây là
    đóng băng vị trí thư mục cha — dời cả thư mục chứa các repo đi nơi khác thì đường cũ
    (đứng trước nấc anh em) sẽ thắng và trỏ vào chỗ không còn."""
    ra = {}
    for khoa, ham, ten in (("voice_station", SP.voice_station, SP.REPO_GIONG),
                           ("video_station", SP.video_station, SP.REPO_VIDEO)):
        p = ham(repo)
        if p and p.is_dir() and p != SP.tram_anh_em(ten, repo):
            ra[khoa] = str(p)
    return ra


def _rel_nhung(repo: Path, st: Path) -> str:
    """Giá trị `station_path` ghi cho embedded: luôn là tên MỚI `workspaces`, kể cả khi đang nhận
    bố cục cũ `workspace` còn sót. Bộ phân giải không tin chuỗi này (đi qua `tram_nhung`), nên
    đổi tên thư mục theo gợi ý không làm mất trạm và config cũ ghi `workspace` cũng được đọc đúng."""
    return SP.WORKSPACE


def _ghi_local(repo: Path, mode: str, st: Path, da_tao: list):
    f = repo / SP.LOCAL_CONFIG
    cu = SP.local_config(repo)
    cu.update({
        "mode": mode,
        "station_path": _rel_nhung(repo, st) if mode == "embedded" else str(st),
        "secrets": ".env" if mode == "embedded" else KHO_SECRET,
    })
    cu.update(_tram_nang_luc_da_co(repo))
    f.write_text(json.dumps(cu, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="\n")
    da_tao.append(SP.LOCAL_CONFIG)


# Windows không mở được đường dài hơn ngần này nếu chưa bật long path — cùng con số với
# `station.py:GIOI_HAN_DUONG`, và cùng bài học: kiểm TRƯỚC khi ghi.
GIOI_HAN_DUONG = 259


def _kiem_cho_dung(st: Path, existing: bool) -> None:
    """Hai lỗi CẤU HÌNH phải nổ thành mã 2, TRƯỚC khi ghi byte nào (REVIEW-P2 N6, N7).

    Cả hai đều từng lọt ra thành `FileExistsError`/`FileNotFoundError`, và `SC.classify`
    xếp chúng vào mã 1 hoặc 3 — mã 1 thì bộ lập lịch/CI thử lại vô hạn một thứ không bao
    giờ tự khỏi, còn cây nửa vời thì người dùng không biết mình phải dọn gì."""
    if st.exists() and not st.is_dir():
        raise SC.ContractError(
            f"--station {st} đang là một FILE, không phải thư mục. Đây là lỗi cấu hình: "
            f"chạy lại nguyên trạng là vô ích. Trỏ sang một thư mục (hoặc chỗ trống).")
    if os.name == "nt" and len(str(st)) > GIOI_HAN_DUONG - 60 and not existing:
        # Trừ hao 60 ký tự cho đường con sâu nhất của cây mẫu: kiểm đúng gốc trạm thì
        # cây dựng xong vẫn có thể có file không mở được, và nó hỏng ngầm về sau.
        raise SC.ContractError(
            f"--station {st} dài {len(str(st))} ký tự — cây trạm dựng bên trong sẽ vượt "
            f"giới hạn 260 ký tự của Windows và đường ống hỏng ngầm về sau. Trỏ vào một "
            f"thư mục nông hơn (ví dụ ngay trong thư mục nhà). CHƯA ghi gì.")


def _mkdir_don_neu_hong(st: Path) -> None:
    """Tạo gốc trạm; nổ giữa chừng thì dọn đúng phần MÌNH vừa tạo rồi báo mã 2."""
    da_co = [p for p in [st, *st.parents] if p.exists()]
    moc = da_co[0] if da_co else None
    try:
        st.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        p = st
        while p != moc and p.is_dir() and not any(p.iterdir()):
            cha = p.parent
            try:
                p.rmdir()
            except OSError:
                break
            p = cha
        raise SC.ContractError(
            f"không tạo được thư mục trạm {st}: {e}. Lỗi cấu hình — sửa đường dẫn rồi chạy "
            f"lại; phần cây vừa tạo dở đã được dọn.") from e


def do_init(station=None, mode=None, yes=False, existing=False, dry_run=False, ask=None,
            non_interactive=False) -> dict:
    ch = chon_che_do(station=station, mode=mode, yes=yes, ask=ask, non_interactive=non_interactive)
    mode, st, ly_do = ch
    then = getattr(ch, "then_migrate", None)    # chỉ có khi người dùng chọn CHUYỂN trạm cũ
    repo = SP.repo_root()
    if mode == "separate" and not station and (st / SP.SO_KENH).is_file():
        existing = True        # trạm đã dựng sẵn (OpcOS, trạm cũ được nhận): không rải file mẫu vào đó
    kq = {"mode": mode, "station": str(st), "reason": ly_do, "repo": str(repo) if repo else None,
          "dry_run": bool(dry_run), "created": [], "hook": None, "then_migrate": then}
    if existing and not st.is_dir():
        raise SC.StationMissing(
            f"--existing nhưng không có thư mục trạm: {st}. Bỏ --existing để dựng mới. "
            + SC.GOI_Y_DU_LIEU_CU)
    if dry_run:
        return kq
    _kiem_cho_dung(st, existing)
    da_tao = kq["created"]
    if not existing:
        _mkdir_don_neu_hong(st)
        t = cay_mau(repo)
        if t:
            _chep_cay(t, st, da_tao)
        else:
            SC.log("[init] không thấy templates/workspace — trạm dựng rỗng.")
    if repo:
        if mode == "embedded" and not then:      # chuyển đi thì không dọn `.env` mẫu rồi bắt gộp nó
            _chep_env(repo, da_tao)
        _ghi_local(repo, mode, st, da_tao)
        if mode == "embedded":
            kq["hook"] = _cai_hook(repo)
    if then:
        _chuyen_sau_khi_ghi_embedded(kq, st, then, ask)
    return kq


def _chuyen_sau_khi_ghi_embedded(kq: dict, st: Path, oc: str, ask) -> None:
    """Người dùng chọn CHUYỂN trạm cũ vào trạm OpcOS. Trạm cũ đã được ghi `embedded` (nhờ đó
    `migrate` hợp lệ). Ở đây: kiểm đích (không rỗng ⇒ mã 2, TRƯỚC câu hỏi), xin `y/N` của `migrate`, rồi
    dời bằng chính đường `migrate`. `n`/Enter/EOF ⇒ GIỮ trạm cũ, mã 0, một dòng chỉ lệnh `migrate`.
    Không gọi `migrate_sang_separate` với đích có sẵn để HỎI trước: nhánh đó bỏ qua `y/N`."""
    d = str(Path(__file__).resolve().parent)
    if d not in sys.path:
        sys.path.insert(0, d)
    import studio as ST                    # noqa: E402 — chỉ cần khi dời; nạp muộn tránh vòng nhập
    dich = Path(oc).resolve()        # junction/liên kết ở đích phải lộ ra TRƯỚC câu hỏi, như `migrate` chạy riêng
    ST.kiem_dich_doi(st, dich)
    ST.kiem_env_doi(SP.repo_root(), Path(KHO_SECRET).expanduser())
    try:
        dong_y = ST.hoi_xac_nhan_doi(st, dich, ask or ST._hoi_ban_phim)
    except EOFError:
        dong_y = False
    if not dong_y:
        SC.log(_dong_giu(st, oc, False))
        return
    kqm = ST.migrate_sang_separate(station=str(dich), kho_secret=KHO_SECRET, non_interactive=True)
    kq["mode"], kq["station"] = "separate", kqm["station"]
    kq["reason"] = f"{kq['reason']}; đã dời sang {kqm['station']}"
    kq["env_moved_to"] = kqm.get("env_moved_to")


# ── in ra cho người đọc ───────────────────────────────────────────────────────────────

def _in(kq: dict):
    log = SC.log
    dau = "(xem trước — chưa ghi gì) " if kq["dry_run"] else ""
    log(f"[init] {dau}chế độ: {kq['mode']} · trạm: {kq['station']}")
    log(f"[init] lý do: {kq['reason']}")
    if kq["dry_run"]:
        if kq.get("then_migrate"):
            log(f"[init] sẽ dời {kq['station']} → {kq['then_migrate']} (xem trước: chưa dời byte nào, "
                "chưa ghi gì)")
        return
    for c in kq["created"]:
        log(f"  + {c}")
    if kq["hook"]:
        log(f"[init] hook pre-commit: {kq['hook']}")
    if kq["mode"] == "separate":
        log(f"\nNên đặt biến cho lịch chạy thấy trạm: MARKETING_STUDIO_DATA={kq['station']}")
        log(f"Bí mật để ở kho secret của máy ({KHO_SECRET}); biến chỉ giữ ĐƯỜNG DẪN.")
    else:
        log("\nĐiền biến của bạn vào <repo>/.env (chỉ đường dẫn + cấu hình, KHÔNG token).")
    log("\nBước tiếp theo:")
    log(f"  python scripts/pipeline/new_channel.py --id ten-kenh --label \"Tên kênh\" "
        f"--path \"{Path(kq['station']) / 'ten-kenh'}\"")
    log("  python scripts/pipeline/new_campaign.py --channel ten-kenh --id CMP-001 "
        "--name \"Tên chiến dịch\" --prefix ABC")
    log("  python scripts/pipeline/check_tree.py")
    log("\nĐọc trước khi dùng: docs/ONBOARDING.md (dựng từ đầu) · docs/WORKSPACE.md "
        "(thư mục nào chứa gì)")
    log("Đổi máy — MỘT máy chạy tại một thời điểm: docs/RUNBOOK-DOI-MAY.md")


def _goi_doctor(kq: dict):
    """`doctor` là bước cuối của bộ cài. Bản cài rút gọn không kèm nó thì bỏ qua, không nổ.

    Gọi **không** `--station`: cả việc của bước này là kiểm rằng cái vừa ghi ra
    (`studio.local.json`, `workspaces/`) khiến các script khác phân giải đúng trạm. Truyền
    sẵn đường trạm vào là tự trả lời hộ câu hỏi duy nhất đáng hỏi.
    """
    d = Path(__file__).resolve().parent / "doctor.py"
    if not d.is_file():
        return None
    SC.log("")
    r = subprocess.run([sys.executable, str(d)], text=True, encoding="utf-8", errors="replace")
    return r.returncode


def _parser_help() -> str:
    """Văn bản `--help` của lõi — để cổng parity so được cờ nào lõi thật sự hiểu."""
    return _parser().format_help()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG, description="Dựng trạm nội dung (hai chế độ: embedded / separate).")
    ap.add_argument("--station", help="trạm ngoài repo — chọn separate, không hỏi")
    ap.add_argument("--mode", choices=SP.MODES, help="chọn chế độ, không hỏi")
    ap.add_argument("--yes", action="store_true",
                    help="nhận khuyến nghị, không hỏi: máy đặt OPCOS_WORKSPACES thì ra "
                         "<biến>/marketing (trạm trong repo: thêm --mode embedded), không thì "
                         "ra <repo>/workspaces")
    ap.add_argument("--non-interactive", action="store_true",
                    help="không có ai trả lời: KHÔNG hỏi và KHÔNG đoán — thiếu "
                         "--yes/--mode/--station thì dừng với mã 2, trừ khi máy đặt "
                         "OPCOS_WORKSPACES (khi đó ra <biến>/marketing)")
    ap.add_argument("--existing", action="store_true",
                    help="nhận một trạm đang chạy: không rải file mẫu")
    ap.add_argument("--dry-run", action="store_true", help="chỉ báo sẽ làm gì, không ghi")
    ap.add_argument("--no-doctor", action="store_true", help="bỏ bước kiểm cuối")
    ap.add_argument("--json", action="store_true", help="in một dòng JSON kết quả ra stdout")
    return ap


def main(argv=None) -> int:
    args, ma = SC.parse(_parser(), argv)
    if args is None:
        return ma
    args.prog = PROG

    def chay(a):
        kq = do_init(station=a.station, mode=a.mode, yes=a.yes, existing=a.existing,
                     dry_run=a.dry_run, non_interactive=a.non_interactive)
        _in(kq)
        if not a.dry_run and not a.no_doctor:
            kq["doctor"] = _goi_doctor(kq)
        return kq
    return SC.run(chay, args, args.json)


if __name__ == "__main__":
    sys.exit(main())
