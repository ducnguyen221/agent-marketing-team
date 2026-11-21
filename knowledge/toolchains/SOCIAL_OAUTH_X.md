# Thiết lập OAuth chỉ đọc cho X

Chủ tài khoản tự chạy từ terminal tương tác. Công cụ dùng OAuth 2.0 Authorization Code với PKCE S256 của **Native App**, rồi dùng chính access token vừa nhận để đối chiếu `data.id` từ `GET https://api.x.com/2/users/me`. Kết quả chỉ xác nhận tài khoản đang cấp quyền trùng ID kỳ vọng. Việc sở hữu ứng dụng, quyền xuất bản và khả năng đăng bài cần bằng chứng riêng. [Tài liệu OAuth của X](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) · [Get My User](https://docs.x.com/x-api/users/get-my-user)

## Chuẩn bị

1. Trong X Developer Console, chọn ứng dụng **Native App** do bạn quản lý, bật OAuth 2.0 trong phần User authentication settings và chọn quyền **Read** nếu giao diện hỏi. Lấy **OAuth 2.0 Client ID** công khai ở Keys and Tokens. Native App dùng `client_id` trong thân yêu cầu đổi mã. Nếu ứng dụng là Web App, Automated App hoặc bot dùng client secret, dừng và chọn Native App riêng. [Loại client và thiết lập ứng dụng trên X](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)
2. Đăng ký đúng callback `http://127.0.0.1:8767/x-oauth-callback` với ứng dụng đó. Công cụ dùng cùng URI ở cả hai bước và chỉ mở cổng IPv4 `8767` trên `127.0.0.1`. HTTP chỉ dùng cho callback trên chính máy. Trang cấp quyền và yêu cầu API dùng HTTPS. Khả năng Console của X chấp nhận URI này cho ứng dụng của bạn chưa được xác minh trực tiếp. Nếu Console từ chối hoặc cổng đang bận, dừng thiết lập. [Luồng OAuth và thông số đổi mã của X](https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token) · [RFC 8252 về loopback](https://www.rfc-editor.org/rfc/rfc8252#section-7.3)
3. Chuẩn bị ID số của tài khoản cần đối chiếu, lấy từ nguồn độc lập đã xác nhận trước khi cấp quyền. Dùng ID dạng chuỗi chữ số, giữ nguyên toàn bộ chữ số. Tên hiển thị, `@handle` và kết quả của chính phiên OAuth đang thiết lập không dùng làm bằng chứng độc lập. [Định dạng ID của X](https://docs.x.com/fundamentals/x-ids)
4. Tạo trước `~/.secret/<profile>/` trên ổ cục bộ mà bạn quản lý. Trên Windows, công cụ yêu cầu ổ cục bộ cố định và tài khoản đang chạy phải sở hữu kho và thư mục profile. Kiểm tra quyền kế thừa trong **Properties → Security → Advanced**. Bộ kiểm ACL chỉ chấp nhận quyền cấp cho chủ hiện tại, SYSTEM và Administrators. Công cụ dừng nếu xác minh không thành công, kể cả khi Windows PowerShell không khả dụng. Trên POSIX, thư mục kho và profile phải thuộc chủ đang chạy và có quyền `0700`. Tránh thư mục đồng bộ, ổ mạng, junction, symlink và cloud placeholder.

X yêu cầu `tweet.read` và `users.read` cho API nhận diện này. Công cụ yêu cầu đúng hai quyền và kiểm tra lại phạm vi khi X trả token. Quyền `tweet.read` cho phép đọc bài viết tài khoản có thể xem, dù công cụ chỉ gọi `/2/users/me`. Luồng này không xin quyền ghi, email hoặc `offline.access`. [Ánh xạ quyền theo endpoint](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping) · [Phạm vi và vòng đời token](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)

## Cấp quyền và lưu

Từ gốc plugin, thay `your-profile` bằng alias đã chuẩn bị.

```powershell
python -m scripts.social.channels.x.oauth_setup --authorize-readonly --profile your-profile
```

1. Xác nhận callback và thư mục riêng tư bằng `authorize`. Nhập Client ID công khai và ID số kỳ vọng khi được hỏi. Giữ các bí mật, URL callback và mã cấp quyền trong công cụ hoặc trình duyệt, tránh sao chép vào terminal, chat hoặc tài liệu.
2. Trên trang `https://x.com/i/oauth2/authorize`, kiểm tra ứng dụng, tài khoản đang đăng nhập và các quyền yêu cầu rồi tự quyết định cấp quyền. Bộ nhận callback mở tối đa ba phút. Công cụ kiểm tra `state`, đổi mã ngay qua `POST https://api.x.com/2/oauth2/token` và dùng token mới để kiểm tra tài khoản. [Hướng dẫn chính thức về endpoint OAuth](https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token)
3. Khi terminal báo khớp tài khoản, gõ `save`. Công cụ tạo mới `~/.secret/<profile>/x-userinfo.json` theo schema `x-userinfo/1`. Nếu file đã tồn tại, công cụ từ chối ghi đè. Token chỉ được ghi vào profile riêng tư sau bước xác nhận. File chứa các trường bộ đọc cần, gồm access token và ID kỳ vọng. Công cụ không lưu refresh token hay phản hồi dữ liệu người dùng.

Chủ tài khoản có thể kiểm tra lại bằng lệnh sau.

```powershell
python -m scripts.social.channels.x.readonly_auth --check-readonly --profile your-profile
```

Access token thường có hiệu lực hai giờ trong luồng này. Khi cần cấp lại, chọn alias khác hoặc tự quản lý file cũ trong kho. Hủy bước lưu vẫn có thể để lại quyền đã cấp ở X. Để thu hồi quyền, dùng mục [Connected Apps của X](https://x.com/settings/connected_apps). [Vòng đời access token](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)

Luồng dành cho máy và thư mục do chủ tài khoản kiểm soát. Kiểm tra metadata và ACL qua đường dẫn không loại trừ mọi tình huống tiến trình khác hoán đổi thư mục đồng thời. Việc thêm mã nguồn này chưa xác minh callback, ACL thực tế, OAuth hoặc tài khoản X trong môi trường live.
