# Thử nối nội dung và media V1 với preview V2

Đây là bộ thử trong bộ nhớ với đầu vào giả. Không mở tệp media, không đọc trạm chiến dịch, không upload, không tạo lịch và không đăng. Preview không thừa hưởng duyệt V1; ID trông giống nhau không chứng minh đúng thương hiệu, tài khoản hay quyền.

## Cách chạy

Tại thư mục plugin:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_social_v2_v1_binding.py tests/test_social_v2_fixture_assets.py
```

Hai file test là ví dụ đầy đủ về source `content/1`, đối tượng `publish/2`, post con, manifest media giả và lời gọi `preview_v1_with_assets_fixture`. Không thay nhãn `fixture-*` bằng ID thật để dùng như một đường upload.

Định hướng mới ưu tiên Markdown/JSON V1 làm nguồn và preview không cần database; bộ lưu phiên JSON V2 mới ở mức prototype. Các đoạn dưới nhắc SQLite mô tả backend thử nghiệm hiện có, không phải yêu cầu lưu nội dung hay quyết định triển khai live.

Đã có prototype Python `scripts/social/json_session_fixture.py` cho một phiên giả trong thư mục tạm cục bộ do caller tin cậy quản lý. Phiên `/1` hỗ trợ tạo, mở lại, cấp grant giả, claim và ghi trạng thái thủ công; `claim_due` đối chiếu giờ giả, key và digest, nhưng attempt thủ công và attempt theo giờ không được phân biệt khi mở lại nên không dùng làm căn cứ gửi. Phiên `/2` tách riêng đường LinkedIn fake bên dưới. Khóa OS chỉ phối hợp các tiến trình cùng dùng một file phiên; `submitting` và `unknown` không được claim lại. Giữ nguyên file khóa trong thư mục tạm suốt đời phiên. Chỉ dùng dữ liệu giả, không dùng trạm thật hoặc tài khoản thật; chưa có CLI hay scheduler.

Giới hạn: không sao chép, khôi phục bản JSON cũ hoặc dùng đồng thời nhiều phiên cho cùng occurrence rồi coi như chống trùng; không có hàng rào chung với V1. Hash không chứng minh người duyệt hay nội dung thật, và mã không chống tiến trình không tin cậy sửa thư mục. Mất điện, filesystem mạng/cloud và các nền tảng ngoài Windows chưa được nghiệm thu. Lỗi ghi sau thay file có thể để kết quả chưa rõ; mở lại để kiểm, không tự claim/gửi lại. Các thử nghiệm này chưa thay thế SQLite fixture hiện hữu.

Phiên `social-json-fixture/2` tạo bằng `FixtureJsonSession.create(..., delivery_fixture=True)` có thêm `send_due_linkedin`: chỉ nhận `FakeLinkedInTransport`, đối chiếu grant giả, key, digest và giờ giả, ghi attempt trước lời gọi fake rồi phân tích receipt `201` và URN. Receipt lưu attempt, author và readback chưa xác minh; URN lặp trong một phiên chuyển intent sau sang `unknown`. Nếu lỗi lưu sau lời gọi, attempt giữ `submitting` và bị chặn gửi lại; `mark_delivery_unknown` chỉ đánh dấu lại đúng key/attempt sau khi kiểm rằng worker cũ đã dừng. Phiên `/1` vẫn đọc được nhưng không dùng đường gửi `/2`; `/2` không cho claim/finish thủ công.

Khi batch fixture có Telegram và không có Instagram, phiên dùng schema `/3`: `send_due_telegram` nhận đúng fake Telegram, kiểm response với chat, loại nội dung và caption/text; receipt lưu cặp chat/message, loại media và attempt. Cặp trùng trong phiên chuyển đích sau sang `unknown`; cùng message ID ở chat khác không mặc nhiên trùng. LinkedIn và Telegram trong `/3` có thể chạy theo hai thứ tự. Nhãn `file_id` giả không chứng minh bytes asset. `/2` LinkedIn cũ vẫn đọc được.

Batch có Instagram dùng schema `/4`: create, observe và publish qua `FakeInstagramTransport`; lưu phase, container và media ID riêng, không gửi lại sau kết quả chưa rõ. Phase `waiting` có thể quan sát lại; `ready` chỉ publish được khi còn chính fake có binding attempt/container trong bộ nhớ. Sau khi tiến trình và fake cũ dừng, fake mới không tự khôi phục binding; hiện chưa có đường tiếp tục publish từ `ready` sau restart. Với `creating` hoặc `publishing` bị bỏ dở, sau khi xác nhận worker cũ đã dừng có thể dùng `mark_instagram_unknown` với đúng key, attempt và phase. `/4` có thể mô phỏng Instagram, LinkedIn và Telegram độc lập trong một phiên. Chưa có CLI hay scheduler; các receipt không chứng minh quyền hoặc bài thật.

Đã kiểm trên Windows với hai subprocess cùng thử một intent LinkedIn, Telegram hoặc bước tạo container Instagram: tổng số lần fake nhận lệnh là một. Đã ngắt subprocess sau khi fake nhận lệnh và trước khi ghi receipt cho LinkedIn, Telegram, Instagram create và Instagram publish; mở lại vẫn giữ attempt và chặn gửi lặp. Với LinkedIn/Telegram, kiểm riêng writer thứ hai bị khóa khi fake của writer đầu còn đang chạy. Các phép thử dùng filesystem tạm cục bộ; không chứng minh chống mất điện, nhiều máy, phiên sao chép hay publish Instagram giữa hai process dùng chung binding.

`scripts/social/json_session_dispatch.py::dispatch_fixture_batch` điều phối tuần tự các job Instagram, LinkedIn và Telegram giả đã khai rõ key, digest và fake. Kiểm toàn lô trước lần gọi fake; mỗi đích phải có grant giả và đến giờ giả. `unknown` không ngăn các job tiếp theo; một lỗi I/O hoặc lỗi bất ngờ dừng lượt và truyền lỗi cho caller, không tự gửi lại. Caller phải mở lại file phiên để kiểm từng đích. Instagram có thể báo chờ quan sát, cần fake gốc hoặc cần phục hồi theo phase. Bộ này là API Python thử nghiệm, chưa có scheduler hay CLI và không thực hiện đăng thật.

Phân biệt các lệnh: `prepare-batch` không mở SQLite khi preview TikTok; `simulate-batch` và `simulate-v1-batch` hiện vẫn dùng SQLite trong bộ nhớ để mô phỏng grant, claim và trạng thái. Không diễn giải kiểm thử preview thành kiểm thử phiên JSON bền.

`preview-v1-file-batch` nhận JSON qua stdin với `source`, `publication` và `entries` giả; dùng cùng builder cho Facebook, YouTube, Instagram, TikTok, LinkedIn, Threads, Discord, X và Telegram. Kết quả là snapshot giả theo đích, không mở kết nối SQLite, không lưu file, không cấp grant hay gửi. Phần kiểm media chỉ áp dụng trong lô; không chứng minh file thật, owner, quyền hay ràng buộc giữa các phiên. Không đưa nội dung thật hoặc thông tin nhạy cảm vào fixture.

Ví dụ PowerShell với publication giả sáu kênh (bỏ trường `events` chỉ dùng cho mô phỏng):

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_six_channel_simulation.json | ConvertFrom-Json | Select-Object source,publication,entries | ConvertTo-Json -Depth 40 | python -m scripts.social.cli preview-v1-file-batch
```

