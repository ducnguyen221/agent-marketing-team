# -*- coding: utf-8 -*-
"""Tên người duyệt ghi vào hồ sơ duyệt/đăng (`approved_by`, `by`).

Thứ tự phân giải (biến đứng trước file, giống cách phân giải trạm ở `studio_paths.py`):

    MARKETING_APPROVER → `studio.local.json["approver"]` → mặc định «chủ kênh»

Không đặt gì thì hồ sơ ghi vai («chủ kênh»), không ghi tên một người cụ thể: bản clone của
người khác không được mang tên chủ repo.
"""
from __future__ import annotations

import os

import studio_paths as SP


def ten_nguoi_duyet(mac_dinh: str = "chủ kênh") -> str:
    v = (os.environ.get("MARKETING_APPROVER") or "").strip()
    if v:
        return v
    try:
        v = SP.local_config().get("approver")
    except SP.StudioPathsError:
        v = None   # file cấu hình hỏng: các đường khác đã báo; tên người duyệt không đáng làm dừng việc
    if isinstance(v, str) and v.strip():
        return v.strip()
    return mac_dinh
