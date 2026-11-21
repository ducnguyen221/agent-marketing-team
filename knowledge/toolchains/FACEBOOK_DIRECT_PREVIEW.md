# Facebook Page: xem trước chữ, ảnh và video bằng dữ liệu giả

`prepare-facebook` tạo candidate offline cho Page text, ảnh đơn hoặc video từ anchor `post:facebook_post`. Không đọc token, gọi Meta, upload hay đăng. Định dạng ID chỉ được kiểm cú pháp, không chứng thực Page hay quyền.

```powershell
'{"source":"## post:facebook_post\nBài giả\n\n### comment_1\nBình luận giả\n","anchor":"post:facebook_post","page_id":"123","api_version":"v27.0","media_type":"TEXT"}' | python -m scripts.social.cli prepare-facebook
```

Ảnh dùng `media_type` là `IMAGE` và `media_url` giả. [Tài liệu Meta Page Photos](https://developers.facebook.com/docs/graph-api/reference/page/photos/) mô tả `/{page-id}/photos` với URL ảnh; nếu gửi yêu cầu có thể phát ảnh. [Page Feed](https://developers.facebook.com/docs/graph-api/reference/page/feed/) dùng `/{page-id}/feed` cho bài text. Đây chỉ là mô tả yêu cầu: API version, quyền, khả năng truy cập URL và dữ liệu media chưa được kiểm.

Video thông thường dùng `media_type: VIDEO` và `media_url` giả; candidate mô tả `/{page-id}/videos` với `description` và `file_url` theo [Meta Page Videos](https://developers.facebook.com/docs/graph-api/reference/page/videos/). Meta ghi mặc định `published=true`, nên gửi candidate có thể đăng thật. Với SQLite fixture từ V1, `facebook_post` phải khai `asset_ref` `.mp4` tường minh và manifest giả khớp bài/tệp; không đổi quy ước ảnh mặc định. Đây không phải Facebook Reel, không kiểm tệp, upload, quyền hoặc URL thật.

Parser V1 tách `comment_1` và `image_prompt`: phần đầu được trả riêng, phần sau chỉ trả cờ hiện diện. Hàm `preview_comment` mô tả yêu cầu bình luận riêng, cần post ID dạng Page_Post; không tự chạy và không suy photo ID là post ID. Nếu gửi, yêu cầu bình luận có tác dụng thật.

Với `reel` của Facebook trong V1, hàm Python `prepare_facebook_native_fixture` nhận `media_type=REEL`, anchor `post:reel` và manifest giả cho `short.mp4`. Lệnh `prepare-facebook-reel` chỉ mô tả `upload_phase=start`; parser chỉ bỏ blockquote khớp chính xác hướng dẫn đầu của template V1 và từ chối blockquote khác vì mơ hồ. Registry ghi `facebook_reel_start` để tránh hiểu nhầm đã hoàn thiện upload. Đây là bước đầu theo [quy trình Reels của Meta](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api?entity=request-23987686-0b79260c-96bd-49de-875b-6076213785fc), không chứng minh đã tạo phiên hay đăng Reel.

```powershell
'{"source":"## post:reel\nReel gia\n","anchor":"post:reel","page_id":"123","api_version":"v27.0","media_id":"fixture-video-reel"}' | python -m scripts.social.cli prepare-facebook-reel
```

`ReelFixtureSession` mô phỏng riêng trong RAM các phản hồi start/upload/finish giả; URL, video ID và attempt là nhãn giả, không đọc tệp, gọi mạng hoặc xác minh tài khoản. `PUBLISHED` chỉ nằm trong request giả, phản hồi finish thành công vẫn là `processing_unverified`. Mất phản hồi finish chuyển `unknown` và không lặp trên cùng đối tượng. Phiên RAM này chưa liên kết trực tiếp ledger.

Ledger SQLite fixture có luồng Reel riêng: `claim_due` tạo attempt và tiến trình giả cùng giao dịch; các phương thức `reel_accept_start`, `reel_accept_upload`, `reel_accept_finish`, `reel_finish_unknown` kiểm lại intent, attempt, Page/video và snapshot. `reel_mark_unknown` ghi nhận mất phản hồi START hoặc upload theo phase và video tương ứng; caller phải xác định worker giả đã dừng trước khi đánh dấu. `processing_unverified` không chứng minh đã đăng; `unknown` không tự nhận lịch lại. Luồng Reel được bổ sung từ schema fixture v3; bản khởi tạo hiện tại là v6 và chỉ dùng DB thử rỗng. DB fixture v2 bị từ chối, không tự di trú. Chưa có upload/finish thật hay đối soát provider.

`reel_candidate(intent_id, attempt=...)` dựng lại preview phù hợp phase từ snapshot và video giả đã lưu; đọc lại nhiều lần không thay đổi trạng thái và không phải quyền gửi hay bằng chứng đã gửi. Preview phản ánh thời điểm đọc và có thể đã cũ khi connection khác chuyển phase; giao dịch đọc dùng `BEGIN IMMEDIATE` nên có thể chờ hoặc chặn ghi ngắn hạn. Trạng thái `unknown` hoặc `processing_unverified` không trả candidate. Không chuyển candidate này cho transport thật.

Nội dung giữ Markdown thô; preview không chứng nhận đã làm sạch, không chuyển định dạng hay qua QA. Luồng `prepare_facebook_native_fixture` nối candidate với SQLite fixture từ output V1 giả, không kế thừa review V1; luồng tham khảo cũ vẫn tồn tại. Chưa có nhiều ảnh, Group, OAuth, upload, xác thực hoặc dispatch live. Group là tình huống giao diện/người dùng, không suy quyền từ Page.
