# Chuẩn bị kết nối social để kiểm thử, chưa đăng live

Tài liệu chuẩn bị cấu hình; chưa thiết lập tài khoản, chưa xác minh quyền và không cho phép đăng. Bằng chứng hiện có là kiểm tra offline với dữ liệu giả. Các lệnh `--check-readonly` thực hiện GET thật khi chủ tài khoản chủ động cho phép; không chạy khi chưa cấu hình thông tin xác thực. Xác thực thành công cũng không đồng nghĩa được phép phát hoặc lịch đã được tạo.

Bộ mẫu trống cho chín nền tảng và lệnh tạo bản ví dụ trong kho bí mật: [templates/social_auth/README.md](../../templates/social_auth/README.md). Mẫu không phải cấu hình đang chạy và không tự tạo token.

## Tạo file cấu hình thử từ mẫu

Chọn một cách chuẩn bị profile. Nếu đã có access token đúng loại hoặc dùng bot token, sao chép mẫu và điền theo các bước dưới đây. Nếu cần cấp access token mới cho LinkedIn, X hoặc YouTube, xem hướng dẫn cấp OAuth ở mục của kênh. Các công cụ cấp quyền này tự tạo file UserInfo sau khi chủ tài khoản xác nhận lưu, nên hãy chuẩn bị thư mục profile riêng và để tên file đầu ra chưa tồn tại. Riêng TikTok có mã tích hợp phía máy chủ, cần backend do chủ ứng dụng quản lý để đổi mã lấy token.

1. Chọn một kênh trong bảng bên dưới. Cột **Mẫu trống** mở đúng JSON cho lệnh kiểm của kênh đó. Có thể dùng trực tiếp mẫu trong repo. Nếu muốn có bản mẫu riêng trong kho, chủ tài khoản chạy lệnh sau từ gốc plugin sau khi đã có kho `~/.secret/` được bảo vệ.

   ```powershell
   python -m scripts.social.init_readonly_auth_templates --create-examples
   ```

   Lệnh chỉ tạo các mẫu trống dưới `~/.secret/_social-auth-templates/`. Kết quả `existing_unverified` nghĩa là tên file đã có và được bỏ qua. Khi cần một mẫu chắc chắn trống, dùng bản trong repo.

2. Trong kho bí mật cục bộ, chủ tài khoản tạo hoặc chọn thư mục `~/.secret/<profile>/` có quyền truy cập giới hạn. Chỉ dùng thư mục vật lý trên máy, tránh thư mục đồng bộ, placeholder, symlink và junction.
3. Sao chép **mẫu trống** đã chọn vào thư mục đó. Đặt tên chính xác theo cột **File trong profile**. Ví dụ, với profile `demo-team_01`, sao chép mẫu YouTube thành `~/.secret/demo-team_01/youtube-channel-userinfo.json`. Nếu file đích đã có, giữ nguyên và chọn tên profile mới để chuẩn bị một bản thử riêng.
4. Chủ tài khoản mở bản sao bằng trình soạn thảo cục bộ. Điền các trường theo hướng dẫn riêng của kênh bên dưới. Lưu JSON dưới dạng UTF-8 không BOM, tối đa 16 KiB. Thay `null` bằng chuỗi có dấu ngoặc kép, kể cả ID dạng số. Giữ đúng các khóa trong mẫu, mỗi khóa xuất hiện một lần. Dán token thô vào trường tương ứng, không kèm tiền tố `Bearer ` hay `Bot `. Không điền vào mẫu trong repo, không truyền credential qua đối số lệnh và không gửi file đã điền qua chat.

## Trước khi bắt đầu