Agent cũng có CLI thử nghiệm, thực thi từ gốc plugin:

```powershell
python -m scripts.social.cli capabilities
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
@'
{"source":"## post:threads_post\nBai viet gia\n","anchor":"post:threads_post","integration_id":"fixture-threads","provider":"threads","media":[],"settings":{"__type":"threads"},"date_utc":"2026-11-20T03:00:00Z"}
'@ | python -m scripts.social.cli prepare
```

`capabilities` liệt kê phương thức **dự kiến**, mức thử offline và `preview_schema`: `postiz_reference` là candidate nghiên cứu theo Postiz, không phải payload gốc của mạng xã hội; `linkedin_native` là preview trực tiếp LinkedIn. `prepare` và `prepare-v1` vẫn dùng cấu trúc nghiên cứu Postiz, không kết nối Postiz. Lệnh `prepare-linkedin` dùng schema LinkedIn trực tiếp; xem [hướng dẫn LinkedIn](LINKEDIN_DIRECT_PREVIEW.md). Mọi lệnh chỉ xử lý offline; không có lệnh submit. Output preview chứa nội dung đầu vào, nên không chuyển dữ liệu nhạy cảm vào ví dụ hoặc log.

Bảng chọn lệnh theo tình huống và giới hạn: [SOCIAL_V2_ROUTES.md](SOCIAL_V2_ROUTES.md).

### Preview nhiều kênh trong một lượt

`python -m scripts.social.cli prepare-batch` nhận JSON từ stdin gồm `source` giả chung và `entries` (1–100 mục). Mỗi mục có `platform`, `destination`, `occurrence`, `scheduled_at`, `options`; xem ví dụ trong `tests/test_social_multichannel_batch.py`. Hỗ trợ native Facebook Page, Instagram, LinkedIn, Threads, YouTube và TikTok Inbox/Direct; mỗi mục dùng anchor riêng. TikTok cần `content_id`/`campaign_id` giả và metadata video giả; Direct còn yêu cầu creator, lựa chọn và digest consent giả khớp, Inbox chỉ giữ caption gợi ý. Preview TikTok dựng candidate trong bộ nhớ, không mở SQLite, không lưu hoặc cấp grant. Lượt preview từ chối trùng bộ platform/destination/occurrence kể cả khi khác giờ, hoặc từ chối toàn lượt nếu một mục sai. Kết quả không ghi sổ bền, không lập lịch, không cấp grant hay gọi mạng. ID, URL, source và thời gian đều do caller tự khai; riêng ID kênh YouTube chỉ là nhãn giả và chưa đối chiếu token/chủ sở hữu. Các action UI chưa được batch này hỗ trợ.

Schema `threads_native` dùng lệnh `prepare-threads` riêng cho chữ, ảnh hoặc video; xem [hướng dẫn Threads](THREADS_DIRECT_PREVIEW.md). Lệnh `prepare` cũ vẫn trả candidate nghiên cứu Postiz, kể cả khi chọn Threads; không suy schema của `prepare` theo registry.

SQLite Threads fixture lưu source giả để dựng lại candidate khi tạo, sửa, grant giả, quét và claim. Account `fixture-threads-account-<id>` và destination `fixture-threads-<id>` là namespace dành riêng; snapshot cũ không có schema mới cần tạo fixture lại. URL ảnh/video chỉ là nhãn giả và được kiểm phần mở rộng theo loại; không xác nhận file, quyền hoặc khả năng Meta truy cập. Không dùng source thật hay dữ liệu nhạy cảm trong fixture.

Schema `tiktok_native` có lệnh `prepare-tiktok-inbox` và `prepare-tiktok-direct` cho video giả; xem [hướng dẫn TikTok](TIKTOK_DIRECT_PREVIEW.md). `prepare` cũ tiếp tục trả candidate tham khảo Postiz; trạng thái native TikTok và trạng thái chuẩn hóa Postiz không dùng thay nhau.

Schema `instagram_native` có lệnh `prepare-instagram` cho ảnh và Reel giả theo nhánh Facebook Login; xem [hướng dẫn Instagram](INSTAGRAM_DIRECT_PREVIEW.md). `prepare` cũ vẫn là candidate tham khảo Postiz và không dùng để khẳng định hỗ trợ native.

Schema `facebook_native` có lệnh `prepare-facebook` cho Page text, ảnh đơn và video thường, tách bình luận đầu và prompt ảnh; xem [hướng dẫn Facebook](FACEBOOK_DIRECT_PREVIEW.md). `prepare_facebook_native_fixture` nối output V1 giả vào SQLite native và dựng lại candidate khi cấp grant giả hoặc claim; video cần `asset_ref` `.mp4` và manifest video khớp. Luồng SQLite cũ vẫn là `postiz_reference` và bảng mapping bên dưới mô tả luồng cũ. Không suy Page API áp dụng cho Group.

Schema `youtube_native` có lệnh `prepare-youtube` xem metadata upload giả; xem [hướng dẫn YouTube](YOUTUBE_DIRECT_PREVIEW.md). `prepare` và `prepare-v1` vẫn là candidate tham khảo Postiz. `prepare_youtube_native_fixture` nối content/1, publish/2 và manifest video/thumbnail giả với SQLite, tách thumbnail khỏi request upload video; chưa upload hay gắn thumbnail.

