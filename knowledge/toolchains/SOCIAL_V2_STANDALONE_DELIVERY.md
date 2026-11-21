# Đối soát gói độc lập với adapter social V2

Gói `social-standalone-package/1` dùng chữ hoặc media từ tệp cục bộ. Adapter V2 kiểm tra trực tiếp schema này, giữ nguyên nguồn `standalone_files` và mã băm của gói. Với nội dung thuộc chiến dịch, dùng quy trình chiến dịch và hồ sơ duyệt tương ứng. [Chuẩn bị gói độc lập](SOCIAL_V2_STANDALONE.md) · [Quy trình chiến dịch](SOCIAL_V2_PACKAGE.md).

## Định danh đích

Khi tạo gói để đưa vào adapter, truyền cả `--account-id` và `--destination-id` theo bảng. Lấy ID từ nguồn định danh đã xác minh của kênh. Giá trị trống vẫn dùng được cho xem trước bằng HTML.

| Adapter V2 | Account ID | Destination ID | Thao tác đã nối với schema |
|---|---|---|---|
| Facebook Page | Page ID của thông tin xác thực | Cùng Page ID | Chữ, ảnh, video, bình luận đầu |
| LinkedIn | URN thành viên, dạng `urn:li:person:…` | Cùng URN | Chữ, ảnh, video, bình luận đầu |
| Threads | User ID | Cùng User ID | Chữ, ảnh, video qua container |
| Instagram | User ID của tài khoản Instagram | Cùng User ID | Ảnh, video qua container |
| X | Account ID | Cùng Account ID | Chữ, ảnh, video |
| Telegram | Bot ID | Channel ID dạng `-100…` | Chữ, ảnh, album ảnh, video, PDF |
| YouTube | Channel ID | Cùng Channel ID | Tải video với metadata được ràng buộc riêng |
| TikTok | Account ID đã xác minh của ứng dụng | Cùng Account ID | Tải video vào Inbox. Caption chỉ để người duyệt xem |
| Discord | Bot ID | Channel ID | Chữ, ảnh, album ảnh, video, PDF. Ràng buộc thêm Guild ID khi chọn tuyến. |

## Kiểm tra cục bộ

Gọi `inspect_standalone_package(directory, platform=..., account_id=..., destination_id=..., package_digest=...)` từ `scripts.social.standalone_delivery`. Truyền mã SHA-256 chuẩn hóa của manifest đã đưa đi review. Repo tính mã này bằng `canonical_snapshot(manifest)[1]` trong `scripts.lib.delivery_contract`. Đối chiếu với giá trị đã lưu từ lần review nếu cần phát hiện sửa đổi sau review.

Hàm trả `integrity_checked` cùng action, tài khoản, đích và mã gói. Phạm vi kiểm gồm manifest, cấu trúc trường nguồn và bản media đã sao chép vào gói. Việc đối chiếu các tệp gốc nằm ngoài thư mục gói cần một bước riêng. Giá trị `text_sha256` khai báo trong manifest tính từ văn bản nguồn đã bỏ BOM, trước khi cắt khoảng trắng.

Tuyến album Telegram và Discord kiểm số byte và SHA-256 cho mọi ảnh theo thứ tự manifest. Caption, thứ tự ảnh, tài khoản và đích cùng thuộc dấu vân tay gói đã xem trước. Quy trình biên nhận Discord còn kiểm phản hồi của từng tệp thuộc cùng tin nhắn. [Discord V2](SOCIAL_V2_DISCORD_WORKFLOW.md)

Khi bỏ caption ở tuyến được hỗ trợ, manifest lưu `content.text` là chuỗi rỗng và lược `source.text`. Hai điều kiện này phải khớp khi đối soát. Mã gói ràng buộc cả việc bỏ caption và mã băm của media. Adapter Telegram bỏ trường `caption` khỏi yêu cầu gửi tệp. YouTube dùng mô tả rỗng trong metadata cần duyệt. TikTok Inbox vẫn chỉ tải video vào Inbox.

Facebook Page, Telegram, YouTube và TikTok Inbox kiểm số byte và SHA-256 rồi dùng chính bản byte đã kiểm khi xây payload gửi tệp. `prepare_linkedin_package_media` trả bản byte cho bước upload tương lai, còn thao tác tạo bài LinkedIn dùng media URN. LinkedIn, X, Threads và Instagram cần định danh media do luồng upload hoặc hosting đã xác minh, gắn với đúng tài khoản và SHA-256 của tệp. Các bước tạo container, xuất bản container và bình luận tiếp tục yêu cầu quan sát tương ứng của adapter.

Mọi lệnh gửi vẫn dừng tại `production_approval_generation_unavailable`. Mã gói và kết quả kiểm tra cục bộ chỉ xác nhận nội dung và đích được ràng buộc. Quyền đăng thật còn cần nguồn cấp duyệt production, xác minh thông tin xác thực và kiểm các điều kiện của từng tuyến.
