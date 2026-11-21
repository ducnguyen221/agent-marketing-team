# Xem trước lịch đa kênh qua Postiz

`scripts/pipeline/postiz_preview.py` dựng candidate theo từng kênh từ một mảng JSON nhận qua stdin. Lệnh chỉ chạy trong bộ nhớ: không ghi lịch, không kết nối Postiz, không upload, không duyệt và không đăng. Kết quả `preview_only` không phải bằng chứng tài khoản được kết nối hay nội dung đã được phép phát.

Ví dụ PowerShell, dùng ID giả. Dòng đầu giúp Windows PowerShell 5.1 truyền UTF-8 khi nội dung có dấu:

```powershell
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
@'
[
  {
    "ref": "slot-01", "integration_id": "demo-threads", "provider": "threads",
    "content": "Noi dung mau", "uploaded_media": [], "mode": "schedule",
    "date_utc": "2026-11-20T03:00:00Z", "settings": {"__type": "threads"}
  },
  {
    "ref": "slot-02", "integration_id": "demo-discord", "provider": "discord",
    "content": "Noi dung mau", "uploaded_media": [], "mode": "schedule",
    "date_utc": "2026-11-20T04:00:00Z", "settings": {"__type": "discord", "channel": "123456"}
  }
]
'@ | python scripts/pipeline/postiz_preview.py
```

Mỗi `ref` phải duy nhất trong lô; `date_utc` là thời gian UTC. `ref` chỉ để ghép kết quả xem trước, không phải khóa chống đăng trùng. Hai nhãn khác nhau có thể mô tả cùng bài, cùng đích và cùng giờ: việc xác định lần đăng, đối soát, cổng duyệt và owner thuộc ledger/dispatcher, hiện chưa được nối với lệnh này. Đầu ra chứa chính nội dung đầu vào; xử lý theo mức riêng tư của bài. Input bị từ chối ghi lỗi tổng quát và mã thoát 2, không in lại nội dung.

Mỗi mục có `warnings`: luôn báo chưa được duyệt hoặc xác minh với nhà cung cấp; thêm cảnh báo khi X chưa được kiểm độ dài có trọng số hoặc TikTok dùng inbox `UPLOAD`. Phải đọc các cảnh báo cùng candidate, không coi mã thoát 0 là đủ điều kiện đăng.

Builder cũng nhận một số candidate Facebook, YouTube, LinkedIn, Instagram, TikTok và X với điều kiện trong `scripts/lib/postiz_payload.py`; hỗ trợ tại đây chỉ là kiểm hình dạng một phần, không bảo đảm schema, giới hạn hoặc quyền của provider. Với X, kiểm độ dài hiện chỉ đếm ký tự Python, chưa tính quy tắc trọng số Unicode và URL của X. TikTok `UPLOAD` đưa tới inbox và cần người hoàn tất; một trạng thái thành công của Postiz không tự chứng minh bài đã công bố. Media ID/path trong ví dụ thực phải đến từ bước upload đã xác thực đúng instance; lệnh này không xác minh media hoặc quyền.
