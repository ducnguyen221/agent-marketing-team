# YouTube: xem trước metadata video giả

`prepare-youtube` dựng metadata cho bước khởi tạo upload resumable `videos.insert`; không đọc byte video, mở phiên upload, gọi Google hoặc đăng. Ví dụ từ gốc plugin:

```powershell
'{"source":"## post:youtube_desc\nMô tả giả\n","anchor":"post:youtube_desc","title":"Video giả","category_id":"22","privacy":"private","made_for_kids":false,"media_id":"fixture-video"}' | python -m scripts.social.cli prepare-youtube
```

Truyền rõ `privacy` (`private`, `unlisted`, `public`) và `made_for_kids`; không tự suy giá trị từ nội dung. Nếu gửi request thật, upload có thể tạo video; API mặc định public khi không khai privacy và `notifySubscribers` mặc định true. Preview luôn khai privacy, nhưng không đặt `notifySubscribers`; cảnh báo để người dùng biết mặc định, không suy thông báo đã gửi. [Google videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)

Tiêu đề tối đa 100 ký tự và mô tả tối đa 5.000 byte UTF-8 theo [video resource](https://developers.google.com/youtube/data/reference/rest/v3/videos); builder từ chối dấu `<`, `>`, placeholder chưa giải quyết và nội dung ẩn. Category chỉ kiểm hình thức; chưa xác minh category, ngôn ngữ, media, quyền hay kênh thực. Nhãn video chỉ là fixture, không phải tệp hoặc upload.

`prepare_youtube_native_fixture` chọn theo `post_id` trong output V1 giả: `youtube_video` dùng anchor `post:youtube_desc`, `video.mp4` và `thumbnail.png`; `youtube_short` dùng `post:youtube_short` và `short.mp4`. Mô tả Short lấy duy nhất dòng `**Caption:**`; thiếu, trùng hoặc nhiều dòng thì dừng, không đưa Hook/Thân/Chốt vào mô tả. Manifest phải khớp bài, còn `asset_ref` tùy chỉnh chưa hỗ trợ. Thumbnail video dài giữ riêng, Short không có thumbnail trong fixture; chưa upload hay gắn ảnh. Nhãn Short trong V1 không chứng minh YouTube phân loại tệp thật là Shorts: chưa kiểm nội dung, độ dài hay khung hình video.

Chưa có metadata A/S, provider schedule `publishAt`, theo dõi resumable hay đối soát. Google nêu `publishAt` quá khứ có thể khiến video phát ngay; không tự suy giờ lịch fixture là lịch YouTube. Không chuyển candidate vào transport hoặc runner V1 khi chưa có thiết kế và quyền phù hợp.
