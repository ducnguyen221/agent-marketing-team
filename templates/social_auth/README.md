# Mẫu chuẩn bị xác thực social

Chín file `<nền-tảng>.example.json` cạnh tài liệu này là **mẫu trống** cho Facebook, Instagram, YouTube, LinkedIn, TikTok, Threads, X, Discord và Telegram. Chúng giúp chủ tài khoản biết những thông tin cần chuẩn bị cho kết nối trực tiếp. Giá trị `null` nghĩa là chưa có dữ liệu; không phải token hay quyền đã được cấp. Các mẫu `*-userinfo.example.json` có định dạng riêng cho phép kiểm chỉ đọc thử nghiệm; dùng trình tạo riêng bên dưới.

**Chín mẫu tổng quát V2 chưa phải cấu hình chạy.** Các reader LinkedIn, TikTok, X, Discord, YouTube, Facebook Page, Instagram Facebook Login, Threads và Telegram publisher chỉ nhận schema riêng tương ứng và chưa kiểm tài khoản thật. Lệnh `--check-readonly` dùng token đã cấp. Các công cụ `oauth_setup` cho LinkedIn, X và YouTube có luồng cấp quyền riêng. Không đổi tên trực tiếp mẫu tổng quát thành file cấu hình V1 đang chạy, không khai biến trỏ tới mẫu, và không gửi thông tin bí mật trong chat, log hoặc repo.

## Tạo bản mẫu trong kho bí mật

Chủ máy có thể chạy từ gốc plugin:

```powershell
python -m scripts.social.init_auth_templates --create-examples
python -m scripts.social.init_readonly_auth_templates --create-examples
```

Hai lệnh chỉ tạo các file tên cố định dưới `~/.secret/_social-auth-templates/`: lệnh đầu tạo chín mẫu tổng quát, lệnh sau tạo chín mẫu cho reader chỉ đọc. Chúng không tự tạo kho gốc, không yêu cầu hay đọc token, không kết nối nền tảng, không bật cấu hình. Nếu mẫu cùng tên đã tồn tại, lệnh bỏ qua mà không đọc hoặc ghi đè và báo `existing_unverified`: không khẳng định file đó còn nguyên vẹn. Kết quả liệt kê tên mẫu đã tạo, đã có, hoặc lỗi; nếu có lỗi thì mã thoát là 2. Khi lỗi giữa lúc ghi, file mẫu có thể còn dở và người sở hữu cần kiểm tra thủ công trước khi xử lý. Lệnh từ chối thư mục gốc hoặc thư mục mẫu là symlink/junction. Việc kiểm liên kết trước khi tạo không loại trừ hoàn toàn rủi ro thay thư mục đồng thời; không chạy khi có tiến trình không tin cậy đang sửa kho. Trên Windows cần dùng quyền bảo vệ kho hiện có; lệnh không thay ACL.

Có thể xem các mẫu trong repo mà không chạy lệnh:

| File mẫu | Chuẩn bị ban đầu | Phân biệt quan trọng |
|---|---|---|
| [facebook.example.json](facebook.example.json) | App, Page ID và Page token | V1 đang đọc `page_id` và `page_token` ở **gốc JSON thật** qua `FB_CONFIG`; mẫu lồng `fields` không phải file V1. Group và Page là hai đích khác nhau. |
| [instagram.example.json](instagram.example.json) | App, loại login, tài khoản professional và token | Preview offline hiện mô hình hóa Facebook Login. Instagram Login và Facebook Login có token/quyền khác nhau; xem [tài liệu Meta](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/). |
| [youtube.example.json](youtube.example.json) | Đường dẫn client JSON Google cấp, token OAuth và channel ID | V1 dùng `YT_CLIENT_SECRET` và `YT_TOKEN_PATH`; token thật do luồng OAuth Google tạo. **Không tạo sẵn file token rỗng tại đường runtime**, vì V1 sẽ cố đọc nó như token thật. [Google](https://developers.google.com/youtube/data/guides/authentication) |
| [linkedin.example.json](linkedin.example.json) | Client, callback, quyền và author URN | Chọn person hoặc organization; quyền yêu cầu và quyền đã được xác minh là hai thông tin khác nhau. Refresh token chỉ có khi grant tương ứng hỗ trợ. [LinkedIn](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow) |
| [tiktok.example.json](tiktok.example.json) | Client key/secret, callback, token và open ID | `posting_method` phải phân biệt Direct Post với chuyển vào inbox; không mặc định bài đã công khai. [TikTok](https://developers.tiktok.com/docs/en/login-kit-web) |
| [threads.example.json](threads.example.json) | App Threads, callback, token và user ID | ID và quyền Threads được kiểm riêng, không suy từ Page hay Instagram. [Meta](https://developers.facebook.com/docs/threads/) |
| [x.example.json](x.example.json) | User ID, kiểu OAuth và thông tin tương ứng | Mẫu hiện chỉ phác thảo OAuth 2 user context/PKCE; OAuth 1.0a cần hợp đồng và các trường riêng, không dùng mẫu này thay thế. [X](https://docs.x.com/fundamentals/authentication/overview) |
| [discord.example.json](discord.example.json) | Application, bot token, guild và channel | Bot token khác user OAuth token; cần kiểm quyền bot tại đúng channel. [Discord](https://docs.discord.com/developers/quick-start/getting-started) |
| [telegram.example.json](telegram.example.json) | Mục đích bot, token và đích | Bot nhận duyệt và bot đăng channel có thể là hai vai trò riêng. V1 dùng `bot_token` và `chats.<alias>.chat_id` trong file thật qua `TG_CONFIG`; mẫu lồng `fields` không phải file V1. [Telegram](https://core.telegram.org/bots/api) |

## Khi thực sự kết nối

1. Chọn một nền tảng, loại tài khoản và đích. Chủ tài khoản tạo app và quyền theo tài liệu chính thức. Nếu dùng công cụ OAuth của LinkedIn, X hoặc YouTube để cấp quyền mới, để file UserInfo đầu ra chưa tồn tại. Nếu đã có token đúng loại, sao chép mẫu UserInfo và tự điền trong kho. Chi tiết từng đường chuẩn bị nằm trong [SOCIAL_AUTH_TEST.md](../../knowledge/toolchains/SOCIAL_AUTH_TEST.md).
2. Tách file theo **tài khoản**, không nhân bản một token cho mỗi chiến dịch. Bí mật thật chỉ nằm trong kho máy; biến môi trường dùng làm con trỏ đường dẫn, không chứa giá trị token.
3. Dùng đúng reader và schema thực tế của kênh. Facebook/YouTube/Telegram V1 tiếp tục theo [SECRETS.md](../../knowledge/toolchains/SECRETS.md); các reader chỉ đọc của chín kênh được mô tả trong [SOCIAL_AUTH_TEST.md](../../knowledge/toolchains/SOCIAL_AUTH_TEST.md). Chưa có bằng chứng kiểm tài khoản thật.
4. Kiểm riêng quyền đọc và đúng tài khoản khi adapter đã có. Không upload, tạo lịch, đăng bài hay sửa cổng duyệt trong phạm vi thử chưa live.

## Mẫu đầu vào cho công cụ OAuth LinkedIn

Hai mẫu đầu vào dưới đây có sẵn trong repo. Hai lệnh tạo mẫu ở trên chỉ sao chép các bộ mẫu tổng quát và UserInfo.

| Luồng | Mẫu đầu vào | Tên trong thư mục profile |
|---|---|---|
| Chuẩn, callback HTTPS | [linkedin-oauth-client.example.json](linkedin-oauth-client.example.json) | `linkedin-oauth-client.json` |
| Native PKCE, khi ứng dụng được LinkedIn bật chế độ này | [linkedin-native-client.example.json](linkedin-native-client.example.json) | `linkedin-native-client.json` |

Chủ tài khoản thay `null` bằng chuỗi trong bản sao cục bộ ở kho bí mật. Luồng chuẩn còn cần chứng chỉ và khóa riêng cho callback. Xem điều kiện của từng luồng trước khi chuẩn bị file. [SOCIAL_OAUTH_LINKEDIN.md](../../knowledge/toolchains/SOCIAL_OAUTH_LINKEDIN.md)
