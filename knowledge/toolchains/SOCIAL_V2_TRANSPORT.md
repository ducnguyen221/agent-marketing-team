# Sổ lần thử khi gửi Social V2

`GuardedPackageTransport` dùng tên tệp `<sha256(attempt_key)>.attempt` trong thư mục sổ. Các lượt xử lý cùng một lần thử phải dùng chung thư mục sổ và cùng khóa lần thử. Mỗi khóa gắn với gói đã duyệt, đích và thao tác tương ứng.

Transport kiểm tra quyền production trước. Trên POSIX, nó mở thư mục sổ, đối chiếu thiết bị và inode với thư mục đã xác thực, rồi tạo tệp độc quyền trong chính thư mục đang mở. Nó ghi và đồng bộ tệp trước khi đồng bộ thư mục. Chỉ khi mọi bước hoàn tất, transport mới gửi POST đầu tiên. Các lệnh PUT của TikTok và LinkedIn, cùng POST hoàn tất tải video LinkedIn, đi sau POST khởi tạo và dùng chung lần thử tải lên.

Tệp đã tồn tại chặn lần thử kế tiếp, kể cả khi tệp rỗng. Lỗi mở, ghi hay đồng bộ sổ chặn request đầu tiên và giữ tệp nếu đã tạo được. Transport giữ dấu lần thử cả khi phản hồi từ nền tảng bị mất hoặc trạng thái vẫn chưa xác định. Dấu này ghi nhận lần thử đã được giữ chỗ. Kết quả đăng cần bằng chứng riêng từ nền tảng.

Thư mục sổ phải được chuẩn bị từ trước trên hệ thống tệp có hỗ trợ đồng bộ tệp lẫn thư mục. Giữ nguyên thư mục và các thư mục cha trong suốt vòng đời sổ. Độ bền qua mất điện còn phụ thuộc vào hệ thống tệp, thiết bị lưu trữ và việc các thư mục cha đã được lưu bền. Trên Windows và các nền tảng ngoài POSIX, transport chặn gửi do chưa có cơ chế đồng bộ thư mục đã xác thực.

Trên Windows, điểm cần xác minh là tên tệp `.attempt` mới tạo còn tồn tại sau mất điện, vì transport dựa vào tên đó để chặn gửi lặp. Tài liệu `FlushFileBuffers` mô tả đồng bộ theo handle tệp và đồng bộ mọi tệp đang mở trên volume với quyền quản trị. Chưa xác minh được cách đồng bộ mục thư mục mới tạo theo đúng hợp đồng này với quyền chạy hiện tại. [Microsoft Learn về FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)

Cổng quyền production V2 hiện chặn gửi ra ngoài cho tới khi có cơ chế cấp quyền từ nguồn chính thức. Các tính năng V1 nằm ngoài phạm vi sổ này.
