# Luồng LinkedIn V2 cho gói độc lập và campaign

`scripts.social.linkedin_package_workflow.run_linkedin_package_workflow` là điểm vào Python dành cho gói LinkedIn độc lập có đích cụ thể. Cổng production chạy đầu tiên và hiện luôn trả `production_approval_generation_unavailable`. Luồng cần được nối với phê duyệt có nguồn trước khi có thể chạy với LinkedIn.

Luồng nhận thư mục gói, tác giả thành viên, đích trùng tác giả, mã lượt đăng ổn định, phiên bản API, thông tin xác thực trong bộ nhớ, tham chiếu phê duyệt và thư mục giữ dấu lần gửi. Luồng gọi API nhận diện tài khoản bằng chính thông tin xác thực dự kiến dùng khi gửi.

- Với gói ảnh hoặc video, trình tải xác minh dấu vân tay gói, kiểm tra byte tệp và tải đúng byte đó. Chỉ bước đọc lại trả `AVAILABLE` cho đúng chủ sở hữu mới cho phép dùng mã media để tạo bài. Kết quả đang xử lý, lỗi, không rõ hoặc đã từng thử đều dừng trước khi tạo bài.
- Sau khi nhận mã bài từ phản hồi chấp nhận tạo, luồng ghi biên nhận `<khóa-tạo-bài>.linkedin-receipt.json` vào thư mục nhật ký bằng thao tác tạo độc quyền. Biên nhận chứa mã bài, tác giả, đích, lượt đăng, khóa thao tác và dấu vân tay gói. Nếu chưa xác nhận ghi thành công, luồng giữ kết quả chấp nhận tạo và dừng trước bước đọc lại.
- Bình luận đầu tiên, nếu có trong gói, chỉ được gửi khi bước đọc lại đúng mã bài và tác giả báo bài `PUBLISHED` và `PUBLIC`. Nếu đọc lại thất bại, bình luận vẫn ở trạng thái chưa thử.
- Giữ cùng thư mục dấu lần gửi và cùng mã lượt đăng để dùng lại khóa tạo bài và bình luận qua các lần chỉnh gói. Hai thao tác có khóa riêng. Khi kết quả gửi không rõ, tệp dấu vẫn được giữ. Trên POSIX, bộ gửi yêu cầu đồng bộ tệp dấu và thư mục trước POST; chưa kiểm chứng độ bền khi mất điện. Windows hiện dừng trước bước này. Chi tiết và các giả định về thư mục ổn định tại [SOCIAL_V2_TRANSPORT.md](SOCIAL_V2_TRANSPORT.md). Trình tải hiện có khóa chứa dấu vân tay gói, vì vậy chỉnh gói trong cùng lượt đăng vẫn có thể tạo thêm lần tải media trước khi khóa tạo bài chặn lần gửi bài.

Điểm vào gửi tự lấy bằng chứng của từng bước. Hàm gửi bài cấp thấp vẫn nhận `MediaObservation` do bên gọi cung cấp. Cổng production hiện chặn các điểm vào gửi và đối soát qua mạng. Việc ghi biên nhận cần hệ thống tệp hỗ trợ hard link. Trên Windows, mã đồng bộ nội dung tệp nhưng chưa có bảo đảm lưu mục thư mục khi mất điện.

## Đối soát sau gián đoạn

Giữ nguyên thư mục nhật ký do bên gọi kiểm soát, gói đã duyệt và mã lượt đăng. Gọi `read_linkedin_create_receipt` để đọc cục bộ bằng tác giả, đích, mã lượt đăng và dấu vân tay gói. Hàm tự tính tên tệp biên nhận và tệp dấu tạo bài. Hàm kiểm tra tệp cục bộ, khóa thao tác, lượt đăng, tác giả, đích, dấu vân tay và định dạng URN bài. Kết quả `matched` yêu cầu cả biên nhận hợp lệ và tệp dấu tạo bài khớp. Khi thiếu biên nhận sau khi đã ghi dấu, kết quả tạo bài là `unknown`. Điều này có thể xảy ra nếu tiến trình dừng giữa lúc LinkedIn chấp nhận yêu cầu và lúc ghi xong biên nhận.

`reconcile_linkedin_package_workflow` chỉ đọc qua mạng sau khi qua cổng production, được bật bằng `enable_provider_read=True` và có đủ bằng chứng cục bộ. Hàm xác minh gói với dấu vân tay đã duyệt, rồi dùng cùng thông tin xác thực trong bộ nhớ cho hai yêu cầu GET, một để kiểm tra tài khoản và một để đọc đúng URN lấy từ biên nhận. Biên nhận không lưu dấu vết để xác minh token hiện tại có giống token của lần tạo trước hay không.

