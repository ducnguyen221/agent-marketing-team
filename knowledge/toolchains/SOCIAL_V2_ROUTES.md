# Chọn nhanh đường mô phỏng social V2

Tất cả các đường dưới đây chỉ dùng dữ liệu giả và không đăng. [Hướng dẫn fixture đầy đủ](SOCIAL_V2_FIXTURE.md) có các ví dụ và ràng buộc.

| Tình huống giả | Đường dùng | Đầu ra và giới hạn |
|---|---|---|
| Facebook Page chữ, ảnh hoặc video thường | `prepare-facebook` | Candidate Page; video thường không phải Reel. [Chi tiết](FACEBOOK_DIRECT_PREVIEW.md) |
| Facebook Page Reel | `prepare-facebook-reel` | Candidate bước START; chưa upload hoặc hoàn tất Reel. [Chi tiết](FACEBOOK_DIRECT_PREVIEW.md) |
| YouTube video dài | `prepare-youtube`, anchor `post:youtube_desc` | Candidate metadata, chưa upload. [Chi tiết](YOUTUBE_DIRECT_PREVIEW.md) |
| YouTube Short | `prepare-youtube`, anchor `post:youtube_short` | Lấy duy nhất dòng `**Caption:**`; không đưa kịch bản vào mô tả. Chưa xác nhận phân loại Shorts. |
| Instagram ảnh hoặc Reel | `prepare-instagram` / `simulate-v1-batch` | Preview container Facebook Login; tuyến ảnh/Reel V1 có session và transport giả hai bước trong SQLite v6. Container và ID bài giả tách biệt; chưa upload hoặc đăng thật. [Chi tiết](INSTAGRAM_DIRECT_PREVIEW.md) |
| LinkedIn chữ, ảnh hoặc video | `prepare-linkedin` | Candidate trực tiếp; media chỉ là nhãn giả. Ledger SQLite fixture từ v4 lưu receipt `201` giả và quan sát đọc lại; bộ gửi giả trong `scripts/social/linkedin_fixture_transport.py` mô phỏng nhận hoặc mất phản hồi, không gọi mạng. Fixture v3 vẫn mở được nhưng không claim LinkedIn native. Không chứng minh bài thật đã đăng. [Chi tiết](LINKEDIN_DIRECT_PREVIEW.md) |
| Threads chữ, ảnh hoặc video | `prepare-threads` | Candidate trực tiếp, chưa gửi tới Meta. [Chi tiết](THREADS_DIRECT_PREVIEW.md) |
| TikTok video Inbox hoặc Direct | `prepare-tiktok-inbox` / `prepare-tiktok-direct` | Candidate video giả; khởi tạo không chứng minh creator đã nhận hay công khai. [Chi tiết](TIKTOK_DIRECT_PREVIEW.md) |
| Discord chữ | `prepare-discord` | Candidate native giả, cố định `allowed_mentions.parse=[]`; chưa kiểm bot, channel hay gửi. |
| Telegram channel chữ | `prepare-telegram` / `simulate-v1-batch` | Candidate `sendMessage` giả; bot purpose `publish` tách với bot duyệt. Có transport giả trong bộ nhớ, không gửi thật. |
| Telegram channel ảnh / video | `simulate-v1-batch` | Facebook infographic → `sendPhoto`; YouTube Short → `sendVideo`. Có transport và response giả; media chỉ là nhãn, chưa upload hoặc xác minh file thật. |
| X chữ độc lập | `prepare-x` | Candidate trực tiếp từ text giả; chưa kiểm giới hạn có trọng số hay quyền tài khoản. |
| X chữ từ Facebook V1 | `simulate-v1-batch` | Candidate trực tiếp với nội dung biên tập riêng; chưa kiểm giới hạn có trọng số hay quyền tài khoản. |
| X chữ kèm một ảnh hoặc video từ Facebook V1 | `prepare-x-v1-media` / `simulate-v1-batch` | Preview riêng hoặc mô phỏng lịch với quan sát media giả; chưa upload hay xác thực media. |
| Một source, nhiều đích để xem candidate | `prepare-batch` | Trả candidate trong RAM; không lưu intent sau khi lệnh kết thúc và không cấp grant. |
| Mô phỏng sự kiện nhiều đích | `simulate-batch` | Grant, scan và claim đều là giả; `submitting` không có nghĩa nền tảng đã nhận. |
| Một `publish/2` giả cho nhiều đích V1 | `simulate-v1-batch` | Facebook, YouTube, Facebook infographic/Reel → Instagram, YouTube Short → TikTok, và Facebook post → LinkedIn/Threads/Discord/X/Telegram text đã biên tập. LinkedIn có thể nhận một ảnh hoặc video giả được khai tường minh và gắn với asset nguồn. Giữ ID, anchor nguồn; kết quả chuyển đích nêu `source_binding`. |
| Facebook Group, TikTok Duet/Stitch | Simulator UI fixture, xem mục **Thao tác UI giả** trong hướng dẫn đầy đủ | Không dùng API Page thay Group; chưa thao tác trên nền tảng thật. |

