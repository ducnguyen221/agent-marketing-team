# Thiết lập OAuth chỉ đọc cho LinkedIn cá nhân

Chủ tài khoản tự chạy công cụ từ terminal tương tác. Công cụ yêu cầu hai quyền `openid profile` và dùng `GET /v2/userinfo` để đối chiếu thành viên. Kết quả là một profile cho bộ đọc thực nghiệm. Luồng này không có bước kiểm quyền trên LinkedIn Page, tạo bài, đăng hoặc lập lịch.

## Điều kiện thực hiện luồng chuẩn

1. Trong LinkedIn Developer Portal, dùng ứng dụng do bạn quản lý đã có sản phẩm **Sign In with LinkedIn using OpenID Connect**. Dùng một ứng dụng riêng cho mục đích chỉ đọc. Khi phạm vi quyền thay đổi, LinkedIn có thể vô hiệu hóa access token đã cấp trước đó. [Tài liệu LinkedIn OIDC](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2) · [Vòng đời access token](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow#access-token-scopes-and-lifetime)
2. Trong **Auth → Authorized redirect URLs**, đăng ký chính xác `https://127.0.0.1:8765/linkedin-oauth-callback`. Luồng chuẩn yêu cầu HTTPS và dùng đúng URI đã đăng ký cho cả yêu cầu cấp mã lẫn đổi mã. Cổng 8765 phải khả dụng trên máy chạy. Đợt phát triển này chưa xác minh Developer Portal chấp nhận URI loopback đó cho app của bạn. Nếu portal từ chối, dừng thiết lập. [Tài liệu LinkedIn Authorization Code](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow)
3. Cần chứng chỉ TLS cục bộ có SAN kiểu IP cho `127.0.0.1`, còn hiệu lực, cùng khóa riêng PEM tương ứng do bạn quản lý. Trình duyệt mặc định phải tin cậy chứng chỉ trên máy đó. Khi trình duyệt cảnh báo chứng chỉ, dừng thiết lập.
4. Chuẩn bị một alias cục bộ trong `~/.secret/<profile>/` với quyền riêng tư. Trên Windows, kiểm tra **Properties → Security → Advanced** của kho, thư mục profile và từng file, bao gồm quyền kế thừa. Script dùng Windows PowerShell `Get-Acl` để yêu cầu người dùng hiện tại sở hữu các mục này và chỉ chấp nhận quyền cấp cho chính người đó, SYSTEM và nhóm Administrators. Khi bộ kiểm không chạy được hoặc quyền nằm ngoài tập này, công cụ dừng. File kết quả dùng ACL kế thừa của thư mục profile. Trên POSIX, đặt thư mục kho và profile `0700`, các file đầu vào `0600`. Dùng ổ vật lý trên máy, tránh cây đồng bộ, symlink, junction và placeholder. Chạy trên máy và thư mục bạn kiểm soát. Kiểm metadata theo đường dẫn có thể không phát hiện mọi lần hoán đổi file trong lúc hệ điều hành mở đường dẫn.

## Chuẩn bị file và cấp quyền theo luồng chuẩn

Trong đúng thư mục profile, chủ tài khoản chuẩn bị ba file. Mở và nhập thông tin nhạy cảm bằng trình soạn thảo cục bộ trong kho. Tránh bản sao lưu hoặc lịch sử chỉnh sửa nằm ngoài kho.

Không đặt home hoặc kho bí mật trên ổ mạng ánh xạ bằng ký tự ổ đĩa. Bộ kiểm tra hiện chưa tự nhận biết trường hợp ổ mạng ánh xạ đó.

| File | Nội dung |
|---|---|
| `linkedin-oauth-client.json` | Một đối tượng JSON với đúng ba trường chuỗi `client_id`, `client_secret` và `person_urn`. Dùng ID và secret của ứng dụng từ LinkedIn Developer Portal. |
| `linkedin-callback-cert.pem` | Chứng chỉ TLS cho callback cục bộ, kèm chuỗi chứng chỉ cần thiết. |
| `linkedin-callback-key.pem` | Khóa riêng PEM tương ứng, đọc được từ file bảo vệ mà không cần câu hỏi mật khẩu. |

Trường `person_urn` có dạng `urn:li:person:<sub>` theo schema của bộ đọc. Lấy `sub` kỳ vọng từ nguồn UserInfo đã được bạn xác nhận độc lập cho **cùng ứng dụng**. LinkedIn tài liệu hóa subject dạng pairwise. Nếu chưa có giá trị đã xác nhận, dừng trước khi chạy luồng này. Tránh suy ID từ tên, email, đường dẫn hồ sơ hoặc ứng dụng khác. [Metadata và UserInfo của LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2#validating-id-tokens)

Từ gốc plugin, thay `your-profile` bằng alias đã chuẩn bị:

```powershell
python -m scripts.social.channels.linkedin.oauth_setup --authorize-readonly --profile your-profile
```

1. Gõ `authorize` sau khi xác nhận URL đã đăng ký và quyền truy cập thư mục là riêng tư. Công cụ mở trình duyệt mặc định và chỉ lắng nghe trên `127.0.0.1` trong tối đa ba phút.
2. Kiểm tra tên ứng dụng, tài khoản và quyền trên trang LinkedIn rồi tự quyết định cấp quyền. Giữ mã OAuth và URL callback trong trình duyệt. Công cụ kiểm tra `state`, đổi mã qua HTTPS tới LinkedIn và dừng nếu quyền trả về sai hoặc UserInfo chưa khớp.
3. Gõ `save` sau khi terminal báo thành viên khớp. File `linkedin-userinfo.json` chỉ được tạo mới theo schema `linkedin-userinfo/1`. Nếu đã có file, luồng từ chối ghi đè. Công cụ chỉ lưu access token và các trường hiện có của profile. ID token, refresh token và dữ liệu hồ sơ do UserInfo trả về không được lưu. Nếu bạn hủy lưu sau khi đã đồng ý trong trình duyệt, quyền vừa cấp vẫn tồn tại trên LinkedIn cho đến khi được thu hồi hoặc hết hiệu lực.

## Luồng native PKCE

Chỉ chọn `--mode native-pkce` sau khi LinkedIn xác nhận đã bật PKCE cho ứng dụng của bạn. Ứng dụng vẫn cần sản phẩm **Sign In with LinkedIn using OpenID Connect**. Áp dụng cùng điều kiện thư mục riêng tư và đối chiếu `sub` kỳ vọng của chính ứng dụng đó như trên. [Tài liệu LinkedIn native PKCE](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow-native)

Tạo `linkedin-native-client.json` trong thư mục profile, với đúng hai trường chuỗi `client_id` và `person_urn`. `client_id` là mã công khai của ứng dụng. Chế độ này dùng PKCE S256 và không cần client secret, chứng chỉ hoặc khóa riêng. Công cụ chọn cổng thực tế khi bắt đầu lắng nghe trên `127.0.0.1` và gửi cùng một địa chỉ `http://127.0.0.1:<port>/linkedin-oauth-callback` cho cả hai yêu cầu OAuth. Trang duyệt quyền và yêu cầu đổi mã đi qua HTTPS tới LinkedIn.

```powershell
python -m scripts.social.channels.linkedin.oauth_setup --authorize-readonly --profile your-profile --mode native-pkce
```

Chủ tài khoản gõ `authorize` để mở trình duyệt mặc định, tự quyết định cấp quyền trên LinkedIn và chỉ gõ `save` khi terminal báo thành viên khớp. Cả hai chế độ yêu cầu phản hồi đổi mã xác nhận đúng `openid profile` và từ chối ghi đè file profile đã tồn tại. Tài liệu native PKCE mô tả phản hồi có thể không có trường `scope`. Khi LinkedIn không trả trường này, công cụ dừng vì chưa xác nhận được phạm vi quyền và không tạo profile. Khả năng chạy native PKCE với ứng dụng cụ thể vẫn cần chủ tài khoản xác nhận.

## Kiểm tra sau khi cấp quyền

Chủ tài khoản có thể chạy phép kiểm đọc dưới đây sau khi lưu profile từ một trong hai luồng. Lệnh gọi UserInfo thật và chỉ in kết quả đối chiếu.

```powershell
python -m scripts.social.channels.linkedin.readonly_auth --check-readonly --profile your-profile
```

## Giới hạn và thu hồi

- Khi kiểm không khớp, timeout, thiếu quyền, chứng chỉ bị từ chối hoặc sai URI, sửa điều kiện tương ứng trước khi bắt đầu phiên mới. Dùng alias mới nếu cần tạo profile khác. Khi không dùng nữa, thu hồi quyền ứng dụng qua LinkedIn và xóa profile cục bộ bằng công cụ quản trị kho của bạn. Hai thao tác xử lý hai nơi lưu quyền riêng.
- Phiên phát triển chỉ đối chiếu mã nguồn và tài liệu chính thức. Chưa chạy CLI, callback, phép kiểm, cấp OAuth hoặc đọc kho bí mật.
