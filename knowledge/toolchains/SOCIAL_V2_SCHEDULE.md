# Lịch đăng theo đích của Social V2

[Bộ lưu lịch](../../scripts/social/schedule_v2.py) giữ ý định đăng, thời điểm, trạng thái nhận việc và kết quả theo đích trong `schedule.json`. [CLI bản nháp](../../scripts/social/schedule_draft_cli.py) sử dụng bộ lưu này để ghi và xem lịch cục bộ. Luồng cấp quyền production và quản lý cổng duyệt tiếp tục thuộc quy trình hiện hành. [Hợp đồng xác minh nguồn](SOCIAL_V2_APPROVAL.md)

## Tạo và xem bản nháp từ gói đã chuẩn bị

Chọn một thư mục rỗng, cục bộ, tin cậy nằm trong vùng tạm và đặt tên bắt đầu bằng `social-schedule-v2-`. Truyền đường dẫn tuyệt đối cho `--directory`. Trong ví dụ PowerShell sau, `$draft` là đường dẫn đó, `$package` là thư mục [gói Facebook Page đã chuẩn bị](SOCIAL_V2_PACKAGE.md), và `$intentId` là `intent_id` mà `put` trả về. Giá trị `123456789` và `v23.0` dùng để minh họa định dạng.

```powershell
python -m scripts.social.schedule_draft_cli --directory $draft init
'{"api_version":"v23.0"}' | python -m scripts.social.schedule_draft_cli --directory $draft put --package-dir $package `
    --station-id demo-station --channel-id demo-channel --campaign-id demo-campaign `
    --content-id demo-content --account-id 123456789 --destination-id 123456789 `
    --occurrence-key demo-occurrence --scheduled-at 2026-11-23T09:00:00+07:00 --timezone Asia/Ho_Chi_Minh `
    --privacy public --options-stdin
python -m scripts.social.schedule_draft_cli --directory $draft get $intentId
python -m scripts.social.schedule_draft_cli --directory $draft due
```

`put` đọc `post_id`, nền tảng và thao tác từ gói rồi dùng bộ kiểm tuyến V2 của dispatch cho trường định danh đích, tùy chọn và tệp đính kèm. Nếu bộ kiểm chặn tuyến, CLI trả `status: blocked` và mã thoát `2` trước khi tạo hoặc cập nhật mục lịch. Station, channel, campaign, content, tài khoản và đích là định danh bên gọi khai báo. `put` và `get` trả `source_status: unverified` vì CLI chưa xác minh nguồn chiến dịch, tài khoản hay cổng duyệt. Lệnh tính `package_sha256` theo biểu diễn chuẩn của manifest, kiểm byte của tệp đính kèm theo manifest và có thể đối chiếu mã băm đã biết qua `--expected-package-sha256`.

Truyền quyền riêng tư qua `--privacy` và một object JSON qua stdin bằng `--options-stdin`. Dùng `{}` nếu tuyến không có tùy chọn. Nếu object có trường `privacy`, giá trị phải khớp `--privacy`. Dùng giá trị công khai được phép lưu trong bản nháp. `get` hiển thị `snapshot.review_digest` và các trường lịch đã dùng để tính nó. Mã băm này dùng cùng biểu diễn chuẩn với bản duyệt V2, gồm phạm vi G2, nền tảng, loại đích, tài khoản, đích, lần đăng, thao tác, mã băm gói, thời điểm, múi giờ, quyền riêng tư và tùy chọn. Bản nháp lưu các giá trị khai báo để đối chiếu với nguồn chiến dịch.

Để đối chiếu với nguồn chiến dịch hiện tại, cung cấp `--schedule-directory` và `--schedule-intent-id` khi dùng `check_package_readiness` với `--dispatch-context-stdin` hoặc `--target-review-stdin`. Bộ kiểm xác minh tùy chọn theo tuyến trước khi tính lại mã băm và so với bản ghi hiện tại. Kết quả khớp trả `schedule_review: matched_current_snapshot` và `schedule_status` tại thời điểm đọc. Mục khớp nhưng đã rời `pending` trả `schedule_intent_not_pending`. Mục cũ trả `schedule_review_required`, mục khác nội dung trả `schedule_review_digest_mismatch`. Kết quả luôn giữ `status: blocked`. [Bối cảnh duyệt chính xác](SOCIAL_V2_APPROVAL_CONTEXT.md)

Với gói campaign Telegram hoặc Discord gồm nhiều ảnh, `put` giữ thao tác `post_image_album`. Bộ đọc theo từng nền tảng kiểm thứ tự, giới hạn kích thước và SHA-256 của từng ảnh trước khi ghi lịch. Mã băm manifest gắn lịch với đúng danh sách ảnh và caption trong gói.

