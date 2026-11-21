# Discord V2 — Gửi gói có sổ theo dõi

`scripts.social.discord_package_workflow.run_discord_package_workflow` nhận gói độc lập `social-standalone-package/1` hoặc gói chiến dịch `social-package/1` đã chuẩn bị cho một bot và một kênh Discord. Gói có thể là `post_text`, `post_image`, `post_image_album`, `post_video` (MP4) hoặc `post_document` (PDF). Album gửi 2–10 ảnh trong một tin nhắn bằng các trường `files[0]`, `files[1]` và tiếp theo. `payload_json.attachments` dùng cùng chỉ số để gắn ảnh theo thứ tự đã duyệt. Adapter kiểm tra kích thước và SHA-256 của từng tệp sẽ gửi. Nội dung gửi giữ nguyên văn bản đã duyệt và tắt phân tích mention. [Discord Uploading Files](https://docs.discord.com/developers/reference#uploading-files)

## Điều kiện trước khi gửi

- `ChannelApproval` liên kết `platform="discord"`, `account_id` là bot ID, `package_digest` là SHA-256 của manifest chuẩn hoá và `options_digest` là kết quả `discord_target_digest(bot_id=..., channel_id=..., guild_id=...)`. Với gói độc lập, `target.account_id` và `target.destination_id` trong manifest phải khớp bot ID và channel ID.
- `approval_ref`, `occurrence_id` và thư mục sổ do bên gọi cung cấp. Chúng phục vụ đối chiếu và lưu dấu. Quyền gửi production cần nguồn phê duyệt có thẩm quyền và hiện bị chặn tại `require_production_authority()` trước khi đọc gói, mở sổ hoặc gọi API.
- Sau khi cổng production được cấp quyền, workflow còn cần `enable_dispatch=True` và thư mục sổ cục bộ trên POSIX có hỗ trợ ghi độc quyền, hard link và `fsync`. Mọi lần gọi cho cùng một lượt phải dùng cùng thư mục sổ và cùng `occurrence_id`. Thư mục sổ và đường dẫn cha phải do bên vận hành tin cậy kiểm soát và giữ ổn định. Việc tra biên nhận mở lại đường dẫn, nên không được đổi tên hoặc thay thế thư mục trong lúc workflow ghi hoặc đọc sổ.
- Adapter dùng cùng bot token trong bộ nhớ để đối chiếu `/users/@me`, kênh văn bản hoặc thông báo trong đúng máy chủ, rồi mới gửi. Hai yêu cầu GET xác nhận bot và quyền đọc kênh. Discord kiểm tra quyền `SEND_MESSAGES` và, với gói có tệp, `ATTACH_FILES` khi xử lý yêu cầu tạo tin nhắn.

## Gói chiến dịch

Truyền `campaign_context=DiscordCampaignContext(...)` với thư mục chiến dịch, phạm vi G2, thư mục dựng lại gói, thư mục quyết định theo đích, múi giờ, quyền riêng tư và các tệp nguồn đã dùng để chuẩn bị gói. Với album, truyền danh sách ảnh theo đúng thứ tự đã duyệt. Workflow hỗ trợ lượt gửi trực tiếp với `scheduled_at=None` và tùy chọn theo đích `{"guild_id": guild_id}`. [Chuẩn bị gói chiến dịch](SOCIAL_V2_PACKAGE.md)

Lấy `expected_review` và `expected_head` từ kết quả `check_package_readiness --target-review-stdin`. Truyền `expected_review` trong ngữ cảnh chiến dịch và dùng `expected_head` làm `ChannelApproval.approval_ref`. Workflow dựng lại gói từ nguồn rồi đối chiếu quyết định duyệt hiện hành, dấu vân tay G1 và G2, bot, kênh, máy chủ và lượt gửi. Sau khi adapter đọc byte đính kèm và kiểm tra bot, kênh bằng GET, workflow kiểm lại cùng bằng chứng trước khi transport ghi dấu lượt gửi. Nguồn phê duyệt production vẫn cần xác thực người duyệt và phối hợp việc thu hồi với thao tác gửi. [Kiểm ngữ cảnh duyệt](SOCIAL_V2_APPROVAL_CONTEXT.md)

## Dấu vết và trạng thái

Khóa lượt gửi được tạo từ bot, kênh, máy chủ, `occurrence_id` và thao tác `create`. Đổi dấu vân tay của gói vẫn dùng cùng khóa cho lượt đó. Transport tạo dấu lượt gửi bằng thao tác ghi độc quyền và đồng bộ xuống đĩa trước một POST. Không tự gửi lại khi API trả lỗi, phản hồi không khớp, mất kết nối hoặc kết quả chưa rõ.

Adapter nhận `accepted_by_provider` khi phản hồi khớp ID kênh, tác giả bot, nội dung và tên tệp đính kèm. Với album, phản hồi phải có đầy đủ tệp theo đúng thứ tự, mỗi tệp có kích thước khớp và ID đính kèm riêng. Phản hồi thiếu hoặc mâu thuẫn trả `unknown`. Biên nhận lưu dấu vân tay của toàn bộ gói có thứ tự, khóa lượt gửi, bot ID, guild ID, channel ID và `provider_id` là ID tin nhắn. Nếu Discord đã nhận tin nhưng việc lưu biên nhận gặp lỗi, workflow trả `status=accepted_by_provider` kèm `receipt_status=unconfirmed` và giữ dấu lượt gửi.

Khi tra gói chiến dịch bằng `read_discord_create_receipt`, truyền thêm `expected_review` và `expected_approval_ref` của lúc gửi. Bộ đọc đối chiếu dấu lượt gửi, bản chụp duyệt kèm dấu vân tay G1/G2, quyết định phê duyệt và toàn bộ đích, kể cả máy chủ. Với album, bộ đọc kiểm manifest ảnh theo thứ tự bằng dấu vân tay gói. Có thể tra lịch sử từ sổ ngay cả khi gói hoặc quyết định duyệt hiện hành đã thay đổi. Lời gọi cho gói độc lập vẫn dùng thư mục sổ, bot, kênh, máy chủ, lượt gửi và dấu vân tay gói.

Lần tra trả `unknown` nếu bằng chứng cục bộ thiếu hoặc không khớp. Biên nhận phản ánh phản hồi lúc Discord nhận yêu cầu tạo tin nhắn. Giữ nguyên sổ và đối chiếu bằng chứng vận hành trước khi quyết định thêm một lượt gửi.
