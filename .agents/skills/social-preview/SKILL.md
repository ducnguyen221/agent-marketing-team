---
name: social-preview
description: Use when preparing an offline social V2 review package from local marketing output or simulating a social preview with synthetic data.
---

# Chuẩn bị gói social V2 và mô phỏng xem trước

## Phạm vi

Skill hỗ trợ chuẩn bị gói duyệt cục bộ từ file V1 hoặc từ caption và media độc lập, cùng đường mô phỏng riêng bằng dữ liệu giả. Giữ nguyên tài liệu nguồn, trạng thái và các cổng V1. Mọi thao tác của skill chạy offline. Gói và kết quả mô phỏng chỉ phục vụ xem trước.

## File độc lập và nhiều kênh

Khi người dùng đưa thư mục caption `.txt`/`.md` và media mà không có bài V1, đọc `knowledge/toolchains/SOCIAL_V2_STANDALONE.md` cho một đích. Với nhiều đích, lập manifest và dùng `knowledge/toolchains/SOCIAL_V2_STANDALONE_BATCH.md`: chọn caption, media và tài khoản/đích cho từng mục; không tự suy nội dung theo kênh. Gói có schema độc lập, chưa có bằng chứng duyệt và không tự đăng. Chỉ sử dụng nguồn cục bộ tin cậy. Đường nhận file và lệnh chưa được xác minh qua chạy thực tế.

## Chuẩn bị gói duyệt từ đầu ra marketing

1. Bắt đầu từ thư mục bài do người dùng chỉ định. Nếu chỉ biết tên chiến dịch hoặc bài, dùng cây trạm đã cấu hình theo `docs/WORKSPACE.md` và bảng Content trong `campaign.md` để xác định đúng thư mục bài. Đối chiếu `content.md`, đúng một dòng `publish.json → posts[]` theo `post_id` và file media cục bộ. Dừng nếu nguồn, ID hoặc đích còn mơ hồ, file thiếu hoặc chỉ là placeholder cloud. Giữ anchor của đúng dòng nguồn.
2. Đối chiếu bảng và ví dụ trong `knowledge/toolchains/SOCIAL_V2_PACKAGE.md` cùng `scripts/social/prepare_package.py` trước khi chọn `--platform` và `--kind`. Nguồn chính là dòng `facebook_post`; YouTube và TikTok cũng nhận dòng YouTube `youtube_video` hoặc `youtube_short`. Khi tái sử dụng nguồn Facebook cho đích khác, dùng `--text-file` trỏ tới bản chữ đã biên tập riêng theo kênh. LinkedIn có thể dùng `--comment-file`. Facebook lấy thân bài và bình luận đầu từ nội dung nguồn. Với YouTube Short, giữ anchor Short và dùng caption nguồn.
3. Với ảnh hoặc video, dùng `asset_ref` của dòng nguồn hoặc `--media-file` để chỉ rõ file đã đối chiếu với bài. Các đường dẫn file nhập tính tương đối từ thư mục bài, dùng `/` giữa các cấp. Khi tham chiếu trống, ảnh mặc định `thumbnail.png`, còn video từ dòng YouTube dùng `video.mp4` hoặc `short.mp4` theo định dạng nguồn. MP4 cần `ffprobe` trong PATH. Chọn thư mục đích mới, có thư mục cha sẵn và nằm ngoài thư mục bài. Ví dụ chạy ở gốc repo sau khi đã xác định nguồn và ID:

   ```powershell
   python -m scripts.social.prepare_package --source-dir <thu-muc-bai> --post-id <post-id> --platform facebook --kind image --output-dir <thu-muc-goi-moi>
   ```

4. Mở `review.html`, đối chiếu `package.json` và media đã sao chép với nguồn. Trả đường dẫn gói, đích, `post_id`, anchor, loại media và mục còn thiếu. Gói mang trạng thái `prepared_for_review`. Chỉ đưa vào gói nội dung và media được phép chia sẻ với người duyệt, kể cả metadata có sẵn trong file.
5. Giữ các cổng của campaign. Gói V2 cần bằng chứng duyệt gắn với đúng mã băm của gói; chỉnh gói thì phải đối chiếu lại. Workflow production hiện khóa với `production_approval_generation_unavailable`. Việc xác thực thuộc quy trình riêng trong `knowledge/toolchains/SOCIAL_AUTH_TEST.md` khi chủ tài khoản cho phép. Chủ tài khoản giữ bí mật trong kho của mình. Kết quả đọc danh tính chỉ xác nhận đích trả về; quyền đăng cần bằng chứng riêng.
6. Facebook Group đi theo luồng giao diện riêng. Với Computer Use, chỉ thao tác trên trang giả cục bộ theo mục **Thao tác UI giả** trong `knowledge/toolchains/SOCIAL_V2_FIXTURE.md`. Dùng tài khoản, nhóm và nhãn media giả; đối chiếu chúng trước khi xác nhận trong mô phỏng. Khi trạng thái là `unknown`, dừng để đối soát. `awaiting_moderation` là trạng thái chờ duyệt. Khả năng dùng giao diện trên Facebook thật chưa được xác minh, và gói Facebook Page không phải tuyến cho Group. Hướng dẫn chuẩn bị cho Group, Duet và Stitch sau khi được cấp quyền nằm ở `knowledge/toolchains/SOCIAL_COMPUTER_USE.md`; đó là quy trình dự kiến, không phải bằng chứng đã thao tác trên nền tảng thật.