Khi dời giờ một mục đang chờ, gọi lại `put` với cùng định danh và `occurrence_key`. Kết quả `intent_returned` trả mã của mục vừa ghi hoặc mục đã khớp snapshot, kể cả khi mục khớp đã được nhận hoặc đóng. Dùng `get` để xem snapshot chuẩn hóa, revision, trạng thái và binding hiện tại. `due` chỉ liệt kê mã các mục đang chờ đã đến giờ. CLI chưa được chạy thử.

## Kiểm tra hàng loạt các mục đã đến giờ

`readiness` nhận một sổ lịch có sẵn và một tệp JSON cục bộ ánh xạ từng `intent_id` từ `put` hoặc `due` tới nguồn cần kiểm. Dùng đường dẫn tuyệt đối cho tệp JSON và bốn thư mục trong mỗi mục. Đây là ví dụ một mục với mã và đường dẫn minh họa.

```json
{
  "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef": {
    "campaign": "C:/work/station/channel/campaign",
    "package_dir": "C:/work/social-packages/post-a",
    "approval_directory": "C:/work/social-review",
    "temporary_parent": "C:/work/temp"
  }
}
```

Thêm các trường tùy chọn `text_file`, `comment_file`, `media_file`, `media_files` hoặc `caption_files` nếu đã dùng khi chuẩn bị gói. Các tên tệp là selector tương đối với thư mục bài V1 và giữ đúng thứ tự ban đầu. Hai trường số nhiều nhận mảng chuỗi JSON. Chọn một trong `media_file` và `media_files`. Thư mục tạm phải nằm ngoài thư mục chiến dịch, gói, nhật ký duyệt và sổ lịch.

```powershell
python -m scripts.social.schedule_draft_cli --directory $draft readiness --manifest $manifest
```

Lệnh dùng cùng bộ lọc với `due()` và chụp các bản ghi đến hạn cùng mốc UTC dưới một khóa sổ. Với từng mục, lệnh lấy phạm vi, đích, giờ và tùy chọn từ bản chụp, dựng lại bản duyệt từ nguồn V1 và gói, rồi đối chiếu mã băm với snapshot lịch. Lệnh cũng đọc quyết định gần nhất trong nhật ký duyệt V2 và kiểm tra mã tham chiếu của quyết định có đổi trong lượt kiểm hay không. Trước và sau khi kiểm nguồn, mục phải còn `pending`, đến hạn theo mốc UTC chung và giữ nguyên binding cùng revision của bản chụp. Kết quả đối chiếu bị loại khi bất kỳ điều kiện nào thay đổi.

Đọc `items[]` để tìm lý do theo từng mã lịch. Ví dụ `readiness_source_mapping_missing` báo thiếu mục trong JSON, `invalid_or_unavailable_readiness_source` báo đường dẫn hoặc trường nguồn không hợp lệ, còn `source_or_approval_check_failed` báo bộ kiểm không xác minh được nguồn hoặc bằng chứng duyệt. Mục có `schedule_review: matched_current_snapshot` trả trạng thái quan sát của nhật ký duyệt trong `approval_binding` (`missing`, `revoked`, `stale` hoặc `matched`). Lỗi đọc manifest hoặc chụp sổ ban đầu trả mã thoát `2`. Mã thoát `3` có nghĩa lệnh đã trả báo cáo, kể cả danh sách rỗng hoặc lỗi đọc lại một mục trong sổ. Báo cáo luôn là `blocked` và chỉ phản ánh các lần đọc cục bộ, giữa các nguồn không có giao dịch xuyên suốt. Lệnh chỉ tạo tệp làm việc trong thư mục tạm để dựng lại gói. Lệnh không ghi sổ, sửa V1, nhận việc hoặc gửi bài. CLI chưa được chạy thử.

## Định danh và lịch

