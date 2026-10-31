# SEO kỹ thuật — checklist crawl, index, tốc độ, dữ liệu có cấu trúc

Bổ sung cho `SEO_PLAYBOOK.md` (on-page, E-E-A-T, AI search, cluster). File này chỉ lo phần kỹ thuật và ánh xạ từ khoá ↔ URL; không lặp lại luật heading, alt text, slug.

## Dùng khi
- Kiểm site hoặc blog trước khi đẩy nhiều bài; xem vì sao một trang không lên chỉ mục.
- Rà title/meta, dữ liệu có cấu trúc, tốc độ tải, liên kết nội bộ.
- Lên kế hoạch sitemap, robots, hoặc gom các trang đang tranh cùng một từ khoá.

---

## 1. Thứ tự làm việc
Gặp một site chưa rõ vấn đề, đi theo thứ tự này; mỗi tầng chặn thì dừng và sửa rồi mới sang tầng sau:
1. **Vào được không?** (crawl, mục 2)
2. **Được lưu đúng bản không?** (index, mục 3)
3. **Tải có nhanh không?** (mục 4)
4. **Máy hiểu loại trang không?** (dữ liệu có cấu trúc, mục 5)
5. **Mỗi trang có đúng một việc không?** (từ khoá ↔ URL, mục 7)

Hai lưu ý đi kèm: kiểm bản di động trước vì chỉ mục ưu tiên di động; và mọi khuyến nghị phải nêu đúng trang cần sửa, không viết kiểu «nên cải thiện SEO».

## 2. Crawl
Câu hỏi: máy tìm kiếm có đến được những trang ta muốn không, và có bị dẫn đi lạc không?
- Rà `robots.txt` hai chiều: có chặn nhầm trang quan trọng không, có để lọt bề mặt vô giá trị (trang lọc, kết quả tìm nội bộ) không.
- Rà thẻ `noindex` trước mỗi đợt xuất bản hàng loạt; lỗi quên gỡ thẻ này là kiểu hỏng im lặng phổ biến.
- Trang quan trọng nên cách trang chủ ít bước nhấp (ngưỡng khởi điểm: ≤ 3, chưa đo).
- Mỗi URL nên đến đích sau tối đa hai lần chuyển hướng; dài hơn thì rút gọn.
- Canonical các trang phải khớp nhau, không trỏ vòng.

## 3. Index
Câu hỏi: trang được lưu dưới đúng một địa chỉ mà ta chọn không?
- Chốt một dạng URL (giao thức, có hay không dấu gạch cuối) và dùng thống nhất.
- Có nhiều ngôn ngữ mới cần `hreflang`; một ngôn ngữ thì bỏ.
- Sitemap chỉ liệt kê phần công khai muốn lên chỉ mục.
- Hai URL cùng nội dung mà không có canonical thì tự tranh nhau.

Nối repo: `scripts/pipeline/build_blog_html.py` đã sinh `<link rel="canonical">` (chỉ khi có `slug`); các luật trên giải thích vì sao phải giữ thẻ đó.

## 4. Core Web Vitals
Ngưỡng «tốt» theo tài liệu công khai web.dev về Core Web Vitals (kiểm lại bản hiện hành trước khi trích):

| Chỉ số | Đo gì | Ngưỡng tốt |
|---|---|---|
| LCP | thời gian hiện phần nội dung lớn nhất | ≤ 2,5 giây |
| INP | độ trễ phản hồi khi tương tác | ≤ 200 ms |
| CLS | mức xê dịch bố cục bất ngờ | ≤ 0,1 |

Cách sửa thường gặp: tải trước ảnh đầu trang; giảm phần chặn hiển thị; chừa sẵn chỗ cho ảnh và quảng cáo để bố cục không nhảy; cắt bớt JavaScript nặng. Chưa đo trên site của kênh này thì ghi «chưa đo», đừng báo đã đạt.

## 5. Dữ liệu có cấu trúc (JSON-LD)
Gắn loại theo vai trò của trang:

| Trang | Loại gợi ý | Điều kiện |
|---|---|---|
| Trang chủ | Organization (hoặc loại doanh nghiệp hợp hơn) | khi có thực thể rõ |
| Bài blog | `Article` hoặc `BlogPosting` | luôn hợp |
| Sản phẩm | `Product` + `Offer` | có giá, tình trạng |
| Trang có đường dẫn phân cấp | `BreadcrumbList` | khi có phân cấp thật |
| Mục hỏi–đáp | `FAQPage` | chỉ khi nội dung đúng là hỏi–đáp |

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

**Đã làm (SPR-04 sổ repo):** `build_blog_html.py` sinh JSON-LD `Article`; canonical chỉ in khi có `slug`. (Baseline cũ đo 0/3 bài có JSON-LD: `fixtures/baseline/blog_baseline.md`.)

## 6. Title và meta
Số cụ thể (≤ 60 ký tự cho title, 150–160 cho meta) lấy từ `SEO_PLAYBOOK.md` mục 1; không đặt số thứ hai ở đây.
- Từ khoá hoặc khái niệm chính đứng gần đầu title; đọc được với người, không nhồi.
- Meta mô tả trang thành thật, nhắc chủ đề chính tự nhiên, có một lý do để bấm.
- Công thức gợi ý — title: *Chủ đề chính – Điểm riêng của bài*; meta: *động từ hành động + chủ đề + lợi ích + một chi tiết hỗ trợ*.

## 7. Ánh xạ từ khoá ↔ URL, tránh cannibalization
Lập bảng hai cột «từ khoá hoặc chủ đề chính» ↔ «URL» và giữ quan hệ một–một:
- Mỗi hàng ghi ý định tìm kiếm (tìm hiểu, so sánh, mua), vài biến thể thực tế, và lý do chọn (độ khớp ý định, giá trị khả dĩ, mức cạnh tranh).
- Một chủ đề mà bảng có hai URL: chọn trang mạnh hơn làm trang chính, rồi gộp nội dung, hoặc đổi ý định của trang kia, hoặc đặt canonical về trang chính.
- Dấu hiệu tranh nhau: hai URL của site luân phiên hiện ra cho cùng truy vấn và thứ hạng dao động.

## 8. Liên kết nội bộ
- Bài mới phải có đường dẫn vào từ bài cũ liên quan, và dẫn ra bài cũ ngược lại.
- Dồn liên kết từ trang mạnh về trang muốn đẩy.
- Văn bản neo nói đúng đích đến; tránh «tại đây», «xem thêm» khi nói cụ thể được.

## 9. Dạng báo cáo kiểm
Mỗi phát hiện: mức (Cao/Vừa/Thấp) · vị trí · vấn đề · cách sửa. Khuôn A–D của `qa-reviewer` dùng khi rà nội dung bài; mức Cao/Vừa/Thấp ở đây dùng khi rà kỹ thuật cả site. Ví dụ bịa: *[Vừa] Trang danh mục đi qua 3 lần chuyển hướng mới tới đích — vị trí: đường dẫn cũ của mục «công cụ» — sửa: trỏ thẳng đường cũ về địa chỉ cuối, cập nhật liên kết nội bộ.*

## Liên kết
- On-page, E-E-A-T, AI search, cluster: `SEO_PLAYBOOK.md` · YouTube SEO: `YOUTUBE_PLAYBOOK.md`
- Vai: `.agents/roles/seo-specialist.md`

Thiết kế tham khảo: affaan-m/ECC skill `seo` (MIT), viết lại bằng tiếng Việt, không chép đoạn.