1. Chọn **một** nền tảng, tài khoản và đích thử. Dùng môi trường thử hoặc quyền chỉ đọc theo tài liệu của nền tảng khi có; không dùng trạm chiến dịch thật cho fixture. Hệ thống đang xây là code riêng của agent-marketing-team; Postiz là nguồn tham khảo, không phải dịch vụ bắt buộc để kết nối.
2. Với kênh dùng ứng dụng, chủ tài khoản chuẩn bị ứng dụng thử trên cổng lập trình viên và chọn đúng sản phẩm API. Với Telegram, chủ tài khoản dùng BotFather để chuẩn bị bot thử do mình quản lý. Chỉ cấp quyền OAuth khi chủ tài khoản đã xác định và đồng ý với đích cùng phạm vi quyền cụ thể.
3. Chủ tài khoản tự lưu bí mật tại kho máy `~/.secret/<tên-tài-khoản>/` theo công cụ quản trị được phép; không dán client secret, access token, refresh token hoặc mã xác nhận vào chat, tài liệu, repo hay log. Không tạo hoặc sao chép secret trong ví dụ. Không ghi bí mật vào file cấu hình tracked.
4. Với kênh dùng OAuth, chủ tài khoản cấu hình callback nếu nhà cung cấp yêu cầu và cấp đúng quyền đọc. Lệnh `--check-readonly` đọc token đã cấp từ file riêng của profile và thực hiện phép đối chiếu danh tính. Khi cần đăng nhập, xử lý callback hoặc đổi mã, làm theo hướng dẫn cấp OAuth riêng của kênh. Reader cần token còn hiệu lực. Mỗi lần chỉ chạy lệnh cho kênh đã chọn.
5. Chủ tài khoản tự kiểm tra app, URL callback, tài khoản và phạm vi quyền trước khi đồng ý. Không tự động vượt cảnh báo, CAPTCHA hay cấp thêm quyền. Không bật scheduler hoặc tạo bài, kể cả bài riêng tư/draft, trong đợt kiểm không đăng live này.
6. Ghi kết quả dạng không chứa bí mật: ngày, phiên bản API, nền tảng, loại đích, môi trường, quyền đã được cấp theo tên, kết quả kết nối và lỗi đã loại dữ liệu nhạy cảm. Không sao chép URL callback có tham số hoặc log xác thực.

## Chuẩn bị theo nền tảng

