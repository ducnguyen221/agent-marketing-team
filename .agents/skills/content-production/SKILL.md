---
name: content-production
description: Write and polish marketing content inside or outside a campaign, including a brand voice profile from published posts, blog drafting and editing, quote and source attribution, raw idea to angles, Facebook post to blog, and 7-pass copy editing, campaign assets. Not for strategy advice or bypassing Gate 1.
---

# Sản xuất nội dung & Biên tập (Content Production)

Sản xuất nội dung đa kênh sẵn-đăng từ brief chiến dịch đã duyệt Gate 1, hoặc biên tập nâng cao bản nháp độc lập qua 7 lượt biên tập.

## Khi nào dùng
- Sản xuất bài viết (blog, social, email, newsletter, landing copy) cho chiến dịch đã qua Gate 1.
- Biên tập, làm sắc nét và gọt giũa bản nháp (loại bỏ sáo rỗng AI, làm rõ luận điểm, kiểm tra claim).
- Tái chế một nội dung gốc sang nhiều định dạng kênh phát hành khác nhau.
- Người dùng chỉ có ý thô, cần bóc angle và đề xuất cấu trúc (mục «Ý thô → angle»).
- Nâng một post có sẵn thành blog (mục «Nâng post → blog»).
- Hồ sơ giọng từ bài đã đăng; viết/sửa blog; dẫn nguồn đúng luật.

## Khi không dùng
- Sản xuất asset cho chiến dịch chưa có brief hoặc chưa qua Gate 1 (cần hoàn tất ở `campaign-pipeline`). Hai việc «Ý thô → angle» và «Nâng post → blog» không vướng dòng này vì chạy trước brief hoặc ở chế độ `standalone-edit`.
- Tư vấn định hướng chiến lược hoặc thay đổi gói dịch vụ/offer (dùng `content-strategy`).

## Ba chế độ hoạt động
1. **Chế độ `campaign` (Mặc định trong chiến dịch):**
   - Đòi hỏi: Chiến dịch đã qua Gate 1 (`Content.status = in_production`).
   - Đầu vào: `campaign.md` (frontmatter + brief), hồ sơ kênh (`brand.md`), research bài viết.
   - Đầu ra: Ghi file `content.md`, tạo khối `## post:<post_format>`, cập nhật trạng thái `Post.agent_status = completed`, chuẩn bị trình Gate 2.
2. **Chế độ `standalone-edit` (Biên tập độc lập):**
   - Đòi hỏi: Bản nháp độc lập không thuộc chiến dịch + mục tiêu biên tập + giọng kênh/nguồn.
   - Đầu vào: Văn bản nháp, đối tượng độc giả, tài liệu kiểm chứng (nếu có).
   - Đầu ra: Bản nháp đã chỉnh sửa + ghi chú lý do sửa; KHÔNG tạo thư mục bài, KHÔNG ghi trạng thái.
   - **Ranh giới cứng:** Nếu bản nháp thuộc về một chiến dịch đang quản lý, bắt buộc phải tuân theo chế độ `campaign` và kiểm tra Gate 1, nghiêm cấm dùng `standalone-edit` để né cổng duyệt.
3. **Chế độ `standalone-blog` (Blog độc lập có chấm cổng):**
   - Đòi hỏi: một file blog markdown ngoài chiến dịch + tên miền nhà (hoặc `channel.yml`). Đầu vào: bài, `research.md` nếu có.
   - Đầu ra: bảng 24 cổng + `gates.json` trong thư mục tạm `.tmp/standalone-blog/`, tự xoá trừ khi `--keep`; KHÔNG ghi trạng thái, KHÔNG tạo bài trong trạm.
   - Lệnh: `python scripts/pipeline/standalone_blog.py --blog <bài.md> --home-domain <miền>`. Thiếu `--home-domain` và `--brand` thì thoát 2 (script không tự tìm `channel.yml`): truyền giá trị giữ chỗ và nói rõ trong báo cáo.

