# TikTok: preview video trực tiếp và inbox

Hai candidate native trong `scripts/social/channels/tiktok/direct.py` chỉ dựng yêu cầu và byte range từ dữ liệu giả. Không đọc tệp video, token, upload URL, không gọi Postiz/TikTok và không gửi bài. Registry ghi `tiktok_native` cho hai action video nhưng `live_enabled=false`; Duet/Stitch vẫn là tình huống UI/manual được lập kế hoạch, chưa có luồng thật.

Ví dụ từ gốc plugin, dùng số byte giả:

```powershell
@'
{"video_size":4194304,"chunk_size":4194304}
'@ | python -m scripts.social.cli prepare-tiktok-inbox
```

`prepare-tiktok-direct` nhận creator, revision, lựa chọn privacy, tương tác, disclosure, thời lượng và consent **giả** theo `tests/test_social_tiktok_direct.py`. Hàm `fixture_consent_digest` gắn nhãn consent giả với bản metadata, kích thước/chunk, thời lượng, creator và SHA-256 media do caller khai; thay bất kỳ giá trị nào phải tạo lại digest. Không đọc bytes và không chứng minh SHA-256 media là đúng. Các nhãn và digest này chưa xác thực tài khoản hay là sự đồng ý thật. Kết quả chứa candidate có thể dẫn tới đăng nếu bị gửi; không chuyển preview vào transport. Hiện chỉ dựng `FILE_UPLOAD`; chưa có `PULL_FROM_URL`, upload, chuyển file hoặc tùy chọn gắn nhãn nội dung AI (`is_aigc`).

TikTok quy định Direct Post phải lấy thông tin creator mới nhất, hiển thị lựa chọn khả dụng và có sự đồng ý rõ ràng trước khi khởi tạo. Trạng thái tài khoản, quyền, tính phù hợp của ứng dụng, disclosure và chính sách phải được kiểm riêng trước bất kỳ kết nối thật. TikTok cũng nêu công cụ chỉ phục vụ upload lên tài khoản của chính người dùng hoặc đội quản lý là trường hợp không được chấp nhận trong hướng dẫn Direct Post; không mặc định sản phẩm này đủ điều kiện. [Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post) · [Content Sharing Guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)

Với inbox, khởi tạo thành công chưa có nghĩa thông báo đã được chuyển. `SEND_TO_USER_INBOX` nghĩa là chờ creator; `PUBLISH_COMPLETE` theo API TikTok native nghĩa là TikTok báo creator đã hoàn tất đăng. Trạng thái đó vẫn không xác minh bài công khai; danh sách ID công khai và moderation cần đối soát riêng. Đây là diễn giải API TikTok trực tiếp; trạng thái chuẩn hóa từ Postiz có hợp đồng khác và không được trộn. [Get Post Status](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status)

TikTok dùng phép chia lấy phần nguyên và gộp phần dư vào chunk cuối; ví dụ 50.000.123 byte với chunk 10.000.000 có 5 phần. Builder dùng ngưỡng byte bảo thủ (5 MiB tối thiểu cho phần thông thường; 64.000.000 byte tối đa cho chunk ban đầu; 128.000.000 byte cho phần cuối) và tối đa 1.000 phần. Đây là phép tính fixture, không chứng nhận toàn bộ giới hạn kích thước, định dạng hay thời lượng hiện hành. Không ghi hoặc đưa `upload_url` thực vào log; URL này có thể chứa thông tin nhạy cảm. [Media Transfer Guide](https://developers.tiktok.com/docs/en/content-posting-api-media-transfer-guide)
