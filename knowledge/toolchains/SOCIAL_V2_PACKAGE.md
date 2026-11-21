# Chuẩn bị gói social V2 từ file V1

Để chuẩn bị nhiều đích từ cùng một danh sách, xem [hướng dẫn tạo lô](SOCIAL_V2_BATCH.md). Bước chuẩn bị media LinkedIn và các giới hạn upload nằm tại [SOCIAL_V2_MEDIA.md](SOCIAL_V2_MEDIA.md).

Dùng thư mục bài V1 đã có `content.md`, `publish.json` và file media cục bộ. Mỗi lần chạy tạo một thư mục mới để người duyệt mở `review.html`. Bộ đọc dùng đúng `post_content` của dòng đã chọn, kể cả hậu tố như `#2`, và đối chiếu ID content, campaign với phần đầu của Markdown.

| Nguồn V1 | Nội dung lấy từ anchor |
|---|---|
| Facebook `facebook_post` | Thân bài và `comment_1` riêng. `image_prompt` dùng cho sản xuất ảnh. |
| Facebook `reel` | Lấy phần caption để tái sử dụng cho kênh khác. Video mặc định là `short.mp4`. Đích Facebook bị chặn vì bộ gửi gói chưa có hành động đăng Reel. |
| Facebook `carousel`, `infographic` | Cần đúng một đoạn ở cấp ngoài cùng, trên một dòng bắt đầu bằng `**Caption:**` và có nội dung ngay sau nhãn. Sau dòng này chỉ chấp nhận dòng trống hoặc `---`. Cần ghi rõ file ảnh. Có thể tái sử dụng carousel cho một gói đơn với file và chữ đã chọn cho kênh đích. Gói Facebook nhiều ảnh chưa được hỗ trợ. |
| YouTube `youtube_video` | Khối mô tả theo anchor `post:youtube_desc` hoặc `post:youtube_video` mà dòng V1 trỏ đến. |
| YouTube `youtube_short` | Một dòng `**Caption:**` riêng. Đích YouTube và TikTok nhận trực tiếp nguồn video YouTube. |

```powershell
python -m scripts.social.prepare_package --source-dir .tmp/demo-v1 --post-id fixture-post --platform facebook --kind image --output-dir .tmp/demo-facebook
```

`--source-dir` là thư mục bài. `--post-id` là ID của dòng tương ứng trong `publish.json → posts[]`. Thư mục cha của `--output-dir` phải tồn tại, còn thư mục đích phải mới và nằm ngoài nguồn V1. Mặc định ảnh lấy theo `asset_ref` hoặc dùng `thumbnail.png` khi tham chiếu rỗng; video lấy theo `asset_ref` hoặc tên video YouTube mặc định. Có thể chọn file khác bằng `--media-file` bên dưới; video cần `ffprobe` trong PATH. Đường dẫn nguồn dùng dấu `/` cho cấp thư mục. Gói lưu bản sao nguyên byte và SHA-256 của media, cùng kích thước ảnh hoặc khung hình. Giới hạn mỗi tài liệu nguồn là 2 MiB và mỗi tệp media là 256 MiB.

Để chọn file khác mà không sửa `publish.json`, thêm `--media-file assets/anh-san-pham.jpg` hoặc `--media-file assets/video.mp4`, tương ứng với `--kind image` hoặc `--kind video`. File phải nằm trong thư mục nguồn và đi qua cùng kiểm tra đường dẫn, định dạng và dung lượng; tùy chọn này cũng dùng với PDF (`--kind document`). Media trong gói mới vẫn cần được duyệt cùng nội dung trước khi đăng.

Chỉ dùng thư mục nguồn cục bộ đáng tin cậy, không chọn thư mục nguồn hay thư mục cha nằm trên cây cloud. Bộ kiểm tra từ chối liên kết hoặc placeholder cloud tại các thành phần bên trong thư mục nguồn, nhưng không kiểm tra toàn bộ các thư mục cha, không bảo vệ hoàn toàn khỏi hard link hay việc tiến trình khác thay file trong lúc đọc.

Với các đích tái sử dụng nguồn Facebook, đặt nội dung đã biên tập cho đúng kênh trong một tệp `.txt` bên trong thư mục bài rồi dùng `--text-file`. LinkedIn và gói Facebook Page dạng chữ hoặc ảnh nhận bình luận đầu tiên từ tệp UTF-8 riêng qua `--comment-file`, ví dụ `--comment-file comments/facebook.txt`. Tệp phải nằm trong thư mục bài và có nội dung sau khi bỏ khoảng trắng ở hai đầu. Với Facebook Page, bình luận từ tệp được ưu tiên. Khi bỏ tùy chọn, gói Facebook tiếp tục lấy bình luận từ anchor nếu có. Truyền lại đường dẫn tệp khi kiểm lại gói với nguồn để bình luận được đối chiếu cùng nội dung đã duyệt. [Đối chiếu duyệt](SOCIAL_V2_APPROVAL.md)

