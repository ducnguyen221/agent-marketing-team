# Tải ảnh và video lên X qua API v2

`scripts/social/x_media_upload.py` triển khai bước tải media của gói độc lập V2. Hàm `upload_x_package_media` yêu cầu gói đã duyệt, ID tài khoản X, ID lượt thực thi ổn định, token OAuth 2.0 của người dùng và thư mục sổ lần gửi. Cổng quyền production được gọi ngay đầu hàm. Cổng hiện chặn thao tác ghi khi chưa có quyền production gắn với nguồn duyệt.

- Ảnh dùng `POST /2/media/upload` với `media_category=tweet_image` và ảnh mã hóa Base64. Giới hạn tại adapter là 5.000.000 byte. [X API Upload Media](https://docs.x.com/x-api/media/upload-media)
- Video MP4 dùng `initialize`, `append` rồi `finalize`. Adapter gửi các đoạn 4 MiB theo thứ tự từ 0 bằng JSON Base64 và chỉ chuyển sang `finalize` sau khi mỗi đoạn được xác nhận. [Hướng dẫn tải theo đoạn](https://docs.x.com/x-api/media/quickstart/media-upload-chunked) · [X API Append Media Upload](https://docs.x.com/x-api/media/append-media-upload)
- Khi X trả `processing_info`, adapter đợi theo `check_after_secs` với tối đa năm lần gọi đọc và ngân sách chờ 30 giây, đồng thời kiểm tra hạn dùng và ID media ở mỗi lần đọc. Trạng thái `succeeded` cho phép trả ID. Theo hợp đồng X, phản hồi hoàn tất hợp lệ không có `processing_info` cũng cho phép dùng media ngay. [X API Finalize Media Upload](https://docs.x.com/x-api/media/finalize-media-upload) · [X API Get Media Upload Status](https://docs.x.com/x-api/media/get-media-upload-status)

Adapter dùng cùng token để đối chiếu tài khoản qua `/2/users/me` và để ghi media. Các byte được đọc một lần từ gói sau khi kiểm tra đích, mã băm gói, độ dài và SHA-256 của tệp. Adapter giữ một lần gửi cho mỗi tài khoản và lượt thực thi, kể cả khi duyệt lại hoặc thay đổi gói. Sổ lần gửi hiện yêu cầu POSIX. Adapter gửi trực tiếp tới `api.x.com`, giữ dấu lần gửi sau lỗi hoặc phản hồi mơ hồ và không tự phát lại các yêu cầu ghi.

Kết quả `available` chứa `provider_id` và thời hạn bảo thủ tính bằng giây Unix, kèm tài khoản, mã băm gói, mã băm tệp, lượt thực thi và khóa lần gửi. Bên tiêu thụ cần kiểm tra các ràng buộc này cùng hạn dùng ngay trước khi gắn media vào bài. Các trạng thái còn lại giữ `provider_id` rỗng. Khi X đã trả ID hợp lệ, adapter giữ ID trong `reconciliation_id` để đối soát và giữ `expires_at` nếu xác định được hạn dùng. JSON có khóa trùng hoặc giá trị số không chuẩn bị từ chối trước khi đọc trạng thái.

Khi X trả ID hợp lệ, adapter ghi biên nhận gồm ID, tài khoản, đích, dấu vân tay gói, SHA-256 tệp, loại media, mã lượt và khóa lần tải. Hạn dùng được ghi khi có dữ liệu hợp lệ. Trên POSIX, mã đồng bộ tệp và thư mục sau khi thay biên nhận. Mốc sau FINALIZE và mỗi kết quả STATUS hợp lệ lưu trạng thái, hạn dùng và thời điểm đọc tiếp. Hạn dùng qua các lần đọc chỉ có thể giảm.

Khi gọi lại [luồng X V2](SOCIAL_V2_X_WORKFLOW.md) với cùng gói và lượt video, adapter chỉ tiếp tục đọc STATUS nếu biên nhận khớp lần tải và cho thấy FINALIZE đã được xác nhận. Biên nhận chỉ có ID ban đầu hoặc dấu tải cũ thiếu biên nhận dừng để đối soát. Trạng thái hoàn tất chuyển bước khi STATUS xác nhận `succeeded` và media còn hạn. Windows dừng trước khi gửi. Cổng quyền production vẫn áp dụng cho việc đối soát và đăng bài.

Phạm vi kiểm chứng hiện tại là đối chiếu mã nguồn. Chưa chạy kiểm thử đồng thời, kiểm thử khôi phục sau sự cố, tải media hoặc đăng bài.
