# Chuẩn bị nhiều gói xem trước social V2 từ tệp độc lập

Dùng khi đã có caption và media cục bộ cho nhiều kênh. Mỗi mục trong manifest tạo một gói theo [quy trình chuẩn bị gói độc lập](SOCIAL_V2_STANDALONE.md). Nội dung thuộc chiến dịch đi theo [quy trình chiến dịch](SOCIAL_V2_PACKAGE.md).

## Manifest

Ví dụ lưu manifest dưới tên `social-review.json`, cùng cấp với thư mục `drafts`.

```json
{
  "schema": "social-standalone-batch/1",
  "source_dir": "drafts",
  "items": [
    {
      "platform": "facebook",
      "kind": "image",
      "text_file": "facebook.txt",
      "media_file": "cover.png",
      "comment_file": "facebook-comment.txt"
    },
    {
      "platform": "linkedin",
      "kind": "video",
      "text_file": "linkedin.txt",
      "media_file": "linkedin.mp4"
    },
    {
      "platform": "telegram",
      "kind": "image",
      "media_files": ["cover.png", "detail.jpg"]
    }
  ]
}
```

- Manifest UTF-8 tối đa 2 MiB, có từ một đến chín mục. Lệnh kiểm tra cấu trúc manifest, trường bắt buộc và mục trùng trước khi tạo đầu ra.
- `platform` và `kind` là bắt buộc. Bỏ `text_file` chỉ với ảnh, video hoặc PDF của Telegram, video YouTube không có mô tả, và video TikTok Inbox. `media_file` là tệp đính kèm cho `image`, `video` hoặc `document`. Với album Telegram, dùng `media_files` gồm 2–10 ảnh theo thứ tự và bỏ `media_file`. Bài `text` bỏ trường media và cần `text_file`. MP4 cần `ffprobe` trong PATH.
- `comment_file` dành cho Facebook và LinkedIn. Có thể khai thêm `account_id` và `destination_id` trên mỗi mục để người duyệt đối chiếu tài khoản và đích dự kiến.
- `source_dir` là đường dẫn tương đối tính từ nơi đặt manifest. Đường dẫn caption, media và bình luận tính từ `source_dir` và dùng dấu `/` giữa các cấp. Dùng nguồn cục bộ đã có đầy đủ trên đĩa và được phép chia sẻ với người duyệt. Từng gói giữ giới hạn 2 MiB cho mỗi tệp chữ và 256 MiB cho media.

## Chạy và đọc kết quả

Chạy từ gốc repo. Chọn thư mục đầu ra mới nằm ngoài `source_dir`, có thư mục cha đã tồn tại. Ví dụ với thư mục `out` đã có:

```powershell
python -m scripts.social.prepare_standalone_batch --manifest .\social-review.json --output-dir .\out\social-batch-01
```

Khi nhận được đối số hợp lệ, lệnh in kết quả JSON. Với đối số sai, lệnh thoát mã 2 và in thông báo chung ra stderr. Mảng `items` giữ thứ tự manifest, có số thứ tự bắt đầu từ 1, kênh, loại nội dung và trạng thái. Mục thành công có trường `review` với đường dẫn tương đối như `01-facebook/review.html`. Mở trang này để kiểm tra caption, media, bình luận và định danh dự kiến.

| Trạng thái lô | Mã thoát | Ý nghĩa |
|---|---:|---|
| `prepared_for_review` | 0 | Tất cả mục đã tạo gói. |
| `partial` | 2 | Một số mục lỗi. Các gói đã tạo vẫn mở được. |
| `failed` có `items` | 2 | Mọi mục đều lỗi. |
| `failed` có `error` | 2 | Lỗi cấp lô. Kiểm tra manifest, nguồn và thư mục đầu ra. |

Mã `invalid_manifest_item_N` và `duplicate_manifest_item_N` chỉ số thứ tự mục cần chỉnh. Mã `too_many_manifest_items` báo lô vượt chín mục. Với mục có `package_preparation_failed`, kiểm tra đường dẫn tệp, định dạng media, khả năng của kênh và định danh trong mục đó. Để chạy lại, khai các mục cần làm lại trong manifest và dùng thư mục đầu ra mới.

Kết quả là gói offline để người dùng xem trước. Khi cần đối soát ràng buộc của bước gửi, dùng [luồng delivery V2](SOCIAL_V2_STANDALONE_DELIVERY.md) và đi qua các cổng cấp quyền tương ứng.
