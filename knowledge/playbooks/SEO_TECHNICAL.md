# SEO kỹ thuật — checklist crawl, index, tốc độ, dữ liệu có cấu trúc

Bổ sung cho `SEO_PLAYBOOK.md` (on-page, E-E-A-T, AI search, cluster). File này chỉ lo phần kỹ thuật và ánh xạ từ khoá ↔ URL; không lặp lại luật heading, alt text, slug.

## Dùng khi
- Kiểm site hoặc blog trước khi đẩy nhiều bài; xem vì sao một trang không lên chỉ mục.
- Rà title/meta, dữ liệu có cấu trúc, tốc độ tải, liên kết nội bộ.
- Lên kế hoạch sitemap, robots, hoặc gom các trang đang tranh cùng một từ khoá.

---

## 1. Nguyên tắc
1. **Sửa chặn kỹ thuật trước khi tối ưu nội dung.** Trang không bò vào được hoặc bị gắn noindex thì viết hay mấy cũng vô nghĩa.
2. **Một trang một ý định tìm kiếm chính.** Hai trang trả lời cùng một câu hỏi sẽ cạnh tranh nhau.
3. Chọn tín hiệu chất lượng dài hạn, không chọn mẹo ngắn hạn.
4. Chỉ mục ưu tiên bản di động: kiểm trên màn hình nhỏ trước.
5. Khuyến nghị phải chỉ đúng trang và làm được ngay, không chung chung kiểu «cải thiện SEO».

## 2. Crawl (máy tìm kiếm vào được không)
- `robots.txt` cho phép trang quan trọng, chặn bề mặt giá trị thấp (trang lọc, kết quả tìm nội bộ).
- Không trang quan trọng nào mang `noindex` ngoài ý muốn: kiểm trước mỗi lần xuất bản hàng loạt.
- Trang quan trọng nằm nông, vài cú nhấp từ trang chủ (ngưỡng khởi điểm: ≤ 3 cú nhấp, chưa đo).
- Chuỗi chuyển hướng không dài quá hai bước; mỗi bước thừa là một lần mất tốc độ và tín hiệu.
- Thẻ canonical nhất quán với nhau, không tự trỏ vòng.

## 3. Index (trang có được lưu đúng bản không)
- Chọn một dạng URL chuẩn (có hay không có dấu gạch cuối, http hay https) và giữ nhất quán.
- Site đa ngôn ngữ cần `hreflang` đúng; nếu chỉ một ngôn ngữ thì không thêm cho có.
- Sitemap phản ánh đúng phần công khai muốn lên chỉ mục, không chứa trang đã chặn.
- URL trùng nội dung phải có canonical kiểm soát, nếu không chúng tự cạnh tranh.

Ghi chú nối repo: `scripts/pipeline/build_blog_html.py` đã sinh `<link rel="canonical">`; luật ở trên làm rõ vì sao phải giữ, không thêm việc mới.

## 4. Core Web Vitals
Ngưỡng «tốt» do Google công bố công khai trong tài liệu web.dev về Core Web Vitals (kiểm lại bản hiện hành trước khi trích):

| Chỉ số | Đo gì | Ngưỡng tốt |
|---|---|---|
| LCP | thời gian hiện phần nội dung lớn nhất | dưới 2,5 giây |
| INP | độ trễ phản hồi khi tương tác | dưới 200 ms |
| CLS | mức xê dịch bố cục bất ngờ | dưới 0,1 |

Cách sửa thường gặp: tải trước ảnh đầu trang; giảm phần chặn hiển thị; chừa sẵn chỗ cho ảnh và quảng cáo để bố cục không nhảy; cắt bớt JavaScript nặng. Chưa đo trên site của kênh này thì ghi «chưa đo», đừng báo đã đạt.

## 5. Dữ liệu có cấu trúc (JSON-LD)
Chọn loại theo loại trang:
- Trang chủ: Organization (hoặc loại doanh nghiệp phù hợp).
- Bài viết, blog: `Article` hoặc `BlogPosting`.
- Trang sản phẩm: `Product` kèm `Offer`.
- Trang con có đường dẫn phân cấp: `BreadcrumbList`.
- Mục hỏi–đáp: `FAQPage`, **chỉ khi** nội dung thật sự là hỏi–đáp.

Ví dụ bịa, chỉ minh hoạ khung (đổi mọi giá trị khi dùng):

```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Tiêu đề bài mẫu",
  "datePublished": "2026-01-01",
  "author": { "@type": "Person", "name": "Tên tác giả mẫu" }
}
```

**Nợ ghi nhận (không làm đợt này):** `build_blog_html.py` chưa sinh JSON-LD `Article`; baseline đo 0/3 bài có (`fixtures/baseline/blog_baseline.md`). Thêm khi có sprint riêng cho script đó.

## 6. Title và meta
Số cụ thể (≤ 60 ký tự cho title, 150–160 cho meta) lấy từ `SEO_PLAYBOOK.md` mục 1; không đặt số thứ hai ở đây.
- Từ khoá hoặc khái niệm chính đứng gần đầu title; đọc được với người, không nhồi.
- Meta mô tả trang thành thật, nhắc chủ đề chính tự nhiên, có một lý do để bấm.
- Công thức gợi ý — title: *Chủ đề chính – Điểm riêng của bài*; meta: *động từ hành động + chủ đề + lợi ích + một chi tiết hỗ trợ*.

## 7. Ánh xạ từ khoá ↔ URL, tránh cannibalization
1. Xác định ý định tìm kiếm (thông tin, so sánh, mua).
2. Liệt kê các biến thể từ khoá thực tế.
3. Xếp theo độ khớp ý định, giá trị khả dĩ, mức cạnh tranh.
4. Gán **một** từ khoá hoặc chủ đề chính cho **một** URL.
5. Rà các trang đang cùng nhắm một chủ đề: gộp, hoặc phân lại ý định, hoặc canonical về trang mạnh nhất.

Tín hiệu cannibalization: hai URL của site luân phiên xuất hiện cho cùng một truy vấn, thứ hạng dao động.

## 8. Liên kết nội bộ
- Từ trang mạnh trỏ sang trang cần đẩy.
- Văn bản neo mô tả đúng đích đến; tránh «xem thêm», «tại đây» khi có thể nói cụ thể.
- Bài mới thì nhớ trỏ ngược tới bài cũ liên quan.

## 9. Dạng báo cáo kiểm
Mỗi phát hiện: mức (Cao/Vừa/Thấp) · vị trí · vấn đề · cách sửa. Khuôn A–D của `qa-reviewer` dùng khi rà nội dung bài; mức Cao/Vừa/Thấp ở đây dùng khi rà kỹ thuật cả site. Ví dụ bịa: *[Cao] Nhiều trang bài dùng chung một title mặc định — vị trí: mẫu trang bài — sửa: sinh title riêng từ tên bài.*

## Liên kết
- On-page, E-E-A-T, AI search, cluster: `SEO_PLAYBOOK.md` · YouTube SEO: `YOUTUBE_PLAYBOOK.md`
- Vai: `.agents/roles/seo-specialist.md`

Thiết kế tham khảo: affaan-m/ECC skill `seo` (MIT), viết lại bằng tiếng Việt, không chép đoạn.