| Kênh | Chuẩn bị kiểm thử và giới hạn |
|---|---|
| LinkedIn | Chuẩn bị ứng dụng có sản phẩm [Sign In with LinkedIn using OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2), cấp quyền đọc UserInfo phù hợp rồi đối chiếu tài khoản cá nhân trong cùng ứng dụng. Phép kiểm cho organization hoặc LinkedIn Page cần một luồng riêng trong tương lai. |
| Facebook / Instagram | Dùng ứng dụng thử của Meta, thêm tài khoản có vai trò phù hợp; theo [Meta App Review](https://developers.facebook.com/docs/resp-plat-initiatives/app-review/introduction). Kiểm riêng Page, Instagram và Group; kết nối Page không chứng minh có thể đăng Group. |
| YouTube | Tạo dự án Google Cloud, bật YouTube Data API, cấu hình OAuth consent và client phù hợp; xem [hướng dẫn xác thực](https://developers.google.com/youtube/data/guides/authentication). Chọn đúng kênh/Brand Account; chưa upload, kể cả video private. |
| TikTok | Tạo ứng dụng và [sandbox](https://developers.tiktok.com/docs/en/add-a-sandbox), thêm tài khoản thử theo hướng dẫn chính thức. Sandbox có giới hạn với Content Posting API cho video công khai; không giả định sandbox hỗ trợ mọi quyền hay thao tác Duet/Stitch. Không gửi video vào inbox hay Direct Post trong lượt này. |
| Threads / X / Discord | Theo tài liệu chính thức và cổng lập trình viên tương ứng; kiểm loại tài khoản, quyền, mức truy cập, quota/chi phí trước khi kết nối. Chưa chứng minh quyền và không thử gửi thật. |
| Telegram | Chủ tài khoản chọn bot thử do mình quản lý qua BotFather, lấy bot token và xác lập bot ID trước lần kiểm. Dùng mục `getMe` của [Telegram Bot API](https://core.telegram.org/bots/api#getme) để hiểu phép kiểm danh tính bot. Việc này không cần chọn chat hay cấp quyền gửi. |

## File và trường cấu hình cho phép kiểm chỉ đọc

Chủ tài khoản chọn tên profile 1–48 ký tự. Dùng chữ thường ASCII và chữ số ở đầu/cuối, có thể dùng thêm `-` và `_` ở giữa. Tránh tên thiết bị dành riêng của Windows. Dùng mẫu cùng tên có hậu tố `.example.json` trong [`templates/social_auth/`](../../templates/social_auth/), rồi tự lưu file chạy theo bảng dưới đây trong `~/.secret/<profile>/`. Điền các trường đang để `null` bằng chuỗi và giữ nguyên các trường cố định trong mẫu như `schema`, `provider`, `token_kind`, `login_product` hoặc `purpose` nếu có. Các cột ID kỳ vọng phải lấy từ nguồn độc lập trước lần kiểm.

| Kênh | Mẫu trống | File trong profile | Tên trường cần điền | Phép đọc thực tế |
|---|---|---|---|---|
| LinkedIn | [Mở JSON](../../templates/social_auth/linkedin-userinfo.example.json) | `linkedin-userinfo.json` | `client_id`, `person_urn`, `access_token` | `GET api.linkedin.com/v2/userinfo` |
| TikTok | [Mở JSON](../../templates/social_auth/tiktok-userinfo.example.json) | `tiktok-userinfo.json` | `client_key`, `expected_open_id`, `access_token` | `GET open.tiktokapis.com/v2/user/info/?fields=open_id` |
| X | [Mở JSON](../../templates/social_auth/x-userinfo.example.json) | `x-userinfo.json` | `client_id`, `expected_user_id`, `access_token` | `GET api.x.com/2/users/me` |
| Discord | [Mở JSON](../../templates/social_auth/discord-bot-userinfo.example.json) | `discord-bot-userinfo.json` | `application_id`, `expected_bot_id`, `bot_token` | `GET discord.com/api/v10/users/@me` |
| YouTube | [Mở JSON](../../templates/social_auth/youtube-channel-userinfo.example.json) | `youtube-channel-userinfo.json` | `client_id`, `expected_channel_id`, `access_token` | `GET www.googleapis.com/youtube/v3/channels` với `mine=true` |
| Facebook Page | [Mở JSON](../../templates/social_auth/facebook-page-userinfo.example.json) | `facebook-page-userinfo.json` | `app_id`, `expected_page_id`, `api_version`, `access_token` | `GET graph.facebook.com/<api_version>/me?fields=id` |
| Instagram Facebook Login | [Mở JSON](../../templates/social_auth/instagram-facebook-userinfo.example.json) | `instagram-facebook-userinfo.json` | `app_id`, `expected_page_id`, `expected_instagram_id`, `api_version`, `access_token` | `GET graph.facebook.com/<api_version>/<expected_page_id>` với `fields=id,instagram_business_account{id}` |
| Threads | [Mở JSON](../../templates/social_auth/threads-userinfo.example.json) | `threads-userinfo.json` | `app_id`, `expected_user_id`, `api_version`, `access_token` | `GET graph.threads.com/<api_version>/me?fields=id` |
| Telegram | [Mở JSON](../../templates/social_auth/telegram-publish-bot-userinfo.example.json) | `telegram-publish-bot-userinfo.json` | `expected_bot_id`, `bot_token` | `GET api.telegram.org` gọi `getMe`, token nằm trong đường dẫn |

Với Facebook Page, Instagram Facebook Login và Threads, điền `api_version` theo dạng `v<major>.<minor>`, chọn phiên bản hỗ trợ ứng dụng và endpoint đang dùng. Facebook Page cần Page access token. Instagram Facebook Login cần Facebook User access token. Threads cần Threads User access token. Giữ `token_kind` hoặc `login_product` theo đúng mẫu của từng kênh.

## Lấy ID kỳ vọng trước lần kiểm

Dùng hồ sơ quản trị của chính tài khoản thử hoặc giá trị đã được chủ tài khoản xác nhận từ trước. Một phép kiểm chỉ có ý nghĩa nếu bạn biết mình định kết nối tài khoản nào trước khi chạy. Nếu nguồn độc lập chưa có ID, để trường đó trống và hoãn lần kiểm. Chép ID từ chính phản hồi đang được kiểm vào trường kỳ vọng sẽ chỉ kiểm sự trùng lặp.

| Kênh | Chỗ đối chiếu ID |
|---|---|
| LinkedIn | Lấy ID thành viên đã được xác nhận trong hồ sơ xác thực của **cùng app**, rồi điền Person URN dạng `urn:li:person:<ID>`. Tên trên hồ sơ và URL profile không thay được OIDC `sub`. [LinkedIn OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2) |
| TikTok | Lấy `open_id` đã ghi nhận khi chủ tài khoản thử cấp quyền cho **cùng app**. `open_id` được phân phạm vi theo ứng dụng, nên tên người dùng hoặc `open_id` từ ứng dụng khác không dùng để đối chiếu. [TikTok Get User Info](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info) |
| X | Lấy ID người dùng dạng số từ hồ sơ tích hợp đã xác thực hoặc bản ghi quản trị đã được chủ tài khoản đối chiếu với đúng tài khoản thử. Dùng ID ổn định thay cho `@handle`. [X Get My User](https://docs.x.com/x-api/users/get-my-user) |
| Discord | Đối chiếu bot thuộc ứng dụng đã chọn ở Developer Portal với ID của **bot user** trong hồ sơ quản trị. Giữ `application_id` và `expected_bot_id` ở đúng trường, không dùng guild ID hay channel ID. [Discord Developer Portal](https://discord.com/developers/applications) |
| YouTube | Chủ kênh lấy ID của kênh đang quản trị từ phần cài đặt nâng cao của YouTube. Nếu có nhiều kênh, chuyển đến đúng kênh thử trước khi lấy ID. [Tìm ID người dùng và ID kênh YouTube](https://support.google.com/youtube/answer/3250431) |
| Facebook Page | Lấy Page ID dạng số trong thông tin quản trị của đúng Page thử. Kiểm tên Page và tài khoản quản lý trước khi ghi ID. [Meta Graph API](https://developers.facebook.com/docs/graph-api/overview#me) |
| Instagram Facebook Login | Từ hồ sơ quản trị Meta của đích thử, lấy cả Page ID lẫn ID của tài khoản Instagram professional liên kết với Page trong luồng Facebook Login. Nếu chỉ có tên Instagram, chưa đủ dữ liệu để chạy phép kiểm liên kết. [Meta IG User](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/) |
| Threads | Lấy Threads user ID đã được xác nhận khi thiết lập ứng dụng thử, trong đúng ngữ cảnh app. Không dùng ID Instagram hay Page dù các tài khoản có liên hệ. [Threads API](https://developers.facebook.com/docs/threads/) |
| Telegram | Lấy ID số của **bot user** từ hồ sơ quản trị của bot thử đã xác nhận; đối chiếu đúng bot với tên do BotFather quản lý. Bot username và chat ID là các giá trị riêng. [Telegram Bot API](https://core.telegram.org/bots/api#getme) |

Các bước và candidate LinkedIn trực tiếp bằng dữ liệu giả: [LINKEDIN_DIRECT_PREVIEW.md](LINKEDIN_DIRECT_PREVIEW.md). Reader và lệnh UserInfo thử nghiệm đã được kiểm bằng file tạm cùng transport giả; **chưa kiểm với credential thật hoặc chứng minh liên kết token, ứng dụng và tài khoản**.

LinkedIn mô tả [UserInfo và OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2): app cần sản phẩm và phạm vi phù hợp. Phép đối chiếu hiện chỉ xét `sub` của tài khoản cá nhân với Person URN kỳ vọng do bên gọi cung cấp; giá trị kỳ vọng phải được xác lập độc lập trong cùng ngữ cảnh ứng dụng. `match` không chứng minh ràng buộc ứng dụng, danh tính pháp lý, quyền đăng hay quyền tổ chức; `401/403` không đủ để kết luận token đã bị thu hồi. Kết quả luôn ghi `profile_binding_verified=false`, `app_binding_verified=false`, `publish_authorized=false`; tổ chức chưa được hỗ trợ.

## LinkedIn: chuẩn bị cho lần kiểm chỉ đọc sau này

Hướng dẫn cấp OAuth chỉ đọc cho tài khoản cá nhân nêu điều kiện callback của luồng chuẩn và Native PKCE. Chọn mẫu đầu vào tương ứng và để `linkedin-userinfo.json` cho công cụ tạo khi lưu. Chưa xác minh luồng này trên tài khoản thật. [Hướng dẫn OAuth LinkedIn](SOCIAL_OAUTH_LINKEDIN.md) · [Mẫu đầu vào](../../templates/social_auth/README.md#mẫu-đầu-vào-cho-công-cụ-oauth-linkedin)

1. Chủ tài khoản chọn tên profile dài 1–48 ký tự; ký tự đầu và cuối phải là chữ thường ASCII `a–z` hoặc số `0–9`, phần giữa có thể thêm `-` và `_`. Ví dụ hợp lệ: `demo-team_01`. Không dùng tên thiết bị dành riêng của Windows. Tên này chỉ là nhãn, không xác thực tài khoản. Tự tạo thư mục `~/.secret/<profile>/` trong kho được bảo vệ.
2. Nếu đã có OAuth **access token**, tự dùng mẫu [linkedin-userinfo.example.json](../../templates/social_auth/linkedin-userinfo.example.json) để tạo `~/.secret/<profile>/linkedin-userinfo.json`. Trong file tại kho bí mật, tự điền `client_id`, `person_urn` đã biết độc lập trong cùng app, và access token tương ứng. Giữ schema và provider. ID token dùng cho mục đích khác. Nếu chọn công cụ OAuth ở trên, dùng file UserInfo mà công cụ đã lưu.
3. Khi chủ tài khoản quyết định kiểm kết nối chỉ đọc, từ thư mục plugin chạy lệnh dưới đây, thay `ten-profile` bằng tên đã chọn. Lệnh thực sự gọi LinkedIn UserInfo một lần, không tạo nội dung hay lịch; **lệnh chưa được chạy với tài khoản thật trong lượt phát triển này**.

```powershell
python -m scripts.social.channels.linkedin.readonly_auth --check-readonly --profile ten-profile
```

4. Kết quả `config_valid` chỉ phản ánh định dạng file, `identity=match` chỉ là subject khớp giá trị trong chính file đó. Sao chép nguyên profile khác có thể cho `match` sai người; phải tự đối chiếu giá trị kỳ vọng với nguồn độc lập. Không kết luận quyền đăng hoặc quyền tổ chức từ kết quả. `unknown` có thể do quyền, mạng hoặc phản hồi; không tự xin thêm quyền.
5. Reader kiểm reparse, hardlink và danh tính file đã mở, nhưng không loại trừ mọi trường hợp thay thư mục hoặc nội dung đồng thời. Chỉ dùng kho có quyền bảo vệ phù hợp và không chạy khi tiến trình không tin cậy có thể sửa kho. Bảo vệ root cố định áp dụng cho CLI; hàm Python nhận `root` đòi hỏi caller tự cung cấp root tin cậy. Chưa có kiểm thử trên tài khoản thật hoặc bằng chứng luồng cấp OAuth gắn token với app.

## TikTok: chuẩn bị cho lần kiểm chỉ đọc sau này

Điều kiện Login Kit Desktop được mô tả tại [SOCIAL_OAUTH_TIKTOK.md](SOCIAL_OAUTH_TIKTOK.md). Repo có [mã tích hợp đổi mã phía máy chủ](SOCIAL_OAUTH_TIKTOK_SERVER.md), cần dịch vụ do chủ ứng dụng triển khai. Để chuẩn bị file chạy reader, dùng user access token được cấp từ backend tin cậy của ứng dụng.

1. Chủ tài khoản tạo ứng dụng và tài khoản thử theo tài liệu TikTok, chọn Login Kit và quyền đọc `user.info.basic` phù hợp, tự thực hiện luồng cấp quyền. `open_id` gắn với ứng dụng, nên phải lấy giá trị kỳ vọng từ nguồn độc lập của **cùng app**; không tự coi ID vừa nhận là kỳ vọng. Tài liệu TikTok Minis có nhắc scope khác, không mặc định thay thế scope cho mọi ứng dụng. [Get User Info](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info) · [Scope migration](https://developers.tiktok.com/bulletin/user-info-scope-migration)
2. Chủ tài khoản chọn tên profile theo cùng quy tắc 1–48 ký tự ở mục LinkedIn và tự tạo `~/.secret/<profile>/tiktok-userinfo.json` theo mẫu trống [tiktok-userinfo.example.json](../../templates/social_auth/tiktok-userinfo.example.json). Điền `client_key`, `expected_open_id` và user access token vào file trong kho bí mật; không điền vào repo hoặc dán vào chat. Mẫu tổng quát `tiktok.example.json` có schema khác và không phải file chạy.
3. Khi chủ tài khoản chủ động chọn kiểm chỉ đọc, chạy lệnh dưới đây từ gốc plugin. Lệnh gọi một GET User Info chỉ yêu cầu `open_id`; không upload, tạo nội dung, refresh token hay đăng. **Lệnh chưa được kiểm với tài khoản thật trong lượt này.**

```powershell
python -m scripts.social.channels.tiktok.readonly_auth --check-readonly --profile ten-profile
```

4. `identity=match` chỉ là ID trả về khớp ID trong file. Sao chép cả profile người khác, hoặc đặt token provider khác trong file tự khai TikTok, không được bộ đọc phát hiện đáng tin cậy. `profile_binding_verified`, `app_binding_verified` và `publish_authorized` luôn `false`. Không suy token hết hạn từ `unknown`/401; cũng không suy quyền `video.upload` hoặc `video.publish` từ phép đọc.
5. Chỉ sử dụng kho được bảo vệ khỏi sửa đồng thời bởi tiến trình không tin cậy. Reader kiểm reparse, hardlink và danh tính file đã mở nhưng không loại trừ mọi rủi ro thay thư mục/file đồng thời. Root cố định chỉ áp dụng cho CLI; caller Python phải tự bảo đảm root tin cậy. Chưa có bằng chứng kiểm tài khoản thật hoặc xác thực token thuộc client key được khai.

## X: chuẩn bị cho lần kiểm chỉ đọc sau này

Code OAuth chỉ đọc cho Native App và các điều kiện callback được mô tả tại [SOCIAL_OAUTH_X.md](SOCIAL_OAUTH_X.md). Luồng chưa được xác minh trên tài khoản thật.

1. Theo [X Get My User](https://docs.x.com/x-api/users/get-my-user) và [bảng scope](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping), chủ tài khoản tự tạo app, kiểm mức truy cập và quyền `users.read`, `tweet.read`; không cần cấp `tweet.write` cho phép kiểm này. Chi phí/quota và khả năng truy cập phụ thuộc tài khoản, cần kiểm trước khi dùng.
2. Nếu đã có OAuth 2 user access token, tự tạo `~/.secret/<profile>/x-userinfo.json` theo [mẫu X riêng](../../templates/social_auth/x-userinfo.example.json), rồi điền client ID, ID user kỳ vọng lấy độc lập và access token. Nếu chọn công cụ OAuth của X, dùng file UserInfo mà công cụ đã lưu. Reader chỉ dùng access token còn hiệu lực trong file. Dùng tên profile theo quy tắc ở phần LinkedIn.
3. Khi đã chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Lệnh thực sự gửi một GET đến X, không đăng hay tạo lịch; **chưa chạy với tài khoản thật** trong đợt này.

```powershell
python -m scripts.social.channels.x.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ nói ID do X trả về trùng ID do chủ tài khoản khai; không chứng minh token thuộc client ID khai báo, danh tính pháp lý, quyền upload/đăng hay cấu hình profile không bị sao chép. `unknown` gồm lỗi mạng, response bất thường và thiếu quyền; không tự suy token hết hạn. Không lệnh nào in token hoặc ID. Reader có kiểm symlink/junction, hardlink và danh tính file, nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Discord: chuẩn bị kiểm bot chỉ đọc sau này

1. Chủ tài khoản kiểm thông tin bot trên [Discord Developer Portal](https://discord.com/developers/applications), lấy **bot user ID** kỳ vọng từ nguồn độc lập; không nhầm với guild ID, channel ID hoặc application ID. Bot token khác OAuth user token; không chia sẻ token qua chat, repo hay log.
2. Chủ tài khoản tự tạo `~/.secret/<profile>/discord-bot-userinfo.json` theo [mẫu riêng](../../templates/social_auth/discord-bot-userinfo.example.json), điền application ID, bot user ID và bot token. Mẫu tổng quát Discord không phải cấu hình chạy; tên profile theo quy tắc ở phần LinkedIn. Không đưa token vào tham số lệnh.
3. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Theo [Discord Get Current User](https://docs.discord.com/developers/resources/user#get-current-user), lệnh gửi một GET đến Discord bằng bot token; không kết nối Gateway, không gửi tin và chưa chạy với bot thật trong đợt này.

```powershell
python -m scripts.social.channels.discord.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ phản ánh ID bot Discord trả về khớp kỳ vọng do chủ tài khoản khai. Nó không chứng minh token thuộc application ID khai báo hoặc bot có quyền trong guild/channel; quyền gửi phụ thuộc role, channel và loại đích. `unknown` có thể do lỗi mạng, phản hồi bất thường hoặc quyền; không tự suy token hết hạn. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## YouTube: chuẩn bị kiểm kênh chỉ đọc sau này

Code thiết lập OAuth chỉ đọc mới và điều kiện để chủ kênh tự chạy được mô tả tại [SOCIAL_OAUTH_YOUTUBE.md](SOCIAL_OAUTH_YOUTUBE.md). Chưa chạy hoặc xác minh OAuth trên tài khoản thật; lệnh kiểm bên dưới vẫn nhận access token đã cấp trong profile.

1. Chủ tài khoản kiểm [Channels: list](https://developers.google.com/youtube/data/reference/rest/v3/channels/list), scope `youtube.readonly`, quota và dự án Google Cloud; chọn channel ID kỳ vọng từ nguồn độc lập. Phép kiểm chỉ xét ngữ cảnh token hiện tại, không liệt kê mọi kênh hoặc quyền quản lý của tài khoản Google.
2. Nếu đã có OAuth user access token, tự tạo `~/.secret/<profile>/youtube-channel-userinfo.json` theo [mẫu riêng](../../templates/social_auth/youtube-channel-userinfo.example.json), rồi điền client ID, channel ID kỳ vọng và access token. Nếu chọn công cụ OAuth YouTube, dùng file UserInfo mà công cụ đã lưu. Mẫu UserInfo tách khỏi file token Google và cấu hình YouTube V1.
3. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Lệnh gọi một GET `channels.list(mine=true)`; không upload hoặc đăng. **Chưa chạy với tài khoản thật** trong đợt này.

```powershell
python -m scripts.social.channels.youtube.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ phản ánh ID kỳ vọng nằm trong trang kết quả hợp lệ. Nếu chưa thấy và còn trang tiếp, kết quả là `unknown`; công cụ chỉ lấy một trang. Danh sách rỗng, lỗi và phản hồi bất thường cũng là `unknown`. Không suy quyền upload, danh tính Google hoặc quan hệ token–client từ kết quả. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Facebook Page: chuẩn bị kiểm chủ thể token chỉ đọc sau này

1. Chủ tài khoản chọn Page ID dự kiến từ nguồn độc lập và Graph API version còn hỗ trợ. Meta mô tả [`/me`](https://developers.facebook.com/docs/graph-api/overview#me) là đối tượng đứng sau token: Page token ứng với Page, User token ứng với user. Kiểm lại quyền, phiên bản và chi phí/quota trước khi dùng; không cần tự cấp quyền ghi để chạy phép kiểm này.
2. Chủ tài khoản tự tạo `~/.secret/<profile>/facebook-page-userinfo.json` theo [mẫu riêng](../../templates/social_auth/facebook-page-userinfo.example.json), điền app ID, Page ID, phiên bản API và Page access token. Không dán token vào chat hoặc tham số lệnh. Mẫu này khác `FB_CONFIG` và không sửa file cấu hình V1.
3. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Lệnh gọi một GET đến Graph `/me?fields=id`; không đăng, không lấy danh sách Page và **chưa chạy với tài khoản thật** trong đợt này.

```powershell
python -m scripts.social.channels.facebook.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ là ID đối tượng Meta trả về trùng Page ID do chủ tài khoản khai. Body chỉ có ID không tự chứng minh loại Page token, app binding, quyền Page hay quyền đăng; các cờ đó luôn `false`. User token nhập nhầm vẫn có thể được API chấp nhận. Không dùng kết quả này làm bằng chứng có thể đăng Group; Group là đích và luồng UI riêng. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Instagram Facebook Login: chuẩn bị kiểm liên kết chỉ đọc

1. Chọn luồng **Instagram API với Facebook Login**. Theo [Meta IG User](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/v21.0/), luồng này dùng host Graph Facebook và Facebook User access token; yêu cầu quyền, vai trò và version phụ thuộc endpoint/app. Instagram Login là sản phẩm khác dùng token và host khác, chưa được reader này hỗ trợ.
2. Chủ tài khoản lấy Page ID và Instagram professional account ID kỳ vọng từ nguồn độc lập, chọn Graph API version còn hỗ trợ, rồi tự tạo `~/.secret/<profile>/instagram-facebook-userinfo.json` theo [mẫu riêng](../../templates/social_auth/instagram-facebook-userinfo.example.json). Điền app ID, hai ID, version và Facebook User access token; không dán token vào chat, repo hay đối số lệnh. Mẫu tổng quát Instagram không phải file chạy.
3. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Lệnh gọi một GET Page với trường `instagram_business_account` để đối chiếu liên kết; không tạo container, upload hay đăng. **Chưa chạy với tài khoản thật** trong đợt này.

```powershell
python -m scripts.social.channels.instagram.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ phản ánh Page và Instagram ID trả về khớp các giá trị do chủ tài khoản khai. Page ID trả về khác kỳ vọng, thiếu liên kết hoặc phản hồi không rõ đều là `unknown`. Reader trả `mismatch` khi Page đúng và phản hồi có IG ID hợp lệ khác kỳ vọng. Kết quả chỉ xác nhận sự trùng khớp ID nên quyền đăng, app và loại token vẫn cần bằng chứng riêng. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời. Chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Threads: chuẩn bị kiểm tài khoản chỉ đọc

1. Chủ tài khoản theo [tài liệu Threads của Meta](https://www.postman.com/meta/threads/request/34203612-3996f0a2-f2ee-4af7-9b66-3dbbe80b8d7d), chọn app, version còn hỗ trợ và quyền đọc phù hợp như `threads_basic`. Lấy Threads user ID kỳ vọng độc lập trong đúng ngữ cảnh app; không thay bằng Instagram ID, Facebook Page ID hay ID bài.
2. Chủ tài khoản tự tạo `~/.secret/<profile>/threads-userinfo.json` theo [mẫu riêng](../../templates/social_auth/threads-userinfo.example.json), điền app ID, Threads user ID kỳ vọng, version và Threads user access token. Không dán token vào chat, repo hay đối số lệnh. Mẫu tổng quát Threads không phải file chạy; reader không thực hiện OAuth hay refresh token.
3. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh sau tại gốc plugin. Lệnh gửi một GET tới `graph.threads.com` theo mẫu Threads của Meta, không tạo container hay đăng; **chưa chạy với tài khoản thật** trong đợt này.

```powershell
python -m scripts.social.channels.threads.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ phản ánh ID được trả về khớp giá trị do chủ tài khoản khai; chưa chứng minh token thuộc app khai báo hay có quyền đăng. Không tự coi Instagram token là Threads token. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Telegram: chuẩn bị kiểm bot phát chỉ đọc

1. Chủ tài khoản chọn bot có mục đích phát nội dung và tự lấy bot ID kỳ vọng từ nguồn độc lập; bot ID khác chat ID. Theo [Telegram getMe](https://core.telegram.org/bots/api#getme), phép kiểm chỉ xác định bot, không xác minh mục đích phát hay quyền trong channel. Bot duyệt V1 và cấu hình `TG_CONFIG` không được dùng làm đường lùi.
2. Chủ tài khoản tự tạo `~/.secret/<profile>/telegram-publish-bot-userinfo.json` theo [mẫu riêng](../../templates/social_auth/telegram-publish-bot-userinfo.example.json), điền bot ID và bot token. Không đưa token vào chat, repo hoặc tham số lệnh. Mẫu tổng quát Telegram không phải file chạy.
3. **Telegram đặt token trong đường dẫn HTTPS.** Reader tắt HTTP debug và không in URL, nhưng audit hook của Python, công cụ trace/proxy, phần mềm giám sát hoặc log mạng của môi trường có thể thấy đường dẫn chứa token. Chỉ chủ tài khoản dùng reader trong môi trường tin cậy, đã kiểm soát các công cụ ghi trace/log; không chia sẻ trace hay log chứa URL. Việc này chưa được kiểm với hạ tầng thực.
4. Khi chủ tài khoản chủ động cho phép một lần gọi chỉ đọc, chạy lệnh dưới đây tại gốc plugin. Lệnh thực sự gọi một GET `getMe`; không gửi tin, không lấy cập nhật và **chưa chạy với bot thật** trong đợt này.

```powershell
python -m scripts.social.channels.telegram.readonly_auth --check-readonly --profile ten-profile
```

`match` chỉ phản ánh bot ID trả về khớp kỳ vọng do chủ tài khoản khai; không chứng minh bot có mục đích phát, khác bot duyệt hay có quyền gửi vào channel. Reader kiểm link và file nhưng không loại trừ thay đổi đồng thời; chỉ dùng kho được bảo vệ. Chỉ CLI cố định root của kho.

## Đọc kết quả và bước tiếp

Với chín lệnh UserInfo thử nghiệm ở trên, trong PowerShell xem `$LASTEXITCODE` ngay sau lệnh. Mã `0` là ID trả về khớp giá trị kỳ vọng trong profile; `1` gồm cả `mismatch` và `unknown`, cần xem trường `identity` trong JSON để phân biệt. Với `mismatch`, dừng và đối chiếu profile, app và ID kỳ vọng; `unknown` nghĩa là lần kiểm chưa kết luận được danh tính. Mã `2` báo yêu cầu hoặc profile không hợp lệ hay không khả dụng. Không mã nào chứng minh quyền đăng hoặc token thực sự thuộc app đã khai.

- **Offline:** Facebook Page, Instagram, YouTube, LinkedIn, Threads, TikTok, Discord và X đã có một số preview trực tiếp bằng dữ liệu giả; phạm vi từng loại bài xem [bảng route](SOCIAL_V2_ROUTES.md). Đây chưa phải kết nối hoặc đăng thật. Candidate Postiz chỉ phục vụ nghiên cứu cấu trúc, không kiểm chứng OAuth. Không đưa thông tin tài khoản thật vào fixture.
- **Kiểm kết nối khi đã được chủ tài khoản cho phép:** các lệnh LinkedIn, TikTok, X, Discord, YouTube, Facebook Page, Instagram Facebook Login, Threads và Telegram publisher ở trên mới kiểm thử offline. Không coi ví dụ dưới dạng Postiz candidate hay test transport giả là kiểm OAuth thật.
- **Không đạt:** thiếu app, callback sai, 401/403, phạm vi thiếu hoặc đích không xác định → ghi rõ lỗi đã làm sạch và dừng, không suy quyền. Chỉ chủ tài khoản xử lý đăng nhập, cấp quyền và kho bí mật.
- **Bằng chứng còn thiếu:** kết quả kiểm với tài khoản thật cho cả chín kênh, liên kết token với app, quyền trên đích và quyền đăng. Các lệnh đọc dùng access token còn hiệu lực từ profile. Phép kiểm Facebook Group và reader cho Instagram Login chưa có. V2 live hiện chưa mở.
