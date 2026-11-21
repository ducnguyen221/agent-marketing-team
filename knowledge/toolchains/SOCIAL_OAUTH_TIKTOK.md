# TikTok Login Kit cho phép kiểm chỉ đọc

Luồng cấp token tự động đang chờ một backend OAuth do chủ ứng dụng kiểm soát. TikTok Login Kit Desktop cho phép đăng ký callback HTTP trên máy cục bộ, gồm các địa chỉ `127.0.0.1` hoặc `localhost` có cổng. Giới hạn này áp dụng cho đích trả mã của trình duyệt. Hợp đồng Desktop vẫn giao cho backend trách nhiệm đổi mã thành token và giữ `client_secret` an toàn. [TikTok Login Kit Desktop](https://developers.tiktok.com/docs/en/login-kit-desktop) · [TikTok Login Kit Overview](https://developers.tiktok.com/docs/en/login-kit-overview)

## Khi có backend đã được chủ ứng dụng xác nhận

1. Chủ ứng dụng đăng ký Login Kit cho nền tảng Desktop, kiểm quyền `user.info.basic` và đăng ký chính xác callback loopback mà triển khai dùng. Giữ cùng `redirect_uri` trong yêu cầu ủy quyền và yêu cầu đổi mã. [TikTok Login Kit Desktop](https://developers.tiktok.com/docs/en/login-kit-desktop)
2. Mỗi phiên dùng bộ sinh số ngẫu nhiên an toàn cho mật mã để tạo `state` và PKCE verifier mới. Verifier dài 43–128 ký tự, dùng tập `A–Z`, `a–z`, `0–9`, `-`, `.`, `_`, `~`. TikTok Desktop quy định challenge S256 là **SHA-256 mã hóa hex**. Mở trang ủy quyền chính thức `https://www.tiktok.com/v2/auth/authorize/` với riêng `user.info.basic`. Callback kiểm `state`, đích nhận đã đăng ký, mã ủy quyền và trường `scopes` trả về. Nếu người dùng từ chối, callback có `error` hoặc `scopes` khác `user.info.basic`, dừng trước bước đổi mã. [TikTok Login Kit Desktop](https://developers.tiktok.com/docs/en/login-kit-desktop)
3. Backend tin cậy đổi mã một lần tại `https://open.tiktokapis.com/v2/oauth/token/` với `client_key`, `client_secret`, đúng `redirect_uri`, `code_verifier` và `grant_type=authorization_code`. Phản hồi token dùng trường `scope`. Quy trình chỉ đọc này yêu cầu giá trị đúng `user.info.basic` và chỉ giữ access token cho phép kiểm. [TikTok Get a User Access Token](https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token)
4. So `open_id` trong phản hồi token và từ `GET /v2/user/info/?fields=open_id` với ID kỳ vọng đã xác lập độc lập cho **chính ứng dụng đó**, rồi mới lưu. Nếu thiếu nguồn độc lập hoặc hai kết quả lệch, dừng trước khi lưu. ID từ chính lần đổi mã, tên tài khoản và ID của app khác đều không xác lập được giá trị kỳ vọng. [TikTok Get a User Access Token](https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token) · [TikTok Get User Info](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info)

## Dùng access token do backend hiện có cấp

Nếu chủ ứng dụng đã có access token từ backend tin cậy, hãy tự điền cấu trúc [mẫu TikTok](../../templates/social_auth/tiktok-userinfo.example.json) vào `~/.secret/<profile>/tiktok-userinfo.json` trong thư mục cục bộ đã giới hạn quyền truy cập. File dùng schema `tiktok-userinfo/1`, provider `tiktok`, token kind `oauth_access_token`, cùng ba trường `client_key`, `expected_open_id`, `access_token`. Giữ client secret và refresh token ở ngoài profile và kho mã. Dùng tên profile mới khi cần lưu một cấu hình riêng.

Khi chủ tài khoản chủ động muốn kiểm chỉ đọc, chạy từ gốc plugin:

```powershell
python -m scripts.social.channels.tiktok.readonly_auth --check-readonly --profile ten-profile
```

`identity=match` cho biết User Info trả về ID trùng với giá trị kỳ vọng trong file. Kết quả của reader tự nó chỉ xác nhận phép so ID. Xem [quy trình kiểm kết nối chỉ đọc](SOCIAL_AUTH_TEST.md#tiktok-chuẩn-bị-cho-lần-kiểm-chỉ-đọc-sau-này) để biết các giới hạn của reader. Chưa thực hiện lần cấp quyền hay kiểm tài khoản thật trong lượt này.
