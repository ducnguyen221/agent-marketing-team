---
title: "Marketing Measurement Playbook"
doc: playbook
repo: agent-marketing-team
version: "1.1.10"
---

# Sổ tay đo lường & Thử nghiệm tiếp thị (Marketing Measurement Playbook)

Đọc khi: cần thiết kế kế hoạch đo lường, quy ước gắn thẻ UTM, xây dựng hệ thống chỉ số (KPI), hoặc thiết lập đề cương thử nghiệm A/B nhằm đưa ra quyết định dựa trên dữ liệu xác thực.

---

## 1. Nguyên tắc đo lường cốt lõi
1. **Đo lường phục vụ quyết định (Decision-driven Metrics):** Mỗi chỉ số thu thập phải phục vụ một quyết định kinh doanh cụ thể; không thu thập số liệu tràn lan chỉ để làm đẹp báo cáo.
2. **Không kết luận vội khi thiếu mẫu (No Underpowered Claims):** Khi lượng truy cập hoặc số chuyển đổi chưa đạt cỡ mẫu tối thiểu, bắt buộc ghi nhận trạng thái "chưa đủ mẫu" (`insufficient_sample`); tuyệt đối không tự xưng "biến thể thắng cuộc".
3. **Minh bạch nguồn và mốc thời gian:** Mọi số liệu phải ghi rõ nguồn trích xuất (Meta Business Suite, Google Analytics, YouTube Studio) và mốc chốt đo lường (D+1, D+7, D+30).
4. **Bảo toàn lịch sử đo lường:** Không ghi đè hoặc chỉnh sửa các báo cáo snapshot cũ; luôn nối thêm (append) mốc mới vào lịch sử theo dõi.
5. **Không giả định có kết nối API tự động:** Hiện tại hệ thống ghi nhận số liệu thủ công hoặc qua lệnh script; không bịa đặt rằng đã có connector đồng bộ tự động thời gian thực.

---

## 2. Phân cấp hệ thống chỉ số (Metric Hierarchy)

### Cấp 1: Chỉ số kết quả kinh doanh (Business Outcomes / North Star)
- Doanh thu mang lại, Số khách hàng trả phí mới, Chi phí thu hút một khách hàng (CAC), Giá trị vòng đời (LTV).
- Đây là mục tiêu tối thượng mà toàn bộ chiến dịch hướng tới.

### Cấp 2: Chỉ số chuyển đổi trung gian (Driver / Proxy Metrics)
- Số lượt đăng ký nhận tài liệu (Leads), Số cuộc hẹn tư vấn, Tỷ lệ chuyển đổi trang đích (CR), Tỷ lệ nhấp chuột (CTR).
- Phản ánh mức độ hiệu quả của thông điệp và lời chào hàng.

### Cấp 3: Chỉ số tiêu thụ & Tương tác (Consumption Metrics)
- Lượt tiếp cận (Reach), Lượt hiển thị (Impressions), Lượt xem video (Views), Lượt tương tác (Reactions, Comments, Shares).
- Phản ánh độ lan tỏa và khả năng giữ chân độc giả ở đầu phễu.

---

## 3. Quy ước gắn thẻ UTM (UTM Tagging Standards)
Mọi liên kết dẫn về website hoặc trang đích bắt buộc phải có đủ 5 tham số chuẩn hóa (viết thường, không dấu, nối bằng gạch nối `-`):
- `utm_source`: Kênh phát hành (`facebook`, `linkedin`, `youtube`, `email`, `threads`).
- `utm_medium`: Định dạng truyền thông (`social-post`, `newsletter`, `video-desc`, `bio-link`).
- `utm_campaign`: Mã chiến dịch khớp với thư mục bài viết (`cmp-2610-ai-news`).
- `utm_content`: Biến thể nội dung hoặc góc tiếp cận (`cta-button`, `text-link`, `hook-v1`).
- `utm_term`: Từ khóa tìm kiếm hoặc phân khúc độc giả (tùy chọn).

---

## 4. Khung thiết kế thử nghiệm A/B (A/B Testing Framework)