- `provider_reports_published` nghĩa là LinkedIn trả đúng URN và tác giả, với `PUBLISHED` và `PUBLIC`.
- `provider_reports_pending` nghĩa là LinkedIn trả đúng URN và tác giả, với `PUBLISH_REQUESTED` và `PUBLIC`.
- `unverified` áp dụng khi đọc lại thiếu bằng chứng, gồm cả phản hồi 403, 404 và lỗi mạng. Kết quả này giữ nguyên `accepted_by_provider` khi có biên nhận đã khớp.

Nếu tiến trình dừng sau khi tạo hard link nhưng trước khi xóa tên tệp tạm, biên nhận có thể còn hai hard link. Khi đó bộ đọc trả `receipt_status=invalid` và `post_status=unknown`, đồng thời giữ nguyên cả hai tên tệp.

Đối soát giữ nguyên tệp dấu, biên nhận và dữ liệu LinkedIn. Luồng không gửi lại bài, không gửi bình luận, không thử lại yêu cầu thất bại và không tiếp tục tải media đang xử lý.

## Gói campaign

Điểm vào `run_linkedin_package_workflow` nhận gói `social-package/1` với `LinkedInCampaignContext`. Truyền thư mục campaign, phạm vi G2 đã chọn, thư mục tạm, sổ quyết định theo đích, dấu vân tay bản xét duyệt, múi giờ và `privacy="public"`. Chỉ định tệp văn bản, bình luận hoặc media nếu đã dùng tệp riêng khi lập gói. `ChannelApproval.approval_ref` phải trùng quyết định mới nhất của đúng đích. Đích là URN tác giả thành viên và phiên bản API phải trùng bản xét duyệt. Luồng áp dụng cho lượt gửi ngay, với bài chữ, ảnh hoặc video và bình luận đầu tiên tùy chọn.

- Luồng dựng lại gói từ nguồn, kiểm bằng chứng G1 và G2, rồi so bản xét duyệt chính xác với quyết định V2 hiện hành cho đích LinkedIn. Luồng đọc lại bằng chứng ngay trước từng yêu cầu tới LinkedIn, kể cả từng phần tải video. Cổng production vẫn chặn vô điều kiện. Nhật ký campaign yêu cầu POSIX.
- Media chỉ được gắn vào bài khi lần tải đúng byte của gói được LinkedIn báo `AVAILABLE` cho đúng chủ sở hữu và URN. Biên nhận tạo bài lưu ảnh chụp xét duyệt và dấu vân tay các cổng, tham chiếu quyết định, đích, phiên bản API, URN bài và kết quả media cùng metadata gói. Khóa cho tải media, tạo bài và bình luận được tính riêng từ tác giả, đích và mã lượt đăng. Giữ nguyên mã lượt đăng qua các lần sửa.
- Chỉ gửi bình luận sau khi ghi bền biên nhận tạo bài và đọc lại đúng URN, tác giả, nội dung và media của bài `PUBLISHED` và `PUBLIC`. Lần gọi sau có thể đọc lại bài khi biên nhận tạo bài khớp và phê duyệt hiện hành vẫn hợp lệ, kể cả gói không có bình luận. Chỉ tiếp tục bước bình luận khi chưa từng thử gửi. Nếu đã có dấu thử bình luận mà thiếu biên nhận hợp lệ, trạng thái vẫn không rõ và luồng không gửi lại. Không tự thử lại lượt tạo bài hoặc tiếp tục phiên tải media dở dang. URN của media đang xử lý chưa được lưu bền.
- `read_linkedin_campaign_receipt` dùng tác giả, đích, mã lượt đăng, phiên bản API, dấu vân tay gói và bản xét duyệt, cùng tham chiếu phê duyệt của lần gửi. Hàm đọc riêng `<khóa>.linkedin-campaign-create.json` và `<khóa>.linkedin-campaign-comment.json` với các tệp dấu tương ứng trong cùng nhật ký. Biên nhận tạo bài lưu manifest gói để xác minh bình luận có được yêu cầu và metadata media có khớp với gói đã duyệt. Kết quả trả về không chứa văn bản bài hoặc bình luận. Hàm đọc được bằng chứng lịch sử sau khi nguồn hoặc phê duyệt đã đổi. `accepted_by_provider` xác nhận phản hồi chấp nhận. Trạng thái hiện tại của bài và bình luận cần được xác minh qua LinkedIn.