SQLite YouTube lưu source giả và publication chỉ gồm trường binding; không mang review V1 sang grant V2. Namespace `fixture-youtube-account-<nhãn>` / `fixture-youtube-channel-<nhãn>` dành riêng cho luồng native. Candidate và manifest được dựng lại khi sửa, duyệt giả, quét hoặc claim; manifest không chứng minh file tồn tại, đúng bytes hoặc thuộc kênh. Giờ lưu trong ledger giả không phải `publishAt` trên YouTube. Không dùng source thật hay thông tin nhạy cảm trong fixture.

Luồng native lưu source giả và bản publication đã chỉ giữ các trường binding, không mang trạng thái review V1 sang grant V2. Namespace `fixture-facebook-account-<page>` và `fixture-facebook-page-<page>` được dành riêng cho hợp đồng native; fixture cũ dùng các nhãn đó phải tạo lại theo hợp đồng mới. Không đưa nội dung thật hay dữ liệu nhạy cảm vào SQLite fixture. Mapping ảnh giả chỉ kiểm tên và manifest, không chứng minh file hay quyền sở hữu.

`scripts/social/linkedin_fixture_flow.py` nối anchor LinkedIn giả, author cá nhân/tổ chức giả, media URN giả và lịch vào SQLite. Ảnh/video đòi quan sát **giả do caller cấp** với URN, owner khớp và trạng thái `AVAILABLE`; text không cần. Bộ kiểm dựng lại candidate khi tạo, sửa, cấp grant giả, quét và claim; source giả được lưu nguyên, không dùng nội dung thật. Namespace account/destination `fixture-linkedin-account-…` / `fixture-linkedin-person-…` và `fixture-linkedin-org-account-…` / `fixture-linkedin-org-…` dành riêng cho luồng này. Các nhãn, hash, quan sát và metadata không xác thực tài khoản, quyền, bytes, chủ sở hữu, trạng thái provider hay upload; anchor LinkedIn chưa là enum V1.

`scripts/social/instagram_fixture_flow.py` nối ảnh/Reel giả và thời gian vào SQLite fixture do caller sở hữu. Định danh giả phải khớp IG user ID giả, URL chỉ nhận miền fixture cố định. Snapshot lưu nguyên **source giả** để tái dựng candidate; không đưa nội dung thật hoặc dữ liệu nhạy cảm vào fixture. Metadata nếu có được đối chiếu với content/campaign của bản ghi, nhưng không xác thực nguồn. Kiểm lại khi tạo, sửa, cấp grant giả, quét và claim; snapshot Instagram cũ không đúng schema này bị từ chối. Không có kiểm tài khoản, media thật, container Meta hay dispatch.

## Những gì đã thử

| Đầu vào V1 giả | Media giả theo quy ước V1 | Candidate Postiz | Giới hạn |
|---|---|---|---|
| Facebook `facebook_post` / `post:facebook_post` | `thumbnail.png`, hoặc một `asset_ref` tương đối đơn lẻ | Thân bài + comment riêng + một nhãn ảnh | Prompt ảnh không được đưa vào nội dung; tệp và ảnh chưa được kiểm hay upload |
| YouTube `youtube_video` / `post:youtube_desc` | `video.mp4` và `thumbnail.png` | Một nhãn video | Ảnh bìa được trả riêng ở `unmapped_assets`, chưa được chuyển; `asset_ref` tùy chỉnh chưa được hỗ trợ vì cần xác định riêng từng vai trò |
| YouTube `youtube_short` / `post:youtube_short` | `short.mp4` | Một nhãn video | Chỉ luồng YouTube native fixture; không chứng minh tệp thực được YouTube phân loại Shorts |

Manifest là danh sách đối tượng gồm `content_id`, `post_id`, `relative_path`, `kind`, `id` và `path`; ID bắt đầu bằng `fixture-`, path candidate bắt đầu bằng `/fixture/`. Phải khớp content, bài con, tên và vai trò; thiếu, trùng hoặc sai bài bị từ chối. Các nhãn trong manifest do caller cung cấp; thành công **không** chứng minh tệp có thật hay Postiz đã nhận media.

`preview_v1_fixture` cho phép thử phần text với media giả tách riêng. Warning `media_not_bound_to_v1_asset` nói rằng chưa có chứng cứ liên kết media với tệp V1. Bộ tách lấy source thô; cần bước rà nội dung, G1/G2/G3 theo quy trình V1 và kiểm tra từng đích trước mọi bước thực tế sau này.

Các kênh/format khác, upload media, thumbnail YouTube, lịch bền, liên kết quyền thật, chuyển trạm và việc đăng chưa được thực hiện trong bộ thử này. Xem [hướng dẫn chuẩn bị xác thực](SOCIAL_AUTH_TEST.md) cho bước do chủ tài khoản thực hiện sau này.

## Thao tác UI giả

`tests/fixtures/social_ui_simulator.html` có sáu tình huống: Group chữ/ảnh/video, video chờ creator, Duet và Stitch. Nhập đích dạng `fixture-*`, nội dung giả và chọn nhãn media giả; Duet/Stitch còn yêu cầu nguồn và quyền tái sử dụng giả. Trang không chọn hay tải tệp. Sau xem trước, sửa bất kỳ trường nào sẽ yêu cầu xem lại; sau xác nhận, nút bị khóa trong tab kể cả khi tải lại. Khóa này dùng `sessionStorage`, **không phải** ledger bền hoặc khóa giữa các tab.

`scripts/social/fixture_ui.py` là bộ mô phỏng trạng thái trong RAM với ledger giả: đối chiếu đích, action, ID media, nội dung và phiên bản; `unknown` không tự gửi lại. Dữ liệu quan sát do test cung cấp, **không** lấy từ màn hình thật. HTML chỉ nối với Python qua binding do bộ test cung cấp; khi mở độc lập thì không có kết nối đó. Thao tác chuột, nhập text trên trang giả không chứng minh có thể điều khiển mạng xã hội thật hoặc tránh hệ thống phát hiện của nền tảng. Khi triển khai UI thật sau này phải kiểm đúng tài khoản/đích và quyền, điều kiện giao diện, quy định nền tảng, trạng thái chờ và cơ chế đối soát; không vượt CAPTCHA hay tự gửi lại khi chưa rõ kết quả.

Ngày 19/11/2026 đã thao tác qua giao diện trang giả trên localhost: video Group trả `awaiting_moderation`; Duet thiếu quyền giả bị từ chối xem trước, sau khi chọn quyền giả trả `awaiting_creator`; Stitch chọn mất phản hồi trả `unknown` và khóa hai nút trong tab. Chỉ chọn nhãn media, không chọn hoặc tải video; các thao tác dùng điều khiển giao diện và nhập trường, không chứng minh chuyển động chuột vật lý hay khả năng thao tác trên nền tảng thật.