## Mô phỏng bằng dữ liệu giả

1. Xác định kênh, loại đích, bài, anchor, caption, media và giờ; thiếu thông tin thì ghi thiếu, không tự đoán. Trong campaign, giữ các cổng hiện hành và không tự ghi trạng thái duyệt.
2. Chạy `python -m scripts.social.cli capabilities` để kiểm schema và chọn đường preview theo bảng dưới; đọc đúng hướng dẫn kênh để lấy mẫu input giả. Các lệnh chuẩn bị và mô phỏng nhận JSON qua stdin; không chuyển candidate sang transport. Giữ anchor của bài nguồn. Riêng chuyển đích V1 giả qua `simulate-v1-batch` hỗ trợ `facebook/infographic` → Instagram IMAGE và `facebook/reel` → Instagram REELS: chọn đúng `post_id` nguồn trong publication chung, giữ anchor `post:infographic` hoặc `post:reel` và manifest của bài đó; kết quả nêu rõ nguồn Facebook và đích Instagram. Không tự đổi tên anchor hoặc giả định chuyển đích khác đã hỗ trợ. Chi tiết và ví dụ: `knowledge/toolchains/SOCIAL_V2_ROUTES.md`.

   | Kênh / tình huống | Lệnh native và hướng dẫn |
   |---|---|
   | Facebook Page chữ, ảnh đơn, video thường | `prepare-facebook` · `knowledge/toolchains/FACEBOOK_DIRECT_PREVIEW.md` |
   | Facebook Page Reel | `prepare-facebook-reel` · `knowledge/toolchains/FACEBOOK_DIRECT_PREVIEW.md` |
   | Instagram ảnh, Reel | `prepare-instagram` · `knowledge/toolchains/INSTAGRAM_DIRECT_PREVIEW.md` |
   | LinkedIn chữ, ảnh, video | `prepare-linkedin` · `knowledge/toolchains/LINKEDIN_DIRECT_PREVIEW.md` |
   | Threads chữ, ảnh, video | `prepare-threads` · `knowledge/toolchains/THREADS_DIRECT_PREVIEW.md` |
   | TikTok video Inbox / Direct | `prepare-tiktok-inbox` / `prepare-tiktok-direct` · `knowledge/toolchains/TIKTOK_DIRECT_PREVIEW.md` |
   | YouTube video | `prepare-youtube` · `knowledge/toolchains/YOUTUBE_DIRECT_PREVIEW.md` |

   LinkedIn và Threads dùng anchor fixture đề xuất, chưa phải enum V1. `prepare-instagram` dùng `post:instagram_reel` cho Reel giả độc lập; `simulate-v1-batch` giữ `post:reel` của Facebook khi chuyển đích. TikTok CLI tạo candidate video từ metadata giả; luồng nối source giả vào lịch nằm trong `SOCIAL_V2_FIXTURE.md`. Với Discord hoặc X, `prepare` chỉ tạo candidate **tham khảo Postiz**, không phải payload native. `prepare` và `prepare-v1` luôn là đường tham khảo, kể cả khi registry có schema native; chúng không kết nối Postiz.
3. Facebook: kiểm thân bài, comment đầu và prompt ảnh tách riêng. Instagram infographic: chỉ caption một dòng rõ ràng; caption nhiều dòng hoặc thiếu thì dừng. YouTube video dài dùng `post:youtube_desc`, còn Short dùng đúng `post:youtube_short` và lấy dòng `**Caption:**`; video giả chỉ là nhãn, chưa upload hay kiểm file. SQLite fixture chỉ dùng dữ liệu giả, không chứng thực nguồn, media hoặc duyệt thật; xem `knowledge/toolchains/SOCIAL_V2_FIXTURE.md`.
4. Đọc candidate cùng warnings. TikTok inbox đang chờ creator chỉ khi kết quả giả tương ứng báo vậy; khởi tạo chưa chứng minh thông báo đã đến. Group và Duet/Stitch đã có mô phỏng UI fixture; quyền và thao tác trên nền tảng thật chưa được xác minh. Khi kết quả không rõ thì dừng đối soát, không tự gửi lại qua API. Thao tác chuột và bàn phím không bảo đảm tránh bị nền tảng phát hiện hay khóa tài khoản.
5. Khi chuẩn bị kết nối, chuyển chủ tài khoản tới `knowledge/toolchains/SOCIAL_AUTH_TEST.md`. Chủ tài khoản tự xử lý bí mật và quyền OAuth; không yêu cầu dán token vào chat. Không thực hiện kết nối, upload hay đăng trong phạm vi fixture.

## Đầu ra mô phỏng

Trả provider, loại đích, anchor, nội dung dự kiến, nhãn media giả, thời gian và warnings; phân biệt đã thử offline với chưa kiểm trên tài khoản/nền tảng. Không in bí mật hay nội dung riêng tư không cần thiết. Với source hoặc caption mơ hồ, báo nguyên nhân và dừng.
