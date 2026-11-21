# Luồng gửi gói Meta độc lập V2

`scripts.social.meta_package_workflow.run_meta_package_workflow` hiện có đường xử lý cho một bài chữ Threads. Cổng quyền production V2 đang chặn toàn bộ luồng trước mọi đọc tài khoản hoặc gửi dữ liệu. Luồng yêu cầu `enable_dispatch=True`, gói standalone khớp tài khoản và digest trong phê duyệt, cùng một `occurrence_id` do hệ thống gọi giữ ổn định cho lần phát hành đó.

| Kênh và định dạng | Xử lý |
| --- | --- |
| Threads chữ | Đọc ID của chủ token, tạo container, đọc trạng thái container rồi gửi lệnh đăng khi Meta báo `FINISHED`. |
| Threads ảnh hoặc video, Instagram ảnh hoặc Reel | Chặn trước khi mở kết nối. Kho mã chưa có dịch vụ lưu trữ URL công khai giữ bất biến đúng bytes đã duyệt cho tới khi Meta tải xong. |
| Instagram chữ, album và định dạng khác | Ngoài phạm vi luồng này. |

Meta công bố hai yêu cầu POST cho Threads. Lệnh tạo container trả ID container. Lệnh đăng trả ID bài. Luồng kiểm giới hạn 500 ký tự trước khi gửi. Meta có cách tính emoji riêng nên dữ liệu sát giới hạn vẫn có thể bị nền tảng từ chối. [Tài liệu đăng bài Threads](https://developers.facebook.com/documentation/threads/posts)

GET trạng thái dùng ID đúng từ biên nhận tạo container và cùng credential vừa đọc lại chủ thể. Phản hồi phải có cùng ID, mã HTTP 200 và `status=FINISHED` thì luồng mới gửi lệnh đăng. `IN_PROGRESS` cho phép gọi lại cùng lần phát hành để đọc trạng thái sau. `ERROR`, `EXPIRED` và `PUBLISHED` dừng trước lệnh đăng. Mỗi lượt đọc nhiều nhất một trạng thái, không tự chạy vòng lặp. Meta khuyến nghị đọc mỗi phút trong tối đa năm phút. [Tài liệu trạng thái container Threads](https://developers.facebook.com/documentation/threads/troubleshooting)

POST gửi `access_token` trong dữ liệu biểu mẫu. GET dùng header `Authorization: Bearer` để tránh đưa credential vào URL. Ví dụ GET của Meta dùng tham số URL. Chưa xác minh trên API thật rằng Threads chấp nhận header cho cả hai GET. Luồng dừng nếu đọc tài khoản hoặc trạng thái thất bại.

Trên POSIX, luồng dùng thư mục sổ riêng do tài khoản chạy sở hữu, quyền truy cập của group và others phải tắt. Khóa tạo container và khóa đăng là hai khóa độc lập, đều gắn với kênh, tài khoản và `occurrence_id`. Biên nhận lưu ID sau phản hồi hợp lệ và ràng buộc digest gói, tài khoản, credential và phiên bản API. Hai tệp lần thử được giữ khi kết quả không xác định để chặn gửi lặp. Hãy giữ nguyên thư mục sổ và `occurrence_id` khi tiếp tục một lần phát hành. Khi thiếu biên nhận sau một lần POST, cần đối soát trước khi tạo một lần phát hành khác. Windows chưa hỗ trợ sổ ghi bền theo hợp đồng transport. [Sổ Transport V2](SOCIAL_V2_TRANSPORT.md)

`accepted_by_provider` trả `provider_id` của bài và `container_id` của container. Lần gọi lại có thể đọc biên nhận đăng đúng ràng buộc từ sổ mà không gửi thêm yêu cầu mạng. Kiểm tra bài có thể xem công khai cần một lượt đối soát riêng.

## Điều kiện mở đường ảnh và video

Luồng web hiện tại dùng `git_static` để đưa nội dung lên nhánh xuất bản. Khi bật xác minh HTTP 200, `web_publish.py` chỉ kiểm URL `.html` của bài. Các tệp media nằm ngoài bước kiểm đó. URL theo slug có thể đổi nội dung khi nhánh được cập nhật. [Luồng xuất bản web](../../scripts/pipeline/web_publish.py#L207)

Khi có dịch vụ lưu trữ phù hợp, tích hợp cần ràng buộc những điểm sau.

- Đọc tệp từ gói đã duyệt, đối chiếu kích thước và SHA-256 rồi chuyển chính bytes đó cho dịch vụ lưu trữ.
- Dùng URL trỏ tới một phiên bản cố định được bảo vệ khỏi xóa, hoặc tới khóa lưu trữ được bảo vệ khỏi ghi đè và xóa. Thao tác chỉ tạo bảo vệ tại thời điểm tải lên. Các bảo đảm lưu trữ phải có hiệu lực trong toàn bộ thời gian Meta có thể tải media, kể cả khi container còn xử lý.
- Đối chiếu SHA-256 của đối tượng được phục vụ với gói, qua checksum SHA-256 mà dịch vụ bảo đảm hoặc tải lại đủ bytes từ URL đó. HTTP 200 và SHA-256 do bên gọi tự khai chưa đủ.
- Meta phải tải được URL HTTPS qua Internet mà không cần credential của ứng dụng. URL và đối tượng phải tiếp tục khả dụng trong khoảng thời gian nhập media đã xác định. Gắn định danh phiên bản hoặc đối tượng với digest gói và `occurrence_id` trước khi tạo container.
- Giữ bước tạo container đóng nếu không xác nhận được đối tượng, thời hạn hoặc liên kết với gói đã duyệt. Với Instagram Facebook Login, đối chiếu tài khoản Instagram với Page liên kết bằng cùng credential và đọc `status_code` của container trước khi đăng. [Tài liệu Instagram của Meta](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-23eacf45-3728-4e41-bcc7-6d164959327c)