Test Python riêng có thêm hai đối tượng phiên Duet đồng thời dùng một ledger RAM: chỉ một phiên nhận claim; sau `unknown`, claim API và tạo phiên UI mới cho intent đó bị từ chối. Đây chưa phải kiểm hai tab HTML, reload hoặc kết nối HTML với ledger. Khi thiết kế phép thử tích hợp, grant giả phải do test cấp riêng cho từng intent; đổi đích cần intent/grant mới. Ledger phía server phải quyết định claim, giao diện chỉ hiển thị trạng thái; khi server RAM mất, phiên thử phải dừng thay vì coi là chưa từng xử lý. Bất kỳ server localhost nào cũng cần ràng buộc truy cập và xác thực yêu cầu, không dùng làm server vận hành.

`FixtureUIBridge` và `FixturePreviewCoordinator` là lớp thử nghiệm **trong cùng tiến trình**, nhận dữ liệu quan sát giả và không có HTTP hay browser. Coordinator quản lý một biểu mẫu, giữ một preview và từ chối revision cũ do caller cấp; thay đổi không hợp lệ vẫn hủy preview cũ và tiêu thụ revision mới. Nếu claim thắng trước, biểu mẫu bị khóa. Các coordinator độc lập không chia sẻ trạng thái biểu mẫu; caller phải cấp revision tăng dần, đồng bộ thay đổi và chờ xác nhận hủy trước khi cho phép xác nhận mới. Chưa có bằng chứng mất phản hồi HTTP hoặc khôi phục sau khi tiến trình dừng.

Test `tests/test_social_ui_browser_bridge.py` dùng Chromium và binding do Playwright gắn riêng trong test để nối HTML với coordinator/ledger RAM. Với Group video giả, test đã kiểm xác nhận, mô phỏng mất phản hồi sau khi ledger ghi `unknown`, sửa trường rồi reload và đọc lại `unknown`. Test riêng dùng binding giả kiểm phản hồi preview cũ đến muộn và reload khi chờ tạo hoặc hủy preview: giao diện khóa khi trạng thái chưa rõ. Trường hợp mất phiên được mô phỏng bằng lỗi binding, chưa thử dừng tiến trình ledger. Không có HTTP, tệp video hay provider. Binding và grant giả do test tạo, không phải API vận hành; cần Chromium của Playwright để chạy test. Chưa kiểm khôi phục sau khi tiến trình dừng hoặc thao tác trên social thật.

Simulator hiện có hai lựa chọn video giả `fixture-video` và `fixture-video-other`. Trong test có binding, chọn video không khớp snapshot bị từ chối trước claim; chọn đúng và đưa receipt giả khớp attempt/đích cho trạng thái `awaiting_moderation`, chưa phải đã đăng. Test cũng tháo nút xác nhận khỏi DOM của trang giả và kiểm việc xem trước bị từ chối. Kiểm DOM này chỉ áp dụng trang test, không xác minh nút, clip, người đăng hoặc nhóm trên nền tảng thật.

`scripts/social/facebook_group_v1_fixture.py` chuẩn bị snapshot Group **trong RAM** từ `facebook/reel` V1 giả, bản caption biên tập riêng và manifest `short.mp4` khớp bài. Snapshot bao gồm nguồn giả, publication đã chọn, manifest và identity nhóm/người đăng/occurrence giả; ledger kiểm lại trước khi chuẩn bị hoặc sửa, ràng buộc grant vào digest và chỉ cho claim qua phiên `FixtureUI`. Sau claim, kết quả trực tiếp chỉ có thể là `unknown` hoặc `awaiting_moderation`; quan sát `published` giả là bước riêng. Dấu nội bộ trong Python chỉ để kiểm hợp đồng test, không phải ranh giới bảo mật chống caller có quyền chạy mã. Builder Page được dùng nội bộ để kiểm nguồn/manifest giả, candidate Page bị bỏ; không gọi Page API hay Group.

`tests/test_social_group_v1_browser.py` dùng Playwright và binding **chỉ do test cung cấp** để nối HTML giả với `FixtureGroupV1Form`: nguồn đầy đủ ở Python; form gửi người đăng, đích, chữ và ID media giả để đối chiếu. Các ca sai người đăng, nhóm, clip, sửa DOM sau preview hoặc đổi nguồn trong ledger được kiểm không claim. Test thành công trả `awaiting_moderation` bằng receipt giả; một ca mô phỏng mất phản hồi sau claim rồi reload và đọc lại `unknown` khi ledger RAM còn sống. Test riêng kiểm preview cũ không hủy preview mới. Đây là điều khiển trình duyệt trên trang giả, không xác minh người/nhóm/video thật, không đọc trạm hay chứng minh khả năng thao tác nền tảng; ledger mất khi tiến trình dừng.

`GroupSQLiteSession` trong `scripts/social/group_sqlite_fixture.py` dùng **SQLite fixture riêng do caller tạo**, không di trú trạm. Test chạy tiến trình con claim rồi thoát bình thường trước receipt; tiến trình cha mở DB, thấy attempt cũ, chủ động đánh dấu `unknown` và xác nhận không claim lại. Nhánh receipt giả khớp được lưu `awaiting_moderation` qua lần mở lại; hai kết nối tranh giữa receipt và `unknown` chỉ có một bên thắng. Caller phải xác định worker đã dừng trước khi đánh dấu `unknown`; việc mở DB không tự kết luận worker đã chết. Namespace Group bị tách khỏi Page và scan lịch. Seal Python nội bộ không bảo vệ trước caller có quyền chạy mã và không có tác dụng với tài khoản thực.

`tests/test_social_group_sqlite_browser.py` nối HTML cục bộ qua binding do test cấp tới `GroupSQLiteForm` và DB fixture: kiểm người đăng, đích và clip, mô phỏng receipt hoặc mất phản hồi rồi reload tab, sau đó mở lại DB để kiểm trạng thái. Test hai form cho cùng intent: chỉ một form claim thành công. Preview chưa claim chỉ tồn tại trong RAM; sau claim, preview ID cũng là attempt ID được ghi nguyên tử. Trong test, worker con giữ form từ preview đến confirm rồi thoát đột ngột sau commit; bridge mới trong subprocess chỉ đọc trạng thái khi intent do harness chọn và attempt khớp. Test cả lúc trước receipt và sau `awaiting_moderation`, cùng mã không khớp. Đây là fixture do test điều khiển, không chứng minh xác thực tab/phiên, bảo mật IPC hay phục hồi trong môi trường vận hành; chưa có nền tảng, file video hay tài khoản thật.

