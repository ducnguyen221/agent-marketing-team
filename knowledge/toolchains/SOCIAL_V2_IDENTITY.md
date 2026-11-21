# Đối chiếu danh tính tài khoản social V2

`read_package_account` nhận credential từ caller và chỉ đọc nhà cung cấp khi
`enable_provider_read=True`. Reader dùng chính credential đó để so sánh ID với
`account_id`. Kết quả `match` tạo `AccountObservation` trong bộ nhớ, chứa nền
tảng, ID tài khoản, SHA-256 của credential và tên loại quan sát. Sai ID,
phản hồi không xác định hoặc tham số không hợp lệ đều chặn quan sát.

| Nền tảng | `account_id` cần đối chiếu | Reader và tham số bổ sung |
|---|---|---|
| Facebook | ID Page | `check_identity(credential, account_id, api_version=...)` so sánh ID từ `/me`. Bắt buộc `api_version`. |
| Instagram | ID tài khoản Instagram Business qua Facebook Login | `check_link(credential, linked_page_id, account_id, api_version=...)` đọc Page và đối chiếu đồng thời ID Page và ID Instagram liên kết. Bắt buộc `linked_page_id` và `api_version`. |
| LinkedIn | URN `urn:li:person:…` | `check_userinfo(credential, account_id)` so sánh `sub` của thành viên. Reader từ chối URN tổ chức vì `sub` đại diện cho thành viên. |
| Telegram | ID bot | `check_bot(credential, account_id)` đối chiếu bot từ `getMe`. ID channel là đích riêng. |
| Threads | ID người dùng Threads | `check_identity(credential, account_id, api_version=...)` so sánh ID từ `/me`. Bắt buộc `api_version`. |
| TikTok | Open ID | `check_userinfo(credential, account_id)` so sánh `open_id` trong hồ sơ trả về. |
| X | ID người dùng | `check_userinfo(credential, account_id)` so sánh ID từ `/2/users/me`. |
| YouTube | ID kênh | `check_channel(credential, account_id)` kiểm tra ID có trong kết quả `channels.list(mine=true)`. Kết quả xác nhận kênh xuất hiện trong danh sách đọc được với token. |

Discord chặn gửi trước khi gọi transport. [Reader Discord](../../scripts/social/channels/discord/readonly_auth.py)
đọc ID bot, trong khi [tuyến V2 hiện tại](../../scripts/social/publish_channel_package.py)
đối chiếu package theo ID channel. Cần tách ID bot và ID đích trong hợp đồng
Discord trước khi quan sát bot có thể dùng cho package.

Các adapter Facebook, Instagram, LinkedIn, Telegram, Threads, TikTok, X và
YouTube bắt buộc `AccountObservation` ở điểm gửi và đối chiếu nền tảng, ID
tài khoản và SHA-256 của chính credential dùng để gửi. Facebook và LinkedIn
kiểm cả ở bước đăng bài lẫn bình luận đầu tiên. Instagram và Threads kiểm khi
tạo container và khi xuất bản container. LinkedIn chỉ hỗ trợ tác giả cá nhân
qua luồng này. Với Telegram, ID bot trong quan sát phải trùng ID bot đã duyệt,
còn ID channel đích vẫn được kiểm riêng theo phê duyệt.

Quan sát chỉ ghi nhận kết quả đọc danh tính tại thời điểm kiểm tra. Cổng duyệt
và quyền đăng vẫn có điều kiện riêng. Loại token, ứng dụng, quyền trên đích,
mục đích của bot Telegram và kênh mà một lượt upload YouTube thực sự chọn đều
cần bằng chứng riêng nếu tuyến đăng yêu cầu. Credential được truyền trực tiếp
qua hàm, không đưa vào tham số dòng lệnh hoặc log. Tuyến đọc V2 không dùng
`check_profile` hay thay đổi cấu hình V1.

## Kiểm tra hồ sơ phê duyệt

`inspect_source_approval` dùng bộ xác minh để đọc manifest và media trong
`package_dir` và đối chiếu với gói dựng lại từ bài V1 thuộc đúng phạm vi G2.
Tệp manifest và media của gói có hard link bị từ chối trước khi đọc nội dung.
Caller truyền `temporary_parent` là thư mục cục bộ đã tồn tại bên ngoài cả
chiến dịch lẫn gói để dựng gói tạm. Nếu gói
ban đầu dùng tệp chỉ định qua `text_file`, `comment_file` hoặc `media_file`,
truyền lại cùng lựa chọn. Gói tạm được dọn khi kết thúc việc đối chiếu.

Sau khi xác minh nguồn và media, hàm kiểm bằng chứng G1, ràng buộc G2 với
payload và digest của gói, cùng G3 nếu chiến dịch yêu cầu. Khi các bước đó đạt,
hàm báo mã sự kiện ràng buộc, digest và khóa lần đăng. Kết quả vẫn mang
`status=blocked` với lý do `production_approval_generation_unavailable`.
Việc đối chiếu hồ sơ không gọi nhà cung cấp. [Hợp đồng xác minh nguồn](SOCIAL_V2_APPROVAL.md)

Chỉ dùng với cây nguồn V1 tin cậy và giữ nguồn ổn định trong suốt lượt kiểm.
Luồng đọc V1 hiện vẫn có thể đọc tệp nguồn có hard link.