Bình luận đầu tiên trên Facebook Page được hỗ trợ cho gói chữ và ảnh. Bước chuẩn bị từ chối gói video nếu anchor nguồn có bình luận đầu tiên hoặc nếu người dùng truyền `--comment-file`. Bước chuẩn bị áp dụng cùng quy tắc kiểm tra nội dung bình luận Facebook như khi gửi, cho cả tệp riêng lẫn anchor. Gói lưu bình luận với xuống dòng LF để bản duyệt khớp nội dung gửi. Quy tắc này giới hạn 20.000 ký tự sau chuẩn hóa và từ chối dấu giữ chỗ hoặc ký tự điều khiển ngoài các ngoại lệ của bộ gửi. Nếu một gói cũ chứa CRLF trong bình luận, bước đối chiếu sẽ phát hiện bản dựng lại khác gói cũ. Khi đó cần tạo lại gói và duyệt bản mới.

Với Telegram và Discord, `--kind document` nhận PDF theo `asset_ref` và kiểm tra chữ ký đầu file. Ví dụ với cùng asset V1:

```powershell
python -m scripts.social.prepare_package --source-dir .tmp/demo-v1 --post-id fixture-post --platform telegram --kind image --text-file telegram.txt --output-dir .tmp/demo-telegram
```

Để chuyển một bài V1, chẳng hạn Facebook carousel, thành album Telegram, dùng `--media-files` với 2–10 ảnh JPEG hoặc PNG tĩnh theo thứ tự đăng, tối đa 10.000.000 byte mỗi ảnh. `--caption-files` nhận đúng một đường dẫn `.txt` hoặc `.md` UTF-8 cho mỗi ảnh theo cùng thứ tự. Dùng `-` cho ảnh không có caption. Giới hạn mỗi caption là 1.024 đơn vị UTF-16. Có thể bỏ `--caption-files` và dùng `--text-file` để chỉ đặt caption cho ảnh đầu.

```powershell
python -m scripts.social.prepare_package --source-dir .tmp/demo-v1 --post-id fixture-post --platform telegram --kind image --media-files assets/cover.jpg assets/detail.png --caption-files captions/cover.txt captions/detail.txt --output-dir .tmp/demo-telegram-album
```

Với Discord, dùng `--media-files` cho 2–10 ảnh JPEG, PNG hoặc WebP tĩnh theo thứ tự gửi. Mỗi ảnh tối đa 20 MiB, tổng tối đa 24 MiB. `--text-file` là file `.txt` UTF-8 chứa nội dung chung cho một tin nhắn, tối đa 2.000 ký tự. `--caption-files` dành cho Telegram.

```powershell
python -m scripts.social.prepare_package --source-dir .tmp/demo-v1 --post-id fixture-post --platform discord --kind image --media-files assets/cover.jpg assets/detail.png --text-file captions/discord.txt --output-dir .tmp/demo-discord-album
```

Tuyến album kiểm dòng và anchor V1 như các gói khác. Các tham số chọn ảnh và caption nằm ở bước chuẩn bị V2. Gói lưu thứ tự tệp, caption đã bỏ khoảng trắng ở hai đầu và SHA-256 từng ảnh. `review.html` hiển thị caption chung của Discord phía trên danh sách ảnh hoặc caption Telegram ngay bên ảnh tương ứng. Khi dựng lại để kiểm nguồn, truyền lại file văn bản và các danh sách ảnh, caption theo đúng thứ tự đã dùng. [Đối chiếu duyệt](SOCIAL_V2_APPROVAL.md)

Mở `review.html` để xem nội dung và media. `package.json` cung cấp trạng thái `prepared_for_review`, đích, hành động, ID và anchor V1, caption và thông tin file. Facebook giữ bình luận đầu tiên ở trường riêng. Quy ước tách đích, nội dung và media dựa trên nghiên cứu Postiz tại [POSTIZ_PREVIEW.md](POSTIZ_PREVIEW.md). Lệnh chạy cục bộ và độc lập với Postiz.

Chỉ đưa vào thư mục nguồn chữ và media được phép chia sẻ với người duyệt. Gói có thể giữ metadata đã có trong byte của ảnh/video. Bộ kiểm tra dữ liệu nhạy cảm dùng quy tắc của snapshot hiện có, gồm từ chối một số mẫu URL chứa thông tin xác thực. Người chuẩn bị vẫn chịu trách nhiệm kiểm nội dung và metadata.