Một test Chromium khác mở hai tab cùng Group, actor, nội dung và clip nhưng khác occurrence; harness gán từng `Page`/main frame vào intent riêng. Sau khi chuyển sang bridge phục hồi subprocess, tráo hai preview ID hợp lệ giữa các tab làm cả hai báo phiên không khả dụng và khóa confirm; đưa đúng ID trở lại cho phép đọc đúng trạng thái giả. DB trước/sau không đổi. Ở ca hai tab, form cũ nằm trong tiến trình test vẫn sống; test worker thoát đột ngột là ca một tab riêng. Không coi sessionStorage hay ánh xạ test là xác thực người dùng ngoài đời.

## Đối soát LinkedIn giả

`tests/test_social_linkedin_delivery_fixture.py` minh họa hai đích, duyệt bản giả, claim và đối chiếu kết quả create với attempt, destination và author của snapshot. `201` có Post URN hợp lệ được lưu là `accepted`; không coi lô đã hoàn thành. Phản hồi không rõ chuyển `unknown` và khóa claim lại. Khi đọc lại, URN và author phải khớp; nếu từng thấy provider báo đã đăng rồi sau đó nhận 403 thì lưu cả lịch sử quan sát và trạng thái hiện tại chưa xác minh.

Các phản hồi và nhãn ràng buộc đều do test tự cung cấp: chúng không chứng minh nguồn gốc response, quyền chủ tài khoản hay nội dung đã đăng. Sổ chỉ tồn tại trong RAM, không chịu được restart hoặc nhiều tiến trình, không nối dispatcher và không thay cổng duyệt thật. Không dùng tính năng này với tài khoản hay receipt thật.

Trong một sổ giả, một Post URN không được gắn `accepted` cho hai attempt: lần sau được lưu làm xung đột và chuyển `unknown`. Lối `finish(..., 'published')` chung vẫn tồn tại cho test fixture cũ và không xác thực receipt LinkedIn; không được xem nó là hàng rào cho luồng thật.

## SQLite V2 thử nghiệm nhiều đích

`scripts/social/destination_ledger_fixture.py` là schema **thử nghiệm riêng**, chỉ nhận kết nối SQLite do caller sở hữu và khởi tạo trên database rỗng; không tự mở đường dẫn, không đọc hoặc sửa database V1. Khóa gồm account, destination và occurrence. Snapshot gắn destination; thay nội dung làm mất grant giả của riêng intent đó. Một claim được giao dịch SQLite ghi bền; receipt sai attempt/đích bị từ chối, remote ID trùng trong cùng platform/account được lưu thành xung đột và chuyển attempt thứ hai về `unknown`.

`tests/test_social_destination_sqlite_fixture.py` dùng SQLite tạm, thử hai tiến trình Windows claim cùng intent, mở lại database và xác nhận đích khác độc lập. Đây chưa phải kiểm thử worker thực sự bị crash: `mark_unknown` chỉ ghi nhận điều caller đã xác định, không tự chứng minh worker đã dừng. Schema cũng chưa có lịch chạy, duyệt thật, lịch sử grant đầy đủ, thu hồi, xác thực source hoặc transport. Các kết quả này không cho phép dùng database fixture để phát bài hoặc chuyển trạm.

Hai luồng fixture ở `scripts/social/threads_fixture_flow.py` và `scripts/social/v1_fixture_flow.py` nối preview vào sổ SQLite thử nghiệm. Threads lưu candidate native cho chữ/ảnh/video, giờ UTC dự kiến và SHA-256 của source caller cung cấp; nhãn account và destination giả được chuẩn hóa theo Threads user ID giả. Nếu source có frontmatter thì kiểm content/campaign khớp; không có frontmatter thì ghi nhận source trần. Cả hai trường hợp đều chưa xác thực nguồn hay tài khoản. URL media trong luồng này chỉ chấp nhận miền/đường dẫn fixture.

Luồng Facebook kiểm các trường `content/1`, `publish/2`, post và manifest ảnh giả rồi lưu candidate `postiz_reference`, không gọi Postiz hay Facebook. Review `approved` trong tài liệu giả **không** chuyển thành grant V2. Hai account alias không được chiếm cùng destination và occurrence trong sổ; thay đổi schema fixture làm database fixture tạo bằng DDL cũ không còn mở được, không có migration cho database thật. SHA-256 chỉ phát hiện thay đổi input, không chứng minh nguồn hay tệp media thật. Chưa có scheduler vận hành hoặc tác dụng đăng.

### Thử lấy intent đến giờ

Trên kết nối SQLite fixture do test quản lý, `scan_due(now=...)` trả các intent đã có grant giả theo thứ tự thời gian rồi ID, đồng thời báo riêng những snapshot có lịch không hợp lệ. Nếu có hơn 1.000 intent đủ điều kiện quét, hàm báo lỗi thay vì trả thiếu. `claim_due(intent_id, expected_version=..., now=...)` kiểm lại giờ, snapshot, version và grant trong một giao dịch trước khi ghi attempt. `claim()` chung từ chối snapshot có lịch; intent không có lịch vẫn dùng hợp đồng fixture cũ.

`approve_batch([(intent_id, version), ...])` cấp grant **giả** cho đúng danh sách được chọn (có thể thuộc nhiều bài), tối đa 1.000 mục; một mục sai làm cả giao dịch không được ghi. `revoke(intent_id, expected_version=...)` chỉ thu hồi grant giả của intent còn `prepared`, đồng thời tăng version để lệnh cấp grant cũ bị từ chối. Thu hồi không hủy được attempt đã chuyển `submitting`; nếu claim và revoke tranh nhau, chỉ thao tác ghi trước thành công. Đây không phải duyệt lô thật, không có danh tính người duyệt, lịch sử thu hồi, phạm vi thời gian hoặc cơ chế hủy tác vụ đang chạy.

`prepare_batch([(key, snapshot), ...])` ghi tối đa 100 intent giả đã dựng sẵn trong một giao dịch; intent mới không có grant. Mỗi snapshot phải đúng hợp đồng nền tảng; một mục trùng hoặc xung đột làm rollback cả lô. Gọi lại lô giống hệt trả cùng ID và giữ trạng thái, grant đã có của intent cũ. Caller phải tránh sửa đồng thời các đối tượng lồng nhau trong lúc sao chép. Hàm nhận kết nối SQLite thử nghiệm do caller sở hữu và không tự mở trạm.

