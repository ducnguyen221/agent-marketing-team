# Instagram: xem trước ảnh và Reel bằng dữ liệu giả

V2 có candidate offline theo Instagram API với **Facebook Login**. Candidate không chứa token, không gửi mạng, không tải media và không cấp quyền phát. `user_id` là IG User ID giả, không phải Page ID; cấu trúc chữ số không xác thực danh tính.

Theo [bộ tài liệu Instagram của Meta](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-3fe78620-2258-44b6-893f-42d76c7200d7), nhánh Facebook Login yêu cầu tài khoản Instagram chuyên nghiệp liên kết Page. Tài khoản, app, quyền và phiên bản API chưa được kiểm ở đây. [Reel của Meta](https://www.postman.com/meta/instagram/request/5kkpkh6/upload-a-reel-to-an-ig-container) dùng `media_type=REELS` và `video_url`, sau đó phải kiểm trạng thái container trước bước phát.

Từ gốc plugin, ví dụ dữ liệu giả (không dùng URL hoặc nội dung thật):

```powershell
'{"source":"## post:instagram_reel\nVideo giả\n","anchor":"post:instagram_reel","user_id":"123","api_version":"v21.0","media_type":"REELS","media_url":"https://media.example.test/video.mp4"}' | python -m scripts.social.cli prepare-instagram
```

Với ảnh, dùng `media_type` là `IMAGE`, anchor `post:infographic` và URL ảnh giả. Parser lấy duy nhất dòng `**Caption:** ...` ở cuối phần infographic; không coi prompt tạo ảnh là caption. Với Reel, `post:instagram_reel` là anchor đề xuất cho fixture, **chưa thuộc enum V1**. Cả hai chỉ dựng yêu cầu tạo container. Hàm Python `preview_publish` riêng mô tả bước phát nếu sau này được gửi; nó không chứng minh container đã sẵn sàng hoặc thuộc tài khoản.

URL chỉ được kiểm cú pháp hạn chế, không xác minh DNS, khả năng truy cập công khai, quyền sở hữu hoặc chất lượng video/ảnh; không dùng URL có thông tin bí mật. Chưa có upload, trạng thái container thực, đối soát, carousel, Stories, V1 binding, xác thực hay dispatch live. Preview Postiz cũ vẫn chỉ là nghiên cứu; luồng này không dùng Postiz.
