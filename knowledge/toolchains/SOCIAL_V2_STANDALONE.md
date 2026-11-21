# Chuẩn bị gói xem trước social V2 từ file độc lập

Dùng để chuẩn bị bài chữ hoặc bài có ảnh, video hay tài liệu từ tệp cục bộ. Mỗi gói dành cho một kênh và một đích dự kiến. Để chuẩn bị cùng một nội dung cho nhiều kênh, viết caption phù hợp từng kênh và dùng lại tệp media nếu định dạng phù hợp.

## Đầu vào

- Chọn một thư mục nguồn cục bộ. Caption là tệp `.txt` hoặc `.md` mã hóa UTF-8, nội dung hiển thị dưới dạng chữ giữ xuống dòng. Nếu soạn bằng Markdown, bỏ dấu định dạng trước khi chạy nếu không muốn chúng xuất hiện trong caption.
- Chọn một ảnh PNG, JPEG hoặc WebP tĩnh, một video MP4, hoặc một PDF cho Telegram và Discord. Chọn loại `text` cho bài chỉ có chữ. Ảnh và video được kiểm tra định dạng và kích thước khung hình. MP4 cần `ffprobe` trong PATH.
- Với album ảnh Telegram, dùng `--platform telegram --kind image --media-files first.jpg second.png`. Nhập 2–10 ảnh PNG hoặc JPEG tĩnh theo thứ tự muốn đăng, tối đa 10.000.000 byte mỗi ảnh. Caption tùy chọn đi cùng ảnh đầu tiên và giới hạn 1.024 đơn vị UTF-16 theo quy ước của adapter. [Telegram Bot API](https://core.telegram.org/bots/api#sendmediagroup)
- Với album ảnh Discord, dùng `--platform discord --kind image --media-files first.jpg second.png --text-file caption.txt`. Nhập 2–10 ảnh PNG, JPEG hoặc WebP tĩnh theo thứ tự muốn đăng. Gói giới hạn mỗi ảnh ở 20 MiB và tổng ảnh ở 24 MiB để chừa chỗ cho nội dung và phần bao multipart. Caption là nội dung chung của một tin nhắn. [Discord Create Message](https://docs.discord.com/developers/resources/message#create-message)
- Bỏ `--text-file` khi chuẩn bị ảnh, video hoặc PDF cho Telegram, video YouTube không có mô tả, hoặc video TikTok Inbox. YouTube vẫn cần metadata riêng khi ràng buộc đích gửi, trong đó có tiêu đề. Các kênh và loại bài còn lại cần `--text-file`. Nếu truyền tùy chọn này, tệp phải chứa chữ.
- Dùng `--comment-file` nếu muốn kèm bình luận đầu cho bài chữ hoặc ảnh trên Facebook Page, hoặc cho bài LinkedIn. Video Facebook dùng một loại mã kết quả riêng, nên luồng hiện tại chưa thể xác nhận mã bài đăng để gửi bình luận đầu.
- Nếu đã biết ID, truyền `--account-id` cho tài khoản dự kiến thao tác và `--destination-id` cho Page, channel hoặc profile nhận nội dung. Hai trường được ghi riêng. Discord kiểm tra cú pháp ID đích trước khi tạo gói. ID bỏ trống hiển thị là “Chưa chỉ định”. Chỉ dùng định danh công khai hoặc dùng để review nội bộ, không truyền thông tin xác thực.

Đường dẫn caption, bình luận và media tính từ `--source-dir`, dùng dấu `/` giữa các cấp. Đặt nguồn và đầu ra trên ổ đĩa cục bộ tin cậy. Tránh ổ mạng đã ánh xạ và thư mục đồng bộ. Chỉ chọn file đã có đầy đủ trên ổ đĩa và được phép chia sẻ với người duyệt, kể cả metadata trong ảnh hoặc video. Mỗi caption/bình luận tối đa 2 MiB và media tối đa 256 MiB. Thư mục cha của đầu ra phải tồn tại. Lệnh tạo thư mục đích mới và từ chối đích đã có.

## Ví dụ

Giả sử `drafts` có `facebook.txt`, `linkedin.md` và `cover.png`, còn thư mục `out` đã tồn tại. Từ gốc repo, chạy từng lệnh:

```powershell
python -m scripts.social.prepare_standalone --source-dir .\drafts --text-file facebook.txt --media-file cover.png --platform facebook --kind image --output-dir .\out\facebook-review
python -m scripts.social.prepare_standalone --source-dir .\drafts --text-file linkedin.md --media-file cover.png --platform linkedin --kind image --output-dir .\out\linkedin-review
python -m scripts.social.prepare_standalone --source-dir .\drafts --media-file cover.png --platform telegram --kind image --output-dir .\out\telegram-review
```

| Kênh | Đích | Loại gói xem trước |
|---|---|---|
| Facebook | Page | Chữ, ảnh, video |
| LinkedIn, Threads, X | Tài khoản | Chữ, ảnh, video |
| Instagram | Tài khoản | Ảnh, video |
| Telegram | Channel | Chữ, ảnh, album ảnh, video, PDF |
| Discord | Channel | Chữ, ảnh, album ảnh, video, PDF |
| YouTube | Channel | Video |
| TikTok | Profile | Video cho tuyến Inbox dự kiến |

## Xem kết quả

Mở `review.html` trong từng thư mục kết quả để đối chiếu caption, loại đích, ID và media. Nếu bỏ caption ở tuyến hỗ trợ, trang xem trước ghi rõ điều này. Telegram giới hạn bài chữ ở 4.096 đơn vị UTF-16 và caption media ở 1.024 đơn vị UTF-16. Discord giới hạn nội dung ở 2.000 ký tự. `package.json` lưu schema `social-standalone-package/1`, nguồn tệp và mã băm. Mã băm văn bản tính trên nội dung UTF-8 đã bỏ BOM, trước khi bỏ khoảng trắng ở hai đầu và chuẩn hóa xuống dòng CRLF thành LF. Media sao chép giữ nguyên byte, kèm mã SHA-256, số byte và kích thước khung hình nếu có.

Gói có trạng thái `prepared_for_review` và nguồn `standalone_files`. Dùng [bước đối soát với adapter V2](SOCIAL_V2_STANDALONE_DELIVERY.md) để kiểm tra ràng buộc tài khoản, đích đến và media. Việc gửi vẫn bị chặn ở cổng cấp quyền production. Nếu nội dung đã thuộc một chiến dịch, đi theo [luồng chiến dịch và các cổng duyệt hiện hành](SOCIAL_V2_PACKAGE.md).

Album hiển thị đủ ảnh trong `review.html`. Manifest dùng action `post_image_album` và lưu danh sách ảnh theo đúng thứ tự trong `source.media_files` và `media`. Mã gói ràng buộc caption, thứ tự và SHA-256 từng ảnh.