`scripts.social.multichannel_fixture.prepare_fixture_batch(ledger, source=..., entries=...)` nối một source giả với các builder native Facebook, Instagram, LinkedIn, Threads, TikTok và YouTube, rồi gọi `prepare_batch` để ghi toàn lô. Mỗi mục gồm `platform` và `args` theo hàm `prepare_*_fixture` của kênh, không lặp `source`; các mục phải có cùng `campaign_id` và `content_id`, còn `post_id` có thể khác. Ví dụ sáu kênh tại `tests/test_social_multichannel_sqlite.py`. Các builder trước tiên chạy trên SQLite trong bộ nhớ và chỉ ghi sổ đích khi tất cả hợp lệ. Nhãn và source do caller cung cấp, không xác thực nguồn. `prepare-batch` CLI vẫn chỉ preview, không gọi hàm ghi này. Không đưa dữ liệu thật vào fixture; không có scheduler thực, grant thật hay dispatch.

`python -m scripts.social.cli simulate-batch` nhận JSON `source`, `entries` theo cấu trúc Python trên và `events`; chạy toàn bộ trong SQLite bộ nhớ rồi đóng. Danh sách `events` rỗng chỉ tạo intent chưa grant. Các sự kiện giả có thể khai rõ theo thứ tự:

```json
[
  {"action":"grant","entries":[{"index":0,"version":1},{"index":1,"version":1}]},
  {"action":"revoke","index":0,"version":1},
  {"action":"scan","now":"2026-11-20T04:00:00Z"},
  {"action":"claim","index":1,"version":1,"now":"2026-11-20T04:00:00Z"}
]
```

`index` là vị trí mục trong `entries`, `version` và đồng hồ do caller giả lập. Mục đến giờ được sắp theo thời gian rồi index đầu vào khi đồng giờ. TikTok trả thêm anchor, ID/hash và caption gợi ý do caller khai để phân biệt media giả. Ví dụ đầy đủ tại `tests/test_social_simulate_batch.py` và `tests/test_social_multichannel_sqlite.py`. Trạng thái `submitting` chỉ nói fixture đã claim; chưa có transport hay provider nhận bài. Một sự kiện sai làm cả lệnh lỗi và mất phiên giả trong bộ nhớ, không trả kết quả một phần; không có lệnh ghi duyệt người thật.

Ví dụ JSON có sẵn cho sáu kênh: [`fixtures/social_v2/six_channel_simulation.json`](../../fixtures/social_v2/six_channel_simulation.json). Từ gốc plugin, chạy trên Windows:

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/six_channel_simulation.json | python -m scripts.social.cli simulate-batch
```

Các index theo thứ tự Facebook 0, Instagram 1, LinkedIn 2, Threads 3, TikTok 4, YouTube 5. Ví dụ giả lập cấp grant cho sáu mục, thu hồi Facebook, quét rồi claim Instagram; các mục khác vẫn `prepared`. Không có cổng duyệt thật, tệp video, tài khoản, lịch bền hay kết nối provider. Không thay dữ liệu giả bằng token hoặc thông tin thật.

Giờ nhận timestamp có múi giờ, chính xác tới giây; offset được đổi về UTC khi so sánh, giá trị thiếu múi, giây lẻ, offset sai và `-00:00` bị từ chối. Đồng hồ là dữ liệu caller cung cấp, không chứng minh thời gian thực đáng tin. `scan_due` không claim, vì vậy caller phải dùng `claim_due` để kiểm lại khi có cạnh tranh hoặc đổi lịch. Không có daemon, cron, transport hoặc kết nối phê duyệt thật; không dùng hàm này để đăng live.

Ví dụ [Reel Facebook và YouTube Short](../../fixtures/social_v2/reel_short_simulation.json) dùng cùng source và hai bản sao giống nhau của `publish/2` giả, chọn hai `post_id`, hai anchor và hai nhãn `short.mp4` riêng. Từ gốc plugin trên PowerShell:

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/reel_short_simulation.json | python -m scripts.social.cli simulate-batch
```

Lệnh chạy trong SQLite bộ nhớ; grant, scan và claim là event giả, `submitting` không chứng minh Meta hay YouTube đã nhận nội dung. Manifest chỉ là nhãn cho từng bài, không đọc video. Test tráo owner của Short bị từ chối trước khi ghi ledger đích. Ví dụ lặp lại publication trong JSON, chưa tự đọc hay chuyển trạm V1.

### Một publication V1 dùng chung cho nhiều đích

[Ví dụ sáu kênh](../../fixtures/social_v2/v1_six_channel_simulation.json) kết hợp Facebook Reel, YouTube Short, Instagram Reel, TikTok Direct, LinkedIn text và Threads text từ một `content/1` + `publish/2` giả. Hai bản chữ LinkedIn và Threads được chuẩn bị riêng. Manifest của mỗi video chỉ là nhãn giả, dù các bài đều dùng tên `short.mp4`.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_six_channel_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Các sự kiện ví dụ dùng chỉ số entry **0 Facebook, 1 YouTube, 2 Instagram, 3 TikTok, 4 LinkedIn, 5 Threads**. Năm mục đầu nhận grant và claim giả; Threads chưa grant, vẫn `prepared`. Nếu đổi thứ tự `entries`, phải đổi mọi chỉ số trong `events` tương ứng. `submitting` không xác nhận nền tảng nhận bài, và grant/consent ở đây không phải phê duyệt thật.

Ví dụ [V1 Reel và Short](../../fixtures/social_v2/v1_reel_short_simulation.json) khai một `publication` giả cấp ngoài, thay vì lặp lại trong từng mục. `simulate-v1-batch` nhận Facebook, YouTube, chuyển infographic hoặc Reel Facebook V1 sang Instagram, YouTube Short sang TikTok Inbox hoặc Direct, và Facebook post sang LinkedIn/Threads text đã biên tập; mỗi mục chọn `post_id` riêng. Mã từ chối `post_id` trùng và không cho từng mục thay `publication` hoặc `source`. Các builder kiểm channel, format, anchor và owner của manifest khi dùng media. `simulate-batch` cũ cho phép từng mục truyền tập con bài khác nhau; nó từ chối header mâu thuẫn, dòng cùng `post_id` khác nhau và cùng anchor gán cho hai bài, nhưng không chứng minh các tập con đến từ cùng một file.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_reel_short_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Chỉ dùng dữ liệu giả. Publication chung bảo đảm các mục trong lượt mô phỏng dùng cùng dữ liệu caller cung cấp; không xác minh nguồn từ trạm, quyền duyệt hay file media thực. Grant và `submitting` vẫn chỉ là trạng thái giả trong bộ nhớ, không gửi API và không tạo lịch thật.

