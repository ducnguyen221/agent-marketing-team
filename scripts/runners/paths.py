# -*- coding: utf-8 -*-
"""paths.py — nguồn sự thật DUY NHẤT cho thư mục hệ thống mà các runner Python cần.

    from paths import auto_task_xlsx
    xlsx = auto_task_xlsx()      # sổ Auto Task — ĐỪNG tự ghép đường dẫn

## Trạm (`station()`)

Thứ tự, không ngoại lệ (cùng luật với `brand-paths.ps1` và `scripts/lib/studio_paths.py`):

    MARKETING_STUDIO_DATA
    → `studio_paths.resolve_station()` của repo (`studio.local.json` → `<repo>/workspaces`),
      chỉ nhận khi nơi đó CÓ `CHANNELS.md`
    → DỪNG bằng `StationMissing`, nêu tên biến. KHÔNG dò thư mục nhà.

Hàm này KHÔNG BAO GIỜ tạo thư mục trạm: một lượt chạy tay không đặt biến từng lặng lẽ tạo
một trạm rỗng trong thư mục nhà của máy mới, và từ đó hai máy ghi sổ vào hai chỗ.

## Desktop (`desktop()`)

Chỉ còn dùng để tìm sổ Auto Task CŨ trên Desktop (đường lùi của đợt chuyển sổ vào trạm).
Windows: đọc registry `User Shell Folders` — đúng nguồn Explorer dùng, nên bám theo mọi lần
Desktop bị đồng bộ đám mây chuyển hướng. KHÔNG dựng đường Desktop từ biến của dịch vụ đồng bộ.
"""
import os
import sys

_SHELL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")


def desktop(fallback=None):
    """Thư mục Desktop THẬT (theo Explorer), đã expand biến môi trường.

    fallback: dùng khi không đọc được registry (máy khác / không phải Windows).
    Mặc định fallback = <thư mục nhà>/Desktop.
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SHELL_KEY) as k:
            d = os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
        if os.path.isdir(d):
            return d
    except (OSError, ImportError, ValueError):
        pass
    if fallback and os.path.isdir(fallback):
        return fallback
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _tram_repo():
    """Trạm theo `studio_paths` của repo — None khi không có repo hoặc nơi đó chưa là trạm."""
    if not os.path.isfile(os.path.join(_LIB, "studio_paths.py")):
        return None
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)
    try:
        import studio_paths as SP
        goc, _ = SP.resolve_station()
    except Exception:  # noqa: BLE001 — cấu hình hỏng thì rơi xuống nấc sau, nấc cuối nêu tên biến
        return None
    return str(goc) if (goc / "CHANNELS.md").is_file() else None


def station():
    """Trạm nội dung marketing — chứa các kênh và sổ Auto Task. Xem docstring module."""
    d = (os.environ.get("MARKETING_STUDIO_DATA") or "").strip()
    if d:
        return os.path.abspath(os.path.expanduser(d))
    t = _tram_repo()
    if t:
        return t
    msg = ("không xác định được trạm: đặt MARKETING_STUDIO_DATA hoặc chạy `scripts/pipeline/init_station.py` "
           "(chế độ embedded: <repo>/workspaces có CHANNELS.md). "
           "Có dữ liệu cũ ở nơi khác? Dùng --station <đường>.")      # = studio_contract.GOI_Y_DU_LIEU_CU
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)
    try:
        import studio_contract as SC
    except ImportError:             # runner chép đi nơi không có lib/: vẫn dừng, nêu tên biến
        raise SystemExit("paths.station: " + msg)
    raise SC.StationMissing(msg)


def station_hoac_thoat():
    """Như `station()` nhưng cho runner chạy TRỰC TIẾP: thiếu trạm ⇒ thoát gọn bằng thông điệp
    nêu tên biến (SystemExit), không phun traceback của `StationMissing`."""
    try:
        return station()
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "StationMissing":
            raise SystemExit("paths.station: " + str(e)) from None
        raise


def auto_task_xlsx():
    """Đường dẫn sổ `Auto Task.xlsx` — nguồn sự thật DUY NHẤT, đừng tự ghép.

    Sổ nằm trong trạm (cục bộ, không đồng bộ đám mây). ĐƯỜNG LÙI có chủ đích: nếu bản trong
    trạm chưa có mà Desktop còn bản cũ thì DÙNG BẢN CŨ — không có nó thì một lượt chạy giữa
    chừng đợt chuyển sẽ tự tạo sổ trắng ở chỗ mới và tách đôi lịch sử.
    """
    moi = os.path.join(station(), "Auto Task.xlsx")
    if os.path.isfile(moi):
        return moi
    cu = os.path.join(desktop(), "Auto Task.xlsx")
    if os.path.isfile(cu):
        return cu
    return moi          # chưa có sổ nào -> tạo ở chỗ MỚI


if __name__ == "__main__":
    print("desktop :", desktop())
    print("station :", station())
    print("xlsx    :", auto_task_xlsx())
