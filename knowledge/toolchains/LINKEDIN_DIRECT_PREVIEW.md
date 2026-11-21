# LinkedIn trực tiếp: xem trước và chuẩn bị xác thực

Đây là bộ dựng **request LinkedIn native** của agent-marketing-team; không cần server hoặc API Postiz. Mã chỉ dựng dữ liệu và đọc kết quả giả trong bộ nhớ, không đọc key, kết nối LinkedIn, upload, lập lịch hay đăng. `lifecycleState: PUBLISHED` trong candidate là trường của API LinkedIn; gửi request đó thật có thể tạo bài công khai. Preview không phải quyền phát.

## Thử text, ảnh hoặc video giả

Tại gốc plugin:

```powershell
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
@'
{"source":"## post:linkedin_post\nNoi dung gia\n","anchor":"post:linkedin_post","author":"urn:li:person:fixture-member","api_version":"202611"}
'@ | python -m scripts.social.cli prepare-linkedin
```

`post:linkedin_post` hiện là anchor fixture đề xuất, **chưa phải enum hoặc output V1**. Chưa nối với chiến dịch thật. Author trong ví dụ là giả; `api_version` chỉ kiểm hình dạng, chưa xác minh phiên bản đang được LinkedIn chấp nhận. Candidate dùng plaintext `little`: ký tự đặc biệt được escape; hashtag và mention hiện hiển thị như chữ thường, chưa có chức năng liên kết native. Bộ đếm giới hạn nền tảng chưa được xác minh.

Để kiểm cấu trúc ảnh/video bằng dữ liệu giả, có thể bổ sung `media_kind` là `image` hoặc `video` và `media_urn` tương ứng `urn:li:image:fixture-image` hoặc `urn:li:video:fixture-video`. Builder không tạo, đọc, tải hay xác minh media; URN đúng hình dạng không chứng minh media thuộc author hoặc đã sẵn sàng. Không dùng candidate như lệnh đăng.

Có thể xem request **khởi tạo upload giả** mà không gửi đi:

```powershell
@'
{"kind":"video","owner":"urn:li:organization:12345","api_version":"202611","file_size":1055736}
'@ | python -m scripts.social.cli prepare-linkedin-media
```

Code `scripts/social/channels/linkedin/media.py` còn mô phỏng chia khoảng byte, ghép ETag theo thứ tự, thời hạn và trạng thái xử lý. Mẫu LinkedIn cho phép khoảng cuối vượt quá EOF; bộ dựng cắt ở byte cuối tệp, không thêm dữ liệu. Fixture finalize chỉ nhận nhãn giả, không nhận URL upload hoặc token thật. Digest phiên và part giúp kiểm tính nhất quán của dữ liệu giả, **không** xác thực response hay quyền owner. Xem `tests/test_social_linkedin_media.py` để thử các ca sai phiên, hết hạn và phản hồi `403`.

## Xác thực trực tiếp sau này

1. Chủ tài khoản chọn profile hoặc organization, tạo ứng dụng LinkedIn và chọn sản phẩm/quyền theo [tài liệu Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api). Quyền viết cá nhân và tổ chức khác nhau; tổ chức còn cần vai trò Page phù hợp. Quyền đọc lại cũng có điều kiện riêng, không tự suy từ quyền viết.
2. Chủ tài khoản tự quản lý client secret, token và quy trình đồng ý OAuth trong kho bí mật của máy; không gửi token, mã OAuth hay callback có tham số qua chat. Bộ OAuth trực tiếp của plugin **chưa triển khai** và chưa có callback để cấu hình.
3. Khi có bộ kiểm chỉ đọc trực tiếp và quyền cụ thể, kiểm đúng author và quyền trước. Chưa tạo, upload hoặc đăng bất kỳ nội dung nào khi phạm vi chỉ là kiểm kết nối.

## Bằng chứng và giới hạn

Response HTTP `201` có đúng một `x-restli-id` hợp lệ được parser ghi `accepted`; trạng thái xem lại vẫn `unverified`. Thiếu ID, ID không hợp lệ hoặc kết quả mơ hồ là `unknown`. Parser đọc lại giả chỉ ghi `provider_reports_published` khi ID, author, trạng thái và visibility khớp; HTTP `403` hay kết quả sai giữ nguyên receipt `accepted`, đánh dấu lượt đọc hiện tại chưa xác minh và giữ cờ đã từng được báo published. Đây là dữ liệu do caller cung cấp, chưa xác minh nguồn response hoặc quyền xem công khai. Parser chưa gắn receipt với attempt/author được duyệt và chưa nối dispatcher; không được dùng nó làm bằng chứng bài đã hiển thị. Luồng upload thật, kiểm quyền owner và xử lý media thật chưa được triển khai hoặc chạy.

Đối chiếu: [LinkedIn Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api), [Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api), [Videos API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api), [định dạng little](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format). Thiết kế học cách Postiz tách xử lý/publish/finalize/receipt theo nguồn đã cho phép trong hồ sơ nghiên cứu, không gọi Postiz và không sao chép provider bị đánh dấu Chặn.