Ví dụ [ba đích](../../fixtures/social_v2/v1_three_destination_simulation.json) bổ sung ảnh Instagram từ bài V1 có `channel=facebook`, `post_format=infographic`, `asset_ref` ảnh tường minh. Kết quả hiển thị `source_binding` để thấy rõ bài Facebook nguồn được chuyển sang Instagram; caption và nhãn ảnh lấy từ anchor/manifest của bài đó. Đây là chuyển đích giả, không phải bài Instagram nguyên bản V1. Schema nguồn không đổi khi sửa intent.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_three_destination_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Ví dụ [Reel V1 sang Instagram](../../fixtures/social_v2/v1_reel_to_instagram_simulation.json) chuyển bài `facebook/reel`, giữ anchor `post:reel`, tách caption bằng parser Reel và chọn `short.mp4` theo manifest của đúng post. Candidate Instagram chỉ mô tả yêu cầu tạo container; không chứng minh Meta có thể tải video, đã xử lý, hoặc đã xuất bản. Người dùng vẫn phải xác định quyền sử dụng nội dung cho đích Instagram.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_reel_to_instagram_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Ví dụ [Short V1 sang TikTok Inbox](../../fixtures/social_v2/v1_short_to_tiktok_simulation.json) chọn `youtube/youtube_short`, giữ anchor, lấy duy nhất dòng Caption làm gợi ý và ánh xạ `short.mp4` đúng post sang video giả. Request Inbox không gửi caption; `source_binding` nêu rõ bài YouTube nguồn. Kích thước và SHA-256 chỉ là dữ liệu fixture caller khai, không chứng minh bytes hay quyền. Không có upload, thông báo creator hoặc đăng thật.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_short_to_tiktok_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

[Short V1 sang TikTok Direct giả](../../fixtures/social_v2/v1_short_to_tiktok_direct_simulation.json) yêu cầu `direct` gồm creator/revision, thời lượng, `post_info`, consent và digest **giả do caller cấp**. `post_info.title` phải khớp Caption Short; digest phải khớp các lựa chọn, creator, thời lượng, kích thước và hash media giả. Digest không bao gồm ID bài, media ID hoặc lịch; snapshot và grant fixture ràng buộc các trường còn lại. Sửa hợp lệ làm mất grant giả cũ. Digest không chứng minh người thật đã đồng ý, tệp thật khớp hash, creator được xác thực hay TikTok đã nhận bài.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_short_to_tiktok_direct_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

[Facebook V1 sang LinkedIn text](../../fixtures/social_v2/v1_facebook_to_linkedin_simulation.json) yêu cầu `adapted_text` giả do caller chuẩn bị riêng cho LinkedIn. Bộ chuyển đổi kiểm bài nguồn, không tự đưa comment đầu hay prompt ảnh vào candidate và trả cờ `source_notes`; asset_ref tường minh bị từ chối ở đường text, còn media mặc định chưa được kiểm. So sánh văn bản chỉ chặn bản sao nguyên văn sau chuẩn hóa xuống dòng, **không xác minh chất lượng biên tập, nội dung comment có bị caller chép lại hay quyền sử dụng**. Người dùng cần rà nội dung và quyết định có chuyển link hoặc media sang đích mới không.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_linkedin_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

[Facebook V1 sang Threads text](../../fixtures/social_v2/v1_facebook_to_threads_simulation.json) cũng yêu cầu `adapted_text` riêng, lưu bài và anchor nguồn, hiển thị các phần chưa chuyển. Fixture giới hạn 500 code point sau chuẩn hóa CRLF; đây là ràng buộc thử, không xác nhận giới hạn hay quyền trên tài khoản thực. So sánh với thân bài nguồn không xác minh chất lượng biên tập hoặc nội dung caller tự chép từ bình luận; asset tường minh chưa được chuyển.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_threads_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

[Facebook V1 sang Discord text](../../fixtures/social_v2/v1_facebook_to_discord_simulation.json) dùng `adapted_text` riêng, bot và channel giả, kèm guild/channel do caller khai. Đích được khóa theo channel; guild được kiểm với target giả nhưng không chứng minh channel thực thuộc guild. Candidate native luôn đặt `allowed_mentions.parse=[]`; đây chỉ là payload xem trước, chưa xác minh hành vi mention trên nền tảng. Receipt giả `finish_discord_fixture` kiểm attempt, channel và message ID, ghi `accepted` chứ không chứng minh người dùng nhìn thấy bài. Bản chữ không tự chuyển comment, prompt hoặc media; chất lượng biên tập cần người kiểm.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_discord_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

