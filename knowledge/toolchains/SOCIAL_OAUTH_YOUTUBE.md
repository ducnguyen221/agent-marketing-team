# Chủ kênh thiết lập YouTube OAuth chỉ đọc

Dùng lệnh này trên máy của chủ kênh để tạo hồ sơ xác minh YouTube V2. Google cấp quyền `youtube.readonly`. Lệnh đối chiếu kênh qua `channels.list(mine=true)` trước khi cho lưu. Kết quả xác nhận kênh dự kiến xuất hiện trong phản hồi Google lúc thiết lập. Quyền đăng và quyền sở hữu ứng dụng Google Cloud cần bằng chứng riêng.

1. Trong Google Cloud, bật YouTube Data API v3 và tạo OAuth client loại **Desktop app** cho dự án đã cấu hình màn hình đồng ý. Nếu ứng dụng ở chế độ thử nghiệm, dùng tài khoản được cấu hình làm người dùng thử nghiệm. Dùng ứng dụng và kênh chủ kênh có quyền sử dụng.
2. Tự chuẩn bị thư mục riêng `~/.secret/<profile>/` trên ổ cục bộ. Trên Windows, kiểm tra thư mục thừa kế quyền truy cập riêng của chủ máy. Lưu JSON của client vào đúng thư mục này với tên `youtube-oauth-client.json`. Đặt tệp trực tiếp trong thư mục kho secret. Tệp và đường dẫn phải là tệp, thư mục thật, một liên kết, nằm dưới tài khoản của chủ máy.
3. Tại terminal tương tác của chủ kênh, đứng ở gốc repo và thay tên hồ sơ, mã kênh trong lệnh dưới đây. Lấy mã kênh dạng `UC…` từ YouTube, không dùng handle dạng `@…`.

   ```powershell
   python -m scripts.social.channels.youtube.oauth_setup --authorize-readonly --profile demo-youtube --expected-channel-id CHANNEL_ID
   ```

4. Gõ `authorize` để mở trang Google trong trình duyệt mặc định. Kiểm tra tài khoản, ứng dụng và phạm vi chỉ đọc trên màn hình Google rồi tự quyết định cấp quyền. Callback chạy trên `127.0.0.1` với cổng chọn cho từng lượt, chờ tối đa 180 giây. Có thể đóng tab sau khi trình duyệt xác nhận đã nhận callback.
5. Sau khi terminal xác nhận khớp kênh, xác nhận quyền truy cập thư mục là riêng tư rồi gõ `save` để tạo `~/.secret/<profile>/youtube-channel-userinfo.json`. Lệnh ghi hoàn chỉnh vào tệp tạm trong chính thư mục rồi đưa vào tên đích. Nếu tên đích đã tồn tại, lệnh giữ nguyên tệp đó; dùng bí danh mới cho lần thiết lập tiếp theo. Nếu mất điện hoặc tiến trình bị chấm dứt đột ngột, chủ máy có thể phải dọn tệp `.youtube-oauth-*.tmp` còn sót tại đúng thư mục hồ sơ. Dùng hồ sơ khi access token còn hạn.

Muốn đối chiếu lại kênh, chủ máy có thể chạy lệnh hiện có. Lệnh này gửi yêu cầu đọc đến YouTube.

```powershell
python -m scripts.social.channels.youtube.readonly_auth --check-readonly --profile demo-youtube
```

Access token có thời hạn theo phản hồi Google. Tiện ích bỏ refresh token nếu Google trả về. Khi access token hết hạn, tự thực hiện lượt cấp mới. Muốn rút quyền, chủ kênh vào phần kết nối của tài khoản Google để thu hồi quyền của ứng dụng. Việc hủy ở terminal sau màn hình đồng ý chỉ dừng ghi hồ sơ cục bộ.

Tham khảo [OAuth 2.0 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app) và [YouTube Data API authorization](https://developers.google.com/youtube/data/guides/authentication).