1. **Giả thuyết khoa học:** Soạn theo mẫu: *Nếu thay đổi [Biến số A], thì [Chỉ số chính B] sẽ tăng, vì [Lý do tâm lý/hành vi C].*
2. **Chỉ số chính (Primary Metric):** Duy nhất 1 chỉ số quyết định kết quả thử nghiệm (ví dụ: Tỷ lệ click vào nút đăng ký).
3. **Chỉ số an toàn (Guardrail Metric):** Chỉ số kiểm soát để tránh tối ưu cục bộ gây hại (ví dụ: Tỷ lệ thoát trang, Tỷ lệ hủy đăng ký email).
4. **Cỡ mẫu và thời gian tối thiểu:**
   - Thời gian chạy tối thiểu: Ít nhất 7 ngày đầy đủ để triệt tiêu ảnh hưởng của chu kỳ ngày trong tuần (day-of-week effect).
   - Cỡ mẫu tối thiểu: Cần đủ số lượt chuyển đổi ở mỗi biến thể trước khi đối chiếu; nếu dưới ngưỡng, duy trì trạng thái thử nghiệm chưa kết luận.

---

## 5. Phễu nội dung 5 tầng và cột `funnel`

Phễu thiên về nội dung (không phải phễu bán hàng thuần) giúp gán mỗi bài vào một tầng và đo chỗ tắc bằng số. Cột `funnel_stage` trong dữ liệu chỉ có 4 giá trị (`awareness · consideration · conversion · retention`, xem `knowledge/data_model/DATA_MODEL.md`), nên 5 tầng được ánh xạ như sau:

| Tầng | Vai của nội dung | Chỉ số chính | Giá trị `funnel` |
|---|---|---|---|
| 1. Được thấy | kéo người chưa biết mình | impressions, reach, tỷ lệ người xem mới, CTR | `awareness` |
| 2. Tin | chứng minh giá trị và chiều sâu | thời gian xem/đọc, đọc hết, lưu, chia sẻ | `consideration` |
| 3. Đăng ký | cho một lý do ở lại | tỷ lệ đăng ký, ghi danh bản tin, theo dõi | `consideration` |
| 4. Quay lại | giữ nhịp, tạo thói quen | người quay lại, mở/click email, giữ chân theo tuần | `retention` |
| 5. Kinh doanh | chuyển người đã quen sang hành động | lead, lịch hẹn, đăng ký, doanh thu | `conversion` |

Tầng 2 và 3 cùng map về `consideration`; phân biệt bằng chỉ số chính, không bằng thêm giá trị mới vào cột (không đổi từ vựng dữ liệu).

### 5.1 Tìm điểm tắc rồi mới sửa
So từng tầng với baseline của chính kênh. Tầng rớt nhiều nhất so với baseline là chỗ cần thí nghiệm. **Sửa điểm tắc trước**, đừng tối ưu tầng đang ổn (ví dụ kéo thêm người vào khi tầng Quay lại đang rò).

### 5.2 KPI theo format
Mỗi định dạng có KPI riêng, đặt mục tiêu riêng; không dùng chung một con số cho mọi format.

| Format | KPI chính | KPI phụ |
|---|---|---|
| Video dài | thời gian/% xem trung bình, CTR thumbnail | sub mới mỗi video, comment |
| Short / Reel | lượt xem có tương tác, tỷ lệ xem lại, chia sẻ | follow từ Short |
| Blog dài | traffic tự nhiên, đọc hết, thời gian trên trang | backlink, lead đến từ nút CTA |
| Post mạng xã hội | tỷ lệ tương tác trên người tiếp cận | lưu, chia sẻ, vào trang cá nhân |
| Bản tin | tỷ lệ mở, click | trả lời, giữ chân theo tuần |

KPI chính phải gắn với một tầng phễu (thời gian xem cho tầng Tin, tỷ lệ đăng ký cho tầng Đăng ký, lead cho tầng Kinh doanh). Chỉ số phù phiếm (số người theo dõi, impressions đứng một mình) chỉ là chỉ số phụ.

### 5.3 Giữ chân trước, kéo người mới sau
Hai chỉ số vòng lặp cần theo dõi: **giữ chân theo tuần** (tỷ lệ người xem/đọc tuần này còn quay lại sau 4 tuần) và **hệ số lan truyền** (mỗi người đang dùng/xem kéo thêm bao nhiêu người mới). Chưa có baseline của kênh thì ghi «chưa đo», không mượn con số chung. Nguyên tắc ưu tiên: vá giữ chân trước khi mở rộng thu hút, vì kéo người vào một phễu rò chỉ đốt công sức.

### 5.4 Nhịp rà số
- **Hàng tuần:** chụp số từng kênh, không quá 30 phút; ghi bài tốt nhất, bài kém nhất và đúng một hành động tiếp theo.
- **Hàng quý:** rà cả phễu: điểm tắc ở đâu, trụ nào vượt/hụt, nhóm 10% cao nhất nhân rộng, nhóm 10% thấp nhất dừng hoặc viết lại; đặt giả thuyết cho quý sau. Khâu đo xem `workflows/07_measure.md`.