[Facebook V1 sang Telegram channel text](../../fixtures/social_v2/v1_facebook_to_telegram_simulation.json) yêu cầu nội dung biên tập riêng, chat ID giả và bot có `purpose=publish`; không dùng bot duyệt V1. Candidate mô tả phương thức [sendMessage](https://core.telegram.org/bots/api#sendmessage), không chứa token hay parse mode và không gửi. Receipt giả gắn attempt, loại `channel`, chat ID và message ID; cùng message ID ở channel khác là hai tin khác nhau. Chưa xác minh ID, quyền bot, giới hạn ký tự hay người đọc thấy tin; comment, prompt ảnh và media không tự chuyển.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_telegram_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Telegram media dùng [infographic V1 giả](../../fixtures/social_v2/v1_to_telegram_image_simulation.json) cho `sendPhoto` và [YouTube Short V1 giả](../../fixtures/social_v2/v1_to_telegram_video_simulation.json) cho `sendVideo`. Infographic cần asset_ref ảnh rõ ràng; Short giữ `short.mp4` của đúng bài. Caption nguồn và caption Telegram tách riêng; với Short chỉ lấy dòng Caption, không tự chuyển Hook hay kịch bản. Mỗi bot/channel, lịch và grant vẫn là giả. Receipt giả kiểm loại ảnh/video bên cạnh channel và message ID, nhưng loại do caller khai không chứng minh đúng byte tệp đã gửi. Trong một batch, các đích Telegram dùng cùng bài và đường dẫn phải khai cùng loại và ID asset nguồn; các nền tảng khác có thể dùng nhãn fixture riêng.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_to_telegram_image_simulation.json | python -m scripts.social.cli simulate-v1-batch
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_to_telegram_video_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Không đọc tệp, kiểm codec hoặc upload; giới hạn caption 1.024 là kiểm fixture, không chứng minh Telegram sẽ chấp nhận nội dung. Tham khảo [sendPhoto](https://core.telegram.org/bots/api#sendphoto) và [sendVideo](https://core.telegram.org/bots/api#sendvideo).

[Facebook V1 sang X text](../../fixtures/social_v2/v1_facebook_to_x_simulation.json) ràng buộc bài nguồn và profile giả với `adapted_text` riêng. Candidate mô tả `POST /2/tweets` chỉ có trường `text` theo [tài liệu X](https://docs.x.com/x-api/posts/create-post); không thực hiện request. Không tự chuyển comment, prompt ảnh hay media, và không hỗ trợ reply, thread hoặc article. Trần 32.000 ký tự chỉ bảo vệ dữ liệu fixture; cảnh báo `x_weighted_length_unchecked` nghĩa là **chưa kiểm độ dài có trọng số của X**, đặc biệt với URL, emoji và chữ đa ngôn ngữ. Receipt giả kiểm attempt và user do caller khai; `accepted` không xác thực tác giả hay chứng minh bài hiển thị. Cần kiểm nội dung và quyền trước mọi kết nối thật.

Để chỉ xem candidate X text độc lập, không ràng buộc publication hay lịch, có thể dùng `prepare-x`:

```powershell
'{"text":"Ví dụ bài X giả 👩‍💻"}' | python -m scripts.social.cli prepare-x
```

Lệnh từ chối các trường ngoài `text` như reply và media; không xem candidate là dữ liệu đã được nền tảng chấp nhận.

Để xem riêng bài Facebook V1 kèm **một ảnh hoặc một video** cho X, dùng [ví dụ ảnh giả](../../fixtures/social_v2/v1_facebook_to_x_image_preview.json) hoặc [ví dụ video giả](../../fixtures/social_v2/v1_facebook_to_x_video_preview.json):

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_x_image_preview.json | python -m scripts.social.cli prepare-x-v1-media
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_x_video_preview.json | python -m scripts.social.cli prepare-x-v1-media
```

Phải chọn `asset_ref` tường minh và manifest gắn đúng bài nguồn; văn bản X cần được biên tập riêng. Asset ID V1 và media ID X là hai nhãn giả do caller khai, **không chứng minh liên kết thực**. Candidate mô tả `media.media_ids` theo [X Create Post](https://docs.x.com/x-api/posts/create-post); ID giả không dùng để gửi lên nền tảng. Không đọc tệp, upload hay xác nhận định dạng, thời hạn, chủ sở hữu hoặc trạng thái xử lý media. Lệnh preview này không lưu intent, không cấp grant và không hẹn lịch.

Để mô phỏng lịch media, dùng [ví dụ ảnh giả](../../fixtures/social_v2/v1_facebook_to_x_image_simulation.json) hoặc [ví dụ video giả](../../fixtures/social_v2/v1_facebook_to_x_video_simulation.json):

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_x_video_simulation.json | python -m scripts.social.cli simulate-v1-batch
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_x_image_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

Quan sát `succeeded`, `pending` hoặc `failed` cùng ID, chủ thể và thời điểm đều do caller khai và **không được xác thực**. `scan` và `claim` chỉ cho nhận lịch giả khi `succeeded`, đã tới giờ, thời điểm kiểm không trước quan sát và trước `expires_at`; hết hạn hoặc chưa sẵn sàng được đưa vào `invalid`. Thay snapshot xóa grant giả; receipt giả có thể được ghi sau khi claim. Chưa mô phỏng upload thực, các phần upload hay xác nhận trạng thái từ X; không suy `submitting` là X đã nhận bài.

Cùng một bài và asset V1 có thể được chuẩn bị cho Facebook Page và X trong một batch: [ví dụ ảnh](../../fixtures/social_v2/v1_facebook_x_image_batch.json) · [ví dụ video](../../fixtures/social_v2/v1_facebook_x_video_batch.json). Cùng `content_id`, `post_id` và đường dẫn tương đối phải có cùng loại và ID asset nguồn ở hai manifest; media ID X vẫn là nhãn đích riêng. Mỗi đích có grant và trạng thái độc lập; nếu một entry sai khi chuẩn bị, batch không ghi entry nào. Đây chỉ là đối chiếu khai báo fixture, chưa chứng minh nội dung các tệp thực giống nhau.

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_x_video_batch.json | python -m scripts.social.cli simulate-v1-batch
```

```powershell
Get-Content -Raw -Encoding UTF8 fixtures/social_v2/v1_facebook_to_x_simulation.json | python -m scripts.social.cli simulate-v1-batch
```

### TikTok video fixture

`scripts/social/tiktok_fixture_flow.py` nối anchor thử nghiệm `post:tiktok_post`, một video giả và giờ dự kiến vào SQLite. Direct Post yêu cầu caption khớp post_info, nhãn creator/revision giả và digest consent giả khớp metadata/media do caller khai. Với inbox, caption chỉ lưu như gợi ý: request upload không chứa caption và chưa chứng minh creator đã nhận thông báo. Lưu anchor, hash source và hash media do caller cấp để phát hiện thay đổi; không đọc tệp hay xác thực nguồn, bytes, creator hoặc consent.

Snapshot mới lưu dữ liệu creator, tùy chọn và consent **giả** cần để dựng lại candidate. Sổ kiểm hợp đồng TikTok khi tạo, sửa, cấp grant giả, quét và nhận lịch; sửa không khớp bị từ chối, còn sửa hợp lệ làm mất grant cũ. Các snapshot TikTok cũ không có schema mới bị từ chối và chỉ dùng lại bằng cách chuẩn bị fixture mới; không di trú trạm thật.

Grant và consent vẫn là dữ liệu giả do caller tạo; hash không chứng minh người thật đồng ý, source, bytes video hay danh tính creator. Không dùng đường này để tạo bằng chứng duyệt, upload hay phát thật. Xem [preview TikTok](TIKTOK_DIRECT_PREVIEW.md) về giới hạn chính sách và hai loại trạng thái.