`python -m scripts.social.cli capabilities` chạy trực tiếp; các action `prepare-*` và `simulate-*` cùng CLI nhận JSON qua stdin. Chỉ đưa dữ liệu giả vào lệnh. Không coi trạng thái fixture là duyệt, lịch hoặc kết quả đăng thật.

`preview-v1-file-batch` dựng các candidate V1 giả theo đích mà không mở kết nối SQLite; xem ví dụ và giới hạn ở [hướng dẫn fixture](SOCIAL_V2_FIXTURE.md). Đường này chưa lưu phiên hoặc chạy transport; các lệnh `simulate-*` hiện vẫn dùng SQLite trong bộ nhớ.

Với LinkedIn media từ V1, manifest và quan sát `AVAILABLE` chỉ là nhãn do caller cung cấp: không chứng minh byte file đã upload, owner hoặc quyền đăng. SQLite fixture từ v5 lưu ràng buộc giữa media URN, owner và asset nguồn để phát hiện mâu thuẫn trong cùng một DB, kể cả giữa nhiều batch; không đối chiếu được giữa các DB độc lập. Fixture v3/v4 cũ không được tự di trú và không hỗ trợ chuẩn bị hoặc claim tuyến media V1 này.

Transport Telegram giả ở `scripts/social/telegram_fixture_transport.py` ghi nhận candidate và bot giả cùng attempt, sau đó đối chiếu response giả với kênh và loại nội dung. `file_id` trả về chỉ là nhãn, chưa có đối chiếu với byte hoặc file thật. Phản hồi mâu thuẫn là `unknown`; không tự gửi lại.

Với Instagram V1, SQLite fixture v6 giữ riêng container và media ID giả. Transport giả `scripts/social/instagram_fixture_transport.py` chỉ cho publish sau quan sát `FINISHED`; mất phản hồi ghi `unknown`. Binding của fake nằm trong bộ nhớ và không tự phục hồi sau khi tiến trình fake dừng; reopen DB chỉ khôi phục trạng thái đã lưu. Các ID và trạng thái không chứng minh Instagram thật đã nhận, tải hoặc hiển thị media. DB fixture v3–v5 vẫn mở được và không tự di trú; session Instagram V1 mới cần DB thử v6.

Bộ điều phối Python `scripts/social/multichannel_fixture_dispatch.py` chỉ nhận danh sách intent giả và ba loại transport giả Instagram, LinkedIn, Telegram. Nó không tự cấp grant; mỗi đích được claim riêng, nên một đích `unknown` không hoàn tác các đích khác. Instagram `waiting` có thể quan sát tiếp với fake còn giữ binding, không tạo lại container. `already_accepted` cho biết intent đã được ghi nhận khi đối soát, không xác định worker nào đã thực hiện các bước giả. Lỗi SQLite truyền về caller; các intent đã claim cần được kiểm tra trước khi tiếp tục. Chức năng này chưa có CLI hay scheduler và không cho biết trạng thái tài khoản thật.