## Chuẩn bị cho xác thực sau khi có quyền

| Đích | Thông tin cần xác định trước |
|---|---|
| Facebook Page | Page ID, ứng dụng Meta và tài khoản người duyệt có quyền trên Page. |
| Telegram channel | Định danh channel, bot dự kiến dùng để đăng và quyền đăng trong channel dành cho bot. |
| LinkedIn account | Kiểu đích cá nhân hay tổ chức, ứng dụng LinkedIn và người có quyền cấp quyền cho mục đích đăng. |
| Threads và Instagram | ID tài khoản, ứng dụng Meta, sản phẩm đăng nhập tương ứng. Media cần URL do pipeline cung cấp và bản đối soát container. Adapter Instagram dùng Facebook Login. |
| X | ID người dùng, ứng dụng có quyền ghi và credential theo ngữ cảnh người dùng. |
| Discord | ID channel, ứng dụng bot và quyền gửi tin, đính kèm trong channel. |
| YouTube | Channel ID và quyền upload của danh tính OAuth đã đối soát với channel. |
| TikTok Inbox | Open ID của creator, quyền upload Inbox, host chuyển byte đã xác minh qua cấu hình tin cậy. |

Giữ thông tin xác thực trong kho do chủ máy quản lý theo [hướng dẫn xác thực](SOCIAL_AUTH_TEST.md). Gói dùng trạng thái chuẩn bị cục bộ, không kế thừa phê duyệt V1. Xác thực, kiểm quyền tài khoản, upload, đặt lịch và đăng cần đường triển khai riêng được cấp quyền.

## Adapter đăng Facebook Page

`scripts.social.publish_facebook_package.publish_facebook_package` định tuyến bài chữ tới `feed`, ảnh tới `photos`, video tới `videos`. Ảnh và video gửi dưới dạng tệp multipart qua transport do workflow tích hợp cung cấp. Adapter mặc định khóa; workflow phải tra bản duyệt thật, cấp `FacebookPackageApproval` gồm Page ID, phiên bản API, mã băm từ `canonical_snapshot(package)` và tham chiếu bản duyệt, cấp Page Access Token trong bộ nhớ, rồi bật `enable_dispatch`.

Gọi riêng `publish_facebook_first_comment` với `FacebookPostObservation` sau khi workflow đã đối soát ID bài chính với Page và gói vừa gửi. Phản hồi ảnh lưu `photo_id` và giữ `post_id` riêng nếu API trả về. Bước bình luận dùng nội dung trong cùng gói đã duyệt và cũng khóa mặc định.

## Adapter đăng Telegram channel

`scripts.social.publish_telegram_package.publish_telegram_package` dùng `sendMessage`, `sendPhoto`, `sendMediaGroup`, `sendVideo` hoặc `sendDocument`. Với album, adapter kiểm lại byte của từng ảnh, tạo phần đính kèm theo thứ tự và đối chiếu caption tương ứng trong từng tin nhắn trả về. Caller chuyển `TelegramPackageApproval` gồm ID bot, ID channel dạng số, mã băm gói và tham chiếu bản duyệt, rồi truyền token trong bộ nhớ. Tuyến campaign hiện có thể đối chiếu hồ sơ duyệt cục bộ. Gửi thật cần cơ chế cấp và thu hồi quyền đã xác thực, và workflow biên nhận Telegram hiện nhận gói standalone.

## Các adapter còn lại

| Kênh | Đường gửi | Điều kiện tích hợp |
|---|---|---|
| LinkedIn | `publish_channel_package.publish_linkedin_package` gửi bài chữ, ảnh hoặc video. `publish_linkedin_first_comment` gửi bình luận. | Media cần URN đã upload và bản đối soát gắn SHA-256 với author. Bình luận cần bản đối soát bài chính với author và gói. |
| X | `publish_channel_package.publish_x_package` gửi bài chữ, ảnh hoặc video. | Media cần ID đã upload và bản đối soát gắn SHA-256 với account. |
| Discord | `discord_package_workflow.run_discord_package_workflow` nhận chữ, ảnh, MP4, PDF và album ảnh từ gói chiến dịch hoặc gói độc lập. | Transport mã hóa multipart với `payload_json` và `files[n]`. Gói chiến dịch dùng lượt trực tiếp và biên nhận gắn với quyết định duyệt theo đích. Cổng gửi production vẫn đóng. [Workflow Discord](SOCIAL_V2_DISCORD_WORKFLOW.md) |
| Threads | `publish_meta_package.create_meta_package_container` và `publish_meta_package_container` gửi chữ, ảnh hoặc video. | Media cần URL HTTPS đã đối soát với file. Publish cần bản đối soát container báo `FINISHED`. |
| Instagram | Cùng hai hàm Meta cho ảnh và Reel. | Cần URL HTTPS của media và container `FINISHED`. |
| YouTube | `publish_video_package.publish_youtube_package` gửi MP4 bằng `videos.insert`. | Transport mã hóa `multipart/related`. Caller duyệt cả metadata title, category, privacy, cờ made-for-kids qua `ChannelApproval.options_digest`. |
| TikTok | `run_tiktok_package_workflow` khởi tạo Inbox và gửi MP4 theo từng đoạn byte cho gói độc lập hoặc gói chiến dịch đã đối chiếu. | Workflow dùng host upload cố định và giữ biên nhận theo mã lượt. Kết quả chuyển file xác nhận TikTok đã nhận video. Nhà sáng tạo xử lý tiếp trong ứng dụng. [Luồng TikTok Inbox](SOCIAL_V2_TIKTOK_WORKFLOW.md) |

