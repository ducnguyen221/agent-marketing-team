# Đối chiếu bằng chứng gửi Social V2 với chiến dịch V1

`inspect_campaign_dispatch_evidence` dựng lại gói từ chiến dịch V1 và kiểm tra nội dung, đính kèm, phạm vi và tuyến gửi. Hàm dùng `verify_delivery_payload` để đối chiếu với ràng buộc hiện hành trong `publish.json`. Khi thiếu bằng chứng hoặc có sai khác, hàm dừng với lỗi. Gói độc lập trả lỗi `standalone_approval_source_unavailable` vì hiện chưa có nguồn duyệt cho loại gói này.

Hàm tạo bản dựng trong `temporary_parent` và dọn bản dựng sau khi đối chiếu. Truyền một thư mục cục bộ có sẵn nằm ngoài chiến dịch và gói. Múi giờ phải hợp lệ theo IANA. Nếu có lịch, timestamp phải có độ lệch UTC tường minh và khớp với giờ địa phương của múi giờ đó. Phép đối chiếu giữ nguyên chuỗi lịch trong dấu vân tay.

`campaign_binding_payload` biểu diễn chính xác bản xem trước V2 trong hợp đồng ràng buộc V1 hiện có. Mã lần gửi `occurrence_id` tương ứng với `occurrence_key` trong bản xem trước và trong payload V1. Mã băm ràng buộc cả gói, tài khoản, đích, lần gửi, lịch, múi giờ, chế độ riêng tư và tùy chọn. Ràng buộc V1 đã có cho một payload khác sẽ không khớp. Hàm đối chiếu đọc bằng chứng G1, G2 và G3 nếu chiến dịch có cột G3 và đích là Facebook hoặc YouTube. Trường `campaign_evidence` chứa dấu vân tay theo cổng và giữ kín tên người duyệt cùng câu duyệt. Trường `binding` chứa tham số gửi đã đối chiếu, gồm ID tài khoản, ID đích và tùy chọn.

Kết quả khớp vẫn có `status=blocked` và `reason=authenticated_approval_and_revocation_unavailable`. Các tệp V1 cùng quyền ghi với tiến trình hiện tại, vì vậy phép đọc lại chỉ phát hiện được thay đổi quan sát thấy khi đối chiếu. Cần nguồn xác thực người duyệt tách khỏi bên gửi, trạng thái thu hồi có thẩm quyền và cơ chế kiểm tra trạng thái đó khi nhận từng lần gửi. Các điểm vào gửi thật tiếp tục chặn bằng `require_production_authority()`. Hàm đối chiếu chỉ đọc bằng chứng, không ghi duyệt, không dùng cơ sở dữ liệu và không gọi nền tảng.

Định danh trạm trong phạm vi tham gia vào phép băm ràng buộc. Việc kiểm chứng độc lập định danh đó cần danh mục trạm có thẩm quyền.

### Biên nhận gửi

Social V2 chưa ghi biên nhận gửi của chiến dịch. Trước khi mở gửi thật, bên xác thực quyền duyệt phải lưu bền vững bản chụp bất biến ngay khi ghi nhận quyền thực hiện lần gửi. Bản chụp gắn khóa thao tác với đúng tài khoản, đích, lần gửi, mã băm của gói và bản duyệt, thế hệ duyệt cùng bằng chứng theo từng cổng.

Bên gửi ghi kết quả về bản chụp của chính lần gửi đó, kể cả khi duyệt bị sửa hoặc thu hồi sau đó. Thu hồi chặn thao tác gửi mới theo quyền đã mất hiệu lực. Lịch sử lần gửi cũ vẫn được giữ để đối soát. Phản hồi chấp nhận từ nhà cung cấp chỉ xác nhận đã nhận yêu cầu. Khi chưa đủ bằng chứng, kết quả ở trạng thái chưa xác minh. Chỉ xác nhận đã đăng sau khi đọc lại từ nền tảng qua nguồn được xác thực và khớp với lần gửi đã lưu.
