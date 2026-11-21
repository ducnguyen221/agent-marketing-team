# Threads: dựng yêu cầu trực tiếp offline

Mã `scripts/social/channels/threads/direct.py` dựng candidate theo Threads API cho một bài chữ, một ảnh hoặc một video; không đọc token, gọi mạng, upload hay gửi bài. Dữ liệu Postiz chỉ là nguồn tham khảo kiến trúc; không gọi hay phụ thuộc Postiz. Luồng này chưa nối dispatcher hoặc trạm V1.

Từ thư mục plugin có thể kiểm một đoạn nội dung **giả**:

```powershell
@'
{"source":"## post:threads_post\nBai viet gia\n","anchor":"post:threads_post","user_id":"123","api_version":"v1.0","media_type":"TEXT"}
'@ | python -m scripts.social.cli prepare-threads
```

`post:threads_post` là anchor thử nghiệm chưa thuộc enum V1. Với `IMAGE` hoặc `VIDEO`, cung cấp thêm `media_url` HTTPS không chứa query, fragment hoặc thông tin đăng nhập. URL là dữ liệu mẫu, không chứng minh Meta đọc được media; không đưa URL ký có token vào preview hay log. Builder từ chối một số địa chỉ nội bộ rõ ràng nhưng không phân giải DNS và không chứng minh URL an toàn, công khai, đúng định dạng hay thuộc đúng người dùng.

Theo [bộ sưu tập API Threads của Meta](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api), tạo container và phát bài là hai yêu cầu khác nhau. Builder không đưa `auto_publish_text` vào yêu cầu tạo container vì tùy chọn đó có thể phát bài chữ ngay. Hàm `preview_publish` chỉ dựng mô tả bước phát; nếu thực sự gửi yêu cầu đó thì có thể đăng bài. Phiên bản API, hạn mức, quyền, nội dung và media đều chưa được kiểm trên nền tảng thật.

Không suy `container_id` là ID bài đăng. Trạng thái xử lý media, quyền sở hữu container, receipt, đối soát sau mất phản hồi, lịch bền và xác thực vẫn phải hoàn thiện trước khi có đường gửi thật. Không tự gửi lại khi kết quả chưa rõ. Output có thể chứa nội dung và URL đầu vào, nên chỉ dùng dữ liệu được phép đưa vào log.
