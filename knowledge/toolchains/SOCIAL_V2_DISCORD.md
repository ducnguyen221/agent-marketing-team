# Discord V2 — Kiểm tra bot và kênh chỉ đọc

Discord V2 dùng hai yêu cầu `GET` đến `discord.com` với cùng một bot token trong bộ nhớ. `GET /api/v10/users/@me` phải trả về ID bot đã duyệt và `bot: true`. Khi bot khớp, `GET /api/v10/channels/{channel_id}` phải trả đúng ID kênh và `guild_id`. Phạm vi hiện tại gồm kênh văn bản và kênh thông báo trong máy chủ Discord.

`check_bot_channel` trả `identity` và `channel_access_verified` mà không trả token hoặc dữ liệu phản hồi gốc. Kết quả xác nhận quyền đọc kênh tại thời điểm kiểm tra. `app_binding_verified`, `profile_binding_verified` và `publish_authorized` giữ giá trị `false`. Quyền đọc và quyền gửi là hai quyền riêng trên Discord.

## Liên kết với gói đã duyệt

- `ChannelApproval.account_id` chứa bot ID. Với manifest standalone V2, `target.account_id` là bot ID và `target.destination_id` là channel ID.
- `ChannelApproval.options_digest` lưu kết quả `discord_target_digest(bot_id=..., channel_id=..., guild_id=...)`. Adapter đối chiếu giá trị này cùng dấu vân tay của manifest.
- Adapter gọi hai yêu cầu chỉ đọc trực tiếp sau khi đối chiếu gói và đích. Cả hai yêu cầu dùng cùng chuỗi credential dành cho transport của adapter. Sai bot, sai guild, sai kênh hoặc phản hồi không hợp lệ đều dừng trước transport.

Cổng `require_production_authority()` hiện chặn dispatch trước khi đọc manifest hoặc gọi API. Bằng chứng đọc kênh thuộc bước kiểm tra danh tính và đích. Cấp quyền đăng production vẫn đòi một nguồn phê duyệt có thẩm quyền.
