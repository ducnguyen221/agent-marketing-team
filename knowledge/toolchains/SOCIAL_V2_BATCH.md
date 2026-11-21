# Chuẩn bị gói xem trước social V2 theo lô

Dùng một manifest JSON khi cần chuẩn bị nhiều gói từ cùng thư mục bài V1. Mỗi mục gọi bộ [chuẩn bị gói đơn](SOCIAL_V2_PACKAGE.md) với đúng ID dòng nguồn, kênh và loại nội dung. Gói chỉ phục vụ duyệt cục bộ. Lệnh chạy offline, giữ nguyên nguồn V1 và các cổng phê duyệt.

## Manifest

Ví dụ lưu ở `.tmp/social-review/manifest.json`. Thư mục `.tmp/social-review/demo-v1` chứa `content.md`, `publish.json`, `thumbnail.png`, `telegram.txt` và các tệp ảnh, caption được liệt kê cho album mẫu.

```json
{
  "schema": "social-batch/1",
  "source_dir": "demo-v1",
  "items": [
    {
      "post_id": "fixture-post",
      "platform": "facebook",
      "kind": "image"
    },
    {
      "post_id": "fixture-post",
      "platform": "telegram",
      "kind": "image",
      "text_file": "telegram.txt"
    },
    {
      "post_id": "fixture-post",
      "platform": "telegram",
      "kind": "image",
      "media_files": ["assets/cover.jpg", "assets/detail.png"],
      "caption_files": ["captions/cover.txt", "-"]
    }
  ]
}
```

- Manifest UTF-8 tối đa 2 MiB, có từ một đến chín mục. Mỗi mục khai `post_id`, `platform`, `kind` và có thể thêm `text_file`, `comment_file`, `media_file`. Tra cặp kênh và loại nội dung theo hợp đồng gói đơn.
- Mục album Telegram dùng `media_files` gồm 2–10 ảnh có thứ tự, tối đa 10.000.000 byte mỗi ảnh. Dùng `caption_files` cùng thứ tự, với `-` cho vị trí không có caption. Mục có `media_files` bỏ `media_file`. Mục có `caption_files` bỏ `text_file`.
- Mục album Discord dùng `kind: "image"`, `media_files` gồm 2–10 ảnh có thứ tự và `text_file` chứa nội dung chung. `caption_files` chỉ áp dụng cho album Telegram. Giới hạn tệp theo tài liệu chuẩn bị gói. [Gói campaign V2](SOCIAL_V2_PACKAGE.md)
- Lệnh chặn các mục có cùng trường và giá trị trước khi tạo thư mục đầu ra. Với mục dùng một tệp media, trần dung lượng là 256 MiB. Giới hạn chín mục giữ tổng media đầu ra trong 2.304 MiB mỗi lô. Tệp JSON và HTML có thêm dung lượng từ các tài liệu nguồn đã giới hạn kích thước.
- `source_dir` tính từ thư mục chứa manifest. Các đường dẫn tệp tính từ thư mục bài V1. Dùng chữ và media cục bộ đã đối chiếu với bài và được phép chia sẻ với người duyệt. Đặt cả nguồn, manifest và thư mục cha của đầu ra trong cây cục bộ đáng tin cậy. Dùng đường dẫn trực tiếp, tránh `..`, liên kết và placeholder cloud.
- Chọn các dòng bằng `post_id`. Mỗi mục giữ anchor mà bộ chuẩn bị gói đơn xác thực. Với đầu ra tái sử dụng bài Facebook, cung cấp bản chữ đã biên tập cho đúng kênh. `comment_file` dành cho LinkedIn. Kiểm tra `ffprobe` trong PATH khi có mục MP4.

## Chạy và đọc kết quả

Chạy từ gốc repo. Thư mục cha phải tồn tại. Chọn thư mục đầu ra mới nằm ngoài nguồn V1.

```powershell
python -m scripts.social.prepare_batch --manifest .tmp/social-review/manifest.json --output-dir .tmp/social-review/batch-01
```

Kết quả JSON trên stdout có `status` và mảng `items` theo thứ tự trong manifest. Mỗi mục có số thứ tự `item`, `platform`, `kind` và `status`. Mục thành công có đường dẫn `review` tính từ thư mục đầu ra, ví dụ `01-facebook/review.html`. Mở trang này và đối chiếu `package.json`, anchor và media. Mục lỗi có mã `package_preparation_failed`. Đối chiếu cấu hình của đúng mục với yêu cầu về dòng V1, caption và media trong hướng dẫn gói đơn.

| Trạng thái lô | Mã thoát | Kết quả |
|---|---:|---|
| `prepared_for_review` | 0 | Tất cả mục đã tạo gói. |
| `partial` | 2 | Một số mục lỗi. Các gói thành công vẫn mở được. |
| `failed` có `items` | 2 | Mọi mục đều lỗi. |
| `failed` có `error` | 2 | Lỗi cấp lô. Kiểm tra manifest, thư mục nguồn và thư mục đầu ra mới. |

Lỗi `too_many_manifest_items` báo lô vượt chín mục. Mã `invalid_manifest_item_N` hoặc `duplicate_manifest_item_N` chỉ mục cần chỉnh theo thứ tự bắt đầu từ 1.

Để chạy lại, đưa các mục cần chuẩn bị lại vào manifest và chọn thư mục đích mới. Mỗi gói cần được duyệt theo quy trình hiện hành trước khi dùng cho bước gửi.
