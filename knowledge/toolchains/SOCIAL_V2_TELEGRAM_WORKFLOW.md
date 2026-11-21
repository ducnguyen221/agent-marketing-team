# Luồng Telegram V2

`scripts.social.telegram_package_workflow.run_telegram_package_workflow` tiếp nhận gói độc lập hoặc gói chiến dịch `social-package/1` cho một kênh Telegram. Cổng production chạy đầu tiên và hiện trả `production_approval_generation_unavailable`. Khi có cơ chế cấp quyền từ nguồn chính thức, điểm vào còn yêu cầu `enable_dispatch=True` và hệ điều hành POSIX có sổ lưu bền. Trên Windows, luồng dừng trước bước đọc Telegram.

Luồng nhận thư mục gói, ID bot, ID số của kênh, mã lượt đăng ổn định, token trong bộ nhớ, phê duyệt gắn với gói và thư mục sổ cục bộ do bên gọi kiểm soát. Luồng kiểm dấu vân tay gói, đích gửi và byte đính kèm. Bộ gửi đọc lại gói và byte tệp ngay trước khi giao dữ liệu cho transport. Hỗ trợ bài chữ, ảnh, album ảnh, video hoặc PDF theo khả năng của gói.

Album dùng một POST multipart tới `sendMediaGroup` với 2–10 ảnh theo thứ tự trong gói. Mỗi phần tử `InputMediaPhoto` trỏ tới phần multipart tương ứng qua `attach://`. Gói độc lập có thể đặt chú thích trên ảnh đầu tiên. Gói chiến dịch giữ chú thích đã duyệt của từng ảnh theo đúng thứ tự. [sendMediaGroup](https://core.telegram.org/bots/api#sendmediagroup) · [InputMediaPhoto](https://core.telegram.org/bots/api#inputmediaphoto)

Luồng dùng cùng token để gọi `getMe`, `getChat`, `getChatMember` và gửi bài. Bước kiểm tra xác nhận đúng bot, đúng ID và loại kênh, cùng quyền quản trị viên `can_post_messages` của bot trên kênh đó. Telegram định nghĩa `status=administrator` và trường `can_post_messages` trong đối tượng quản trị viên của kênh. [getChat](https://core.telegram.org/bots/api#getchat) · [getChatMember](https://core.telegram.org/bots/api#getchatmember) · [ChatMemberAdministrator](https://core.telegram.org/bots/api#chatmemberadministrator)

## Gói chiến dịch

Truyền `campaign_context=TelegramCampaignContext(...)` với thư mục chiến dịch, phạm vi G2, thư mục dựng lại gói, thư mục quyết định theo đích, múi giờ, quyền riêng tư và các tệp nguồn đã dùng khi chuẩn bị gói. Luồng này nhận lượt đăng trực tiếp với `scheduled_at=None` và `options={}`. Giữ cùng mã lượt đăng khi kiểm duyệt, gửi và tra cứu biên nhận.

Lấy `expected_review` và `expected_head` từ kết quả kiểm quyết định theo đích của `check_package_readiness --target-review-stdin`. Truyền `expected_review` trong ngữ cảnh chiến dịch và dùng `expected_head` làm `TelegramPackageApproval.approval_ref`. Kết quả phải khớp quyết định duyệt theo đích còn hiệu lực, gói đã đối chiếu với nguồn V1, bot, kênh và mã lượt đăng. Luồng kiểm lại bằng chứng ngay trước khi gửi, sau khi đã đọc và kiểm toàn bộ byte đính kèm. Quyết định cục bộ phục vụ đối chiếu. Việc xác thực người duyệt và phối hợp thu hồi nguyên tử với thao tác gửi cần nguồn cấp quyền production chính thức. [Kiểm ngữ cảnh duyệt](SOCIAL_V2_APPROVAL_CONTEXT.md)

## Lần gửi và biên nhận

Giữ cùng thư mục sổ và mã lượt đăng để giữ cùng khóa thao tác tạo bài qua các lần chỉnh gói hoặc thay tham chiếu phê duyệt. Khóa dựa trên nền tảng, bot, kênh, lượt đăng và thao tác. Transport tạo độc quyền rồi đồng bộ tệp dấu và thư mục trước POST. Một tệp dấu đã tồn tại chặn POST tiếp theo cho cùng khóa. [Sổ lần thử Social V2](SOCIAL_V2_TRANSPORT.md)

Đổi mã lượt đăng hoặc thư mục sổ tạo phạm vi chống trùng mới. Trước khi mở production, cơ chế cấp quyền cần xác thực mã lượt đăng có nguồn chính thức và khóa định danh đó cùng gói đã duyệt. Hiện mã lượt đăng đến từ bên gọi.

- `accepted_by_provider` yêu cầu phản hồi HTTP thành công, `ok=true`, mã tin nhắn, đúng ID và loại kênh, đúng chữ hoặc chú thích và đúng trường media nếu có đính kèm.
- Với album, phản hồi cần có đúng số tin nhắn ảnh, mã tin nhắn riêng của từng ảnh và cùng mã nhóm tin nhắn. Biên nhận bổ sung `media_group_id` và toàn bộ `message_ids`. `provider_id` là mã tin nhắn ảnh đầu tiên do Telegram trả.
- `unknown` cần đối soát trước khi chủ tài khoản quyết định xử lý. Phản hồi có thể bị mất sau khi Telegram đã nhận yêu cầu. Luồng thực hiện tối đa một POST cho mỗi khóa và giữ tệp dấu qua mọi kết quả.
- `receipt_status=stored` ghi nhận biên nhận đã được đồng bộ. Biên nhận lưu mã tin nhắn cùng ID kênh vì mã tin nhắn chỉ có nghĩa trong kênh đó. Sổ còn lưu ID bot, lượt đăng, khóa thao tác và dấu vân tay gói. Nếu lỗi lưu xảy ra sau khi Telegram chấp nhận, kết quả vẫn là `accepted_by_provider` với `receipt_status=unconfirmed`.

Với gói độc lập, gọi `read_telegram_create_receipt` với đúng thư mục sổ, `package_dir`, bot, kênh, lượt đăng và dấu vân tay gói. Kết quả `matched` yêu cầu gói, byte của mọi tệp đính kèm, biên nhận và tệp dấu khớp. Gói thiếu tệp hoặc có byte đã đổi trả `receipt_status=unverified_package`.

Với gói chiến dịch, gọi cùng hàm với thư mục sổ, bot, kênh, lượt đăng, dấu vân tay gói, `expected_review` và `expected_approval_ref` của lúc gửi. Biên nhận lưu bản chụp đích và dấu vân tay các cổng nguồn đã kiểm, kèm ID quyết định. Biên nhận album còn lưu manifest đã duyệt, gồm chú thích và siêu dữ liệu ảnh. Bộ đọc xác minh dấu vân tay manifest rồi dùng số ảnh trong đó để kiểm tra số mã tin nhắn. Có thể tra cứu lịch sử kể cả khi gói hoặc trạng thái duyệt sau đó thay đổi.

Khi tiến trình dừng sau khi tạo liên kết tệp biên nhận nhưng trước khi xóa tên tạm, bộ đọc có thể bác biên nhận vì tệp còn nhiều tên. Giữ sổ nguyên trạng để đối soát thủ công. Biên nhận phản ánh phản hồi lúc tạo bài. Trạng thái hiện tại và khả năng người xem truy cập bài chưa được xác minh.

Biên nhận độc lập đã lưu vẫn đọc được bằng lời gọi cũ với `package_dir` trỏ đến gói ban đầu, dấu vân tay đã lưu và nguyên thư mục sổ.

## Bình luận trong nhóm thảo luận

Bình luận của bài kênh Telegram thuộc bản sao tự chuyển tiếp trong nhóm thảo luận liên kết. Tính năng này cần xác minh đúng nhóm, đúng tin nhắn của bài trong nhóm và khả năng trả lời của bot trong nhóm. Luồng hiện dừng ở bài kênh. Gói Telegram có trường bình luận sẽ bị từ chối trong kiểm tra schema. [Thảo luận kênh Telegram](https://core.telegram.org/api/discussion)