Các adapter và transport đều khóa gửi production tại `require_production_authority`. `enable_dispatch=True`, `approval_ref`, credential và dữ liệu quan sát do caller cung cấp vẫn không mở khóa này. Workflow tích hợp cần tra bằng chứng duyệt, xác minh credential đúng tài khoản và quản lý trạng thái đối soát xuyên các lần gọi. Khi nhận `unknown` sau khi tuyến gửi được cấp quyền, workflow phải dừng và đối soát trước khi gọi lại.

Workflow có thể cấp `GuardedPackageTransport(journal_directory, attempt_key)` từ `scripts.social.publish_package_transport`. Dùng `.post_form` cho Facebook/Telegram, `.post` cho các adapter khác và thêm `.put_tiktok_chunk` cho TikTok. Mỗi thao tác POST dùng một khóa ổn định cho đúng gói, đích và bước gửi, kể cả khi tiến trình bị khởi động lại. Transport tạo dấu claim độc quyền và đồng bộ nội dung file trước khi mở HTTPS. Dấu này tồn tại sau mọi kết quả. Workflow cần lưu receipt, đối soát sau `unknown` và duy trì cùng khóa thao tác qua các lần gọi.

X, YouTube và TikTok yêu cầu `AccountObservation` từ bước đọc danh tính đã làm bằng chính credential dùng để gửi. Credential và mã SHA-256 của nó chỉ dùng trong bộ nhớ, không đưa vào gói, journal, log hoặc tham chiếu duyệt. So sánh này ràng buộc credential với lần đọc danh tính, không chứng minh quyền đăng và không cấp quyền gửi.

Transport HTTPS giới hạn host, tắt chuyển hướng và tự gửi lại, có timeout và che chi tiết lỗi. URL upload TikTok chỉ dùng lại với đúng phiên khởi tạo trong bộ nhớ. Chưa chạy xác thực, test, UAT hay gửi mạng cho các adapter này.

## Workflow kiểm nguồn duyệt và danh tính

`scripts.social.publish_package_workflow.inspect_source_approval` đọc bằng chứng G1/G2 và G3 khi campaign yêu cầu. Hàm kiểm bản ràng buộc G2 hiện có cho payload chứa `social_package_digest` khớp đúng gói V2. Hàm trả ID của bản ràng buộc và khóa thao tác xác định từ định danh bài, tài khoản, `destination_id` và lần đăng. `destination_id` bắt buộc để các đích của cùng tài khoản có khóa riêng. Khóa giữ nguyên khi sửa gói hoặc duyệt lại cùng lần đăng. Hàm tái dựng gói trong thư mục tạm cục bộ do caller chỉ định để đối chiếu nguồn và media, sau đó dọn thư mục tạm; không sửa nguồn hay cấp quyền gửi.

`read_package_account` dùng bộ đọc danh tính hiện có cho X, YouTube hoặc TikTok khi được bật rõ bằng `enable_provider_read=True` và nhận credential trong bộ nhớ. Chỉ phản hồi khớp tài khoản mới tạo `AccountObservation`. Bước này xác nhận danh tính tài khoản; quyền đăng cần bằng chứng riêng.

Workflow vẫn khóa gửi với `production_approval_generation_unavailable`, kể cả khi bằng chứng trong file V1 khớp. Dispatcher hiện có chưa bật cấp quyền production từ nguồn duyệt và ledger chỉ cấp sự kiện mới cho fixture. Bộ phân loại cổng V1 cũng chưa có X hoặc TikTok và trình ghi binding V1 buộc platform trùng với dòng nguồn. Các kênh và luồng tái sử dụng ngoài phạm vi này cần đường duyệt riêng trước khi nối gửi. Không có fallback tự đặt approval hoặc dùng dấu claim thay quyền đăng.