## Quy trình sản xuất & Biên tập
1. **Tiếp nhận & Xác định chế độ:** Nhận brief hoặc bản nháp; kiểm tra tính hợp lệ của Gate 1 nếu là campaign.
2. **Khung bài & Giọng điệu:** Chọn công thức (`COPY_FRAMEWORKS.md`) và giọng theo kênh (`brand.md`, `output_styles/`). Dựng hoặc rà hồ sơ giọng: `knowledge/playbooks/BRAND_VOICE.md`.
3. **Áp dụng 7 lượt biên tập (`COPY_EDITING.md`):**
   - Lượt 1: Cấu trúc & Mạch lập luận (Flow & Structure).
   - Lượt 2: Độ rõ ràng & Tinh gọn (cắt sáo rỗng AI).
   - Lượt 3: Giọng tác giả & Phù hợp kênh.
   - Lượt 4: Bằng chứng & Tính cụ thể (gắn `[KIỂM CHỨNG]` cho số liệu chưa xác minh).
   - Lượt 5: Lời kêu gọi hành động (CTA) trực diện, duy nhất.
   - Lượt 6: Trình bày & Quét mắt (tiêu đề phụ, bullet, đoạn ngắn).
   - Lượt 7: Rà soát an toàn (loại bỏ PII, không lộ tool nội bộ).
4. **Kiểm tra QA:** Chạy checklist `checklists/QA_ASSET.md` trước khi bàn giao.

## Ý thô → angle
Khi người dùng chỉ đưa một ý thô (một câu, một ghi chú), đừng hỏi ngược cả loạt câu. Làm theo thứ tự:
1. Nêu 3 angle khả dĩ, mỗi angle một dòng: luận điểm + người đọc được gì.
2. Chọn 1 angle khuyến nghị, nói lý do và rủi ro.
3. Đề xuất tiêu đề, cấu trúc (outline), ý hình, giọng, hook, CTA, hashtag.
4. Gắn nhãn `inferred` cho mọi điều tự suy; **dừng** chờ người dùng gật angle trước khi viết bản đầy đủ.

## Nâng post → blog
Có bài ngắn (post) cần mở thành blog:
1. Giữ giọng và luận điểm gốc; không viết lại thành giọng khác.
2. Mở chiều sâu: giải nghĩa key-term, thêm khung hoặc quy trình áp dụng, thêm ví dụ.
3. Thêm nguồn cho mọi số liệu và lời gán; việc nào chưa có nguồn gắn `[KIỂM CHỨNG]`.
4. **Dừng** trước khi viết bản đầy đủ để người dùng xem dàn ý đã mở rộng. Ở `standalone-edit`, bỏ bước dừng khi người dùng đã nói rõ muốn bản đầy đủ ngay **và** dàn ý không có mục `inferred` nào; ở `campaign` luôn dừng (trước khi ghi `content.md`). Ngoài chiến dịch, việc này chạy ở `standalone-edit`, không tạo thư mục bài.

### Chấm cổng blog ngoài chiến dịch
Dùng chế độ `standalone-blog` (lệnh ở trên). Cổng chỉ đo thứ đếm được; cổng báo «thiếu» không phải xanh.

## Đầu ra
- Với `campaign`: `content.md` (nguồn duy nhất của mọi kênh, `B2`) chứa các khối `## post:<format>`; bản blog tách ra nằm ở `atlas/blog.md` theo `scripts/lib/post_paths.py` `LAYOUT` — không có `blog.md` ở gốc bài.
- Với `standalone-edit`: bản sửa + bảng giải thích. Với `standalone-blog`: bảng cổng + `gates.json`.

## Kiểm tra chất lượng & Ranh giới an toàn
- Giữ nguyên sự thật và giọng tác giả; không tự ý thay đổi offer, cam kết hoặc chính sách giá.
- Không bịa đặt chứng chỉ, logo đối tác hoặc lời chứng thực của khách hàng.
- Số khối `## post:` phải khớp chính xác số dòng Post trong campaign.

### Dẫn nguồn
- Chỉ gán lời cho một nguồn khi nguồn đó có thật trong tư liệu đang cầm và truy được tới đoạn cụ thể.
- Tiêu đề bài báo không phải lời toà soạn; không trích tiêu đề như một phát biểu.
- Mốc thời gian và quan hệ nhân quả cũng là dữ kiện, cần nguồn như số liệu.
- Không có nguồn thì viết là quan điểm của tác giả, hoặc bỏ.
- Bài sẽ bàn giao: đọc `checklists/QA_ASSET.md` mục `chk_quote_attribution` **trước khi** viết trích dẫn; đoạn trích lẻ thì bốn luật trên là đủ.

Ví dụ minh hoạ và luật chiều sâu/liên tục: `references/source-depth.md`.

## Tài liệu tham khảo
- Sổ tay biên tập 7 lượt: `knowledge/playbooks/COPY_EDITING.md`
- Công thức viết: `knowledge/playbooks/COPY_FRAMEWORKS.md`
- Checklist QA: `.agents/checklists/QA_ASSET.md`