- Dùng một thư mục rỗng, tin cậy do caller phân bổ ngay bên dưới thư mục tạm cục bộ với tiền tố `social-schedule-v2-`. Truyền đường dẫn tuyệt đối của cả hai qua `ScheduleStore(directory, isolated_parent=parent)`. `initialize()` tạo mốc khóa độc quyền trong thư mục rỗng và tạo sổ một lần. Khi mở lại, dùng cùng cặp đường dẫn. Nếu sổ mất mà mốc khóa vẫn còn, quá trình khởi tạo lại bị chặn.
- `put` nhận station, channel, campaign, content, post, platform, account, destination và `occurrence_key`. Giữ nguyên `occurrence_key` khi dời giờ. Hai đích của cùng bài có hai trạng thái riêng. Đổi account cho cùng đích và lần đăng bị chặn. Đường UI hoặc API do lớp gửi chọn và không tham gia khóa.
- Các lệnh gọi `ScheduleStore.put` trước đây truyền `identity`, `scheduled_at`, `timezone_name`, `package_sha256` và `action`. Từ phiên bản có mã băm bản duyệt, bên gọi phải truyền thêm ba đối số theo tên `destination_kind`, `privacy` và `delivery_options`. Cả ba đều bắt buộc, không có giá trị mặc định. Bên gọi lấy loại đích từ gói, truyền quyền riêng tư chủ định và truyền các tùy chọn hợp lệ của tuyến. Dùng `delivery_options={}` cho tuyến không có tùy chọn.
- Truyền dấu SHA-256 của gói, thao tác nghiệp vụ, giờ ISO 8601 có offset và tên múi giờ IANA. Ví dụ `2026-11-23T09:00:00+07:00` đi với `Asia/Ho_Chi_Minh`. Khi ghi lịch, sổ đối chiếu offset với quy tắc múi giờ và từ chối giờ địa phương không tồn tại. Offset giúp xác định lần nào khi một giờ địa phương lặp lại. Khi đọc lại, sổ dùng UTC và offset đã lưu để bảo toàn giờ đã duyệt kể cả sau khi cập nhật dữ liệu múi giờ.
- Ghi lại snapshot y hệt là thao tác lặp an toàn. Đổi giờ, gói, thao tác, quyền riêng tư hoặc tùy chọn khi còn `pending` tăng revision và tạo binding mới, kể cả khi sau đó đổi về nội dung cũ. Binding gắn với mã sổ được sinh khi khởi tạo, nên hai sổ được khởi tạo riêng có binding khác nhau cho cùng nội dung. Lấy binding hiện tại qua `get`. `due` chỉ tìm mục đến giờ. Quyền nhận việc còn phụ thuộc `claim_due`.
- Sổ cũ vẫn đọc được với binding và trạng thái đã lưu. Mục cũ còn `pending` cần `put` lại với cùng định danh và đủ dữ liệu duyệt để sinh revision mới trước khi có thể nhận việc. Mục cũ đã nhận hoặc đóng giữ nguyên lịch sử.

## Quyền nhận việc và kết quả

| Thao tác | Hành vi |
|---|---|
| `claim_due` | Giữ khóa, kiểm mã băm bản duyệt, đối chiếu binding và giờ từ bản ghi hiện tại, rồi gọi bộ tra cứu duyệt tin cậy cho đúng binding. Một mã chứng cứ còn hiệu lực là đầu vào cho chuyển `pending` sang `submitting`. Bên gọi chỉ nhận mã attempt sau khi ghi hoàn tất. |
| `revoke` | Đóng mục `pending` theo binding hiện hành. Nếu claim đã ghi `submitting`, thao tác thu hồi trả lỗi để người vận hành đối soát lượt đang xử lý. |
| `finish` | Kiểm mã attempt của đúng đích rồi ghi `published`, `failed` hoặc `unknown` cùng mã tham chiếu kết quả. Viết lại đúng kết quả là thao tác lặp an toàn. |
| `record_unknown_evidence` | Lưu mã biên nhận phục vụ đối soát một attempt ở trạng thái `unknown`. Giữ nguyên trạng thái và mã kết quả gốc. |

Bộ lưu lịch không cấp mã chứng cứ và repo chưa nối bộ tra cứu duyệt production. Bên tích hợp tương lai phải lấy mã từ nguồn phê duyệt có xác thực, còn hiệu lực và đúng snapshot. Bộ tra cứu thực hiện việc đọc dưới khóa, cần chạy nhanh và tránh gọi ngược lại sổ. Nếu thiếu bằng chứng, trả về `None` để chặn. Một quyết định thu hồi tại nguồn duyệt sau thời điểm kiểm cần được đồng bộ với cơ chế gửi và điểm chặn production của hệ thống.

Khi tiến trình mất phản hồi, giữ `submitting` cho đến khi người vận hành ghi `unknown` theo mã attempt. Mọi trạng thái sau claim đều chặn claim lại.

Để ghi nhận dữ kiện đối soát, truyền `ProviderEvidence(intent_id, binding, attempt_id, provider_id, receipt_ref, reported_outcome)` vào `record_unknown_evidence(intent_id, evidence=...)`. Các trường đều là chuỗi. `intent_id`, `binding` và `attempt_id` phải khớp bản ghi hiện tại. Binding gắn với snapshot đầy đủ, bao gồm tài khoản và đích. `provider_id` nhận `postiz` hoặc tên trùng nền tảng đã lưu trong các giá trị `discord`, `facebook`, `instagram`, `linkedin`, `telegram`, `threads`, `tiktok`, `x`, `youtube`. `receipt_ref` là SHA-256 viết thường của định danh biên nhận đã được lọc để loại dữ liệu nhạy cảm. `reported_outcome` mô tả kết quả bên gọi ghi nhận và có thể là `published`, `failed` hoặc `unknown`. Mỗi cặp provider và biên nhận được ghi một lần cho attempt. Gửi lại đúng dữ liệu là thao tác lặp an toàn. Gửi một kết quả khác cho cùng cặp trả lỗi.

