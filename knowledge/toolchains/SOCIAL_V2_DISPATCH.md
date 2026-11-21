# Chuẩn bị tuyến gửi cho gói social V2 độc lập

`scripts/social/dispatch_package_v2.py` đối chiếu gói độc lập `social-standalone-package/1` với workflow tương ứng. Lệnh kiểm tra mã SHA-256 của manifest theo dạng chuẩn, tài khoản, đích, mã lần gửi và byte tệp đính kèm. Đầu ra JSON chứa workflow được chọn, bộ dữ liệu đã gắn kết và mã SHA-256 của bộ dữ liệu đó.

| Nền tảng | Tuyến có thể chuẩn bị | Tuỳ chọn bắt buộc |
|---|---|---|
| Facebook | Page, chữ, ảnh hoặc video thường | `--api-version` |
| Telegram | Channel, chữ, ảnh, album ảnh, video hoặc PDF | ID bot và ID channel riêng |
| LinkedIn | Tài khoản cá nhân, chữ, ảnh hoặc video | `--api-version` |
| X | Tài khoản, chữ, ảnh hoặc video | Dùng cùng ID cho tài khoản và đích |
| YouTube | Channel, tải video | `--title`, `--category-id`, `--privacy` và `--made-for-kids` hoặc `--no-made-for-kids` |
| TikTok | Profile, tải video vào Inbox | Dùng cùng ID cho tài khoản và đích |
| Threads | Tài khoản, bài chữ | `--api-version` |
| Discord | Guild channel, chữ, ảnh, video hoặc PDF | `--guild-id`, cùng ID bot và ID channel riêng |

```powershell
python -m scripts.social.dispatch_package_v2 ./out/package --package-digest <digest> --account-id <id> --destination-id <id> --occurrence-id <occurrence>
```

Dùng dấu ngoặc giữ chỗ trong ví dụ để xác định giá trị cần thay. Thay tên tệp và thêm đúng các cờ theo bảng trước khi chạy. Kết quả hợp lệ có `status=blocked` và `reason=production_approval_generation_unavailable`. Lỗi dữ liệu hoặc tuyến trả mã thoát 2. Mã `adapter_options_digest` hiện có cho metadata YouTube, đích Discord và lần tải vào Inbox TikTok.

Facebook Group, Facebook Reel và TikTok Direct Post bị từ chối tường minh. Ảnh và video trên Instagram hoặc Threads cần nguồn lưu trữ từ xa bất biến đã xác minh, hiện chưa có. Một số workflow gốc yêu cầu POSIX để mở nhật ký gửi bền vững. Lệnh chuẩn bị tuyến chỉ kiểm tra gói cục bộ.

Mã gắn kết chỉ nhận diện dữ liệu, còn quyền gửi hiện bị chặn bởi `require_production_authority()`. Các lớp approval của adapter có thể được khởi tạo từ caller, vì vậy mã này không chuyển chúng thành bằng chứng duyệt. Việc nối lời gọi gửi thật cần bộ cấp quyền đọc bằng chứng đã lưu, xác minh đúng mã gói, đích, lần gửi và tuỳ chọn rồi mới chuyển credential trong bộ nhớ tới workflow. Lệnh hiện tại không nhận credential, không ghi approval và không gọi nền tảng.