Sổ chỉ đối chiếu liên kết và lưu tham chiếu, còn xác thực biên nhận với provider cần một lớp tích hợp riêng. Phản hồi tiếp nhận yêu cầu, 404 và timeout đều cần giữ trạng thái `unknown` trong luồng đối soát. Chỉ truyền định danh tham chiếu vào sổ. Lưu nội dung duyệt, payload, credential và log người dùng ở kho có quyền phù hợp.

## Phạm vi vận hành hiện tại

Khóa hệ điều hành phối hợp các tiến trình tuân thủ API trên một máy và một thư mục. Giữ nguyên tệp khóa suốt vòng đời của sổ. Trên các hệ POSIX hỗ trợ đồng bộ thư mục, API đồng bộ tệp tạm, thay thế tệp cùng thư mục và đồng bộ thư mục trước khi trả mã attempt. Windows có thể lưu và đọc dự thảo. `claim_due` dừng với `durable_claim_unavailable_on_this_platform` vì chưa có cơ chế xác nhận độ bền tương đương cho lần thay thế tệp. Xử lý lỗi ghi như một lượt cần đọc lại và đối soát.

Trước khi mở `claim_due` trên Windows, cần xác minh thao tác thay thế cùng thư mục giữ được cả trạng thái `submitting` lẫn mã attempt qua mất điện, vì việc khôi phục trạng thái `pending` có thể cho nhận việc lần hai. Microsoft nêu rõ bảo đảm flush của `MOVEFILE_WRITE_THROUGH` cho lần di chuyển bằng sao chép rồi xóa. Tài liệu đó chưa đủ để xác nhận thao tác thay thế cùng thư mục đáp ứng đầy đủ hợp đồng của sổ trên máy đích. [Microsoft Learn về MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)

Luồng xem trước trên Windows có thể dùng `initialize` và `put` để lưu lịch theo đích. `due` trả danh sách mã đã đến giờ. Đọc lại từng mã bằng `get` để hiển thị snapshot, binding và trạng thái hiện tại, vì lịch có thể đã đổi giữa hai lời gọi. Kết quả chỉ dùng để xem lịch. `claim_due` trả lỗi trước khi gọi bộ tra cứu duyệt hoặc ghi mã attempt.

Điều kiện mở nhận việc trên Windows là kiểm chứng trên hệ tệp và cấu hình lưu trữ dự kiến dùng. Hai tiến trình cùng nhận một binding chỉ được có tối đa một tiến trình nhận mã attempt. Nếu lỗi ghi xảy ra trước khi xác nhận, bên gọi phải nhận lỗi và đọc lại sổ để đối soát. Sau khi đã trả mã attempt và xảy ra mất điện, sổ mở lại phải giữ đúng `submitting` và mã đã trả, hoặc dừng với lỗi để đối soát. Áp cùng kiểm tra độ bền cho `finish` và `record_unknown_evidence`, kể cả khi bên gọi gửi lại cùng dữ liệu. Các điều kiện này chưa được kiểm thử trên Windows.

Ở POSIX, `put`, `finish` và `record_unknown_evidence` đồng bộ lại thư mục trước khi xác nhận một yêu cầu lặp, kể cả khi tệp hiện tại đã chứa dữ liệu của yêu cầu trước. Ghi nhận dữ kiện đối soát cũng yêu cầu độ bền này, nên thao tác dừng trên Windows. Checksum phát hiện dữ liệu sổ sai lệch. Kiểm tra bản ghi đối chiếu cấu trúc, khóa, binding và trạng thái với các trường đã lưu. Nguồn phê duyệt và bằng chứng kết quả vẫn do bên tích hợp xác thực.

Sổ yêu cầu ổ cục bộ tin cậy và thư mục cha đã tồn tại ổn định. Trên POSIX, khởi tạo đồng bộ thư mục cha để lưu bền mục nhập của thư mục sổ. Đường dẫn qua `.secret` bị chặn. Việc sao chép nguyên sổ giữ cả mã sổ và binding. Việc khôi phục phiên bản cũ có thể làm mất dấu attempt. Cả hai tình huống cần quy trình đối soát riêng trước khi sử dụng lại. Chưa chạy kiểm thử đa tiến trình, mất điện, tích hợp nguồn duyệt hoặc UAT. Việc đưa vào trạm thật còn phụ thuộc chứng minh độ bền trên máy đích và cơ chế để mỗi lần đăng có đúng một chủ sở hữu giữa V1 và V2.
