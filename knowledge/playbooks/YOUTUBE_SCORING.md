---
title: "YouTube Scoring Playbook"
doc: playbook
repo: agent-marketing-team
version: "1.1.10"
---

# Chấm điểm ứng viên nội dung YouTube (Opportunity · Risk · Hook · Rights Gate)

Đọc khi: có nhiều đề tài/tập/series ứng viên và cần quyết định làm đầy đủ, làm gọn, để backlog hay loại; hoặc khi kênh đăng lại nội dung có chủ sở hữu khác và phải kiểm quyền trước khi công khai.

Mọi trọng số và ngưỡng trong file này là **ngưỡng khởi điểm, chưa đo**. Kênh chạy vài chu kỳ rồi chỉnh theo dữ liệu của chính mình; không trích chúng như chuẩn ngành.

> **Cổng tài liệu, chưa có cổng máy.** Chưa có script nào tự chặn khi `Rights < 4` hay `Risk >= 3`. Người/agent điền hồ sơ phải tự dừng; QA (`roles/qa-reviewer.md`) kiểm lại ở khâu duyệt.

---

## 1. Nguyên tắc dùng điểm
1. Điểm phục vụ **một quyết định**; chấm xong mà không đổi hành động nào thì bỏ bước chấm.
2. Mỗi tiêu chí chấm số nguyên 0–5. Điểm tổng = tổng (điểm × trọng số), trọng số cộng lại bằng 1,0.
3. Chỉnh trọng số theo bản chất kênh: kênh chạy theo thời sự nâng Timeliness và Impact; kênh thư viện/series nâng Series fit và Community; kênh đăng lại nội dung người khác nâng Rights.
4. Ghi trọng số đã chỉnh vào hồ sơ kênh (`brand.md` của trạm hoặc template chiến lược kênh) để lần sau không chấm bằng thước khác.

---

## 2. Opportunity Score — có đáng làm không

### 2.1 Bộ tiêu chí lõi

| Mã | Tiêu chí | Hỏi gì | Trọng số khởi điểm |
|---|---|---|---:|
| R | Relevance | khớp người xem và định vị kênh đến đâu | 0,20 |
| D | Demand | nhu cầu/độ nóng lúc này | 0,15 |
| I | Impact | ảnh hưởng tới người xem mục tiêu | 0,15 |
| O | Original value | mình thêm được gì mà bản khác chưa có (demo, khung phân tích, biên tập) | 0,20 |
| E | Evidence | bằng chứng có chắc, hoặc việc làm có khả thi | 0,15 |
| S | Series fit | có nối vào series sẵn có để giữ người xem quay lại | 0,10 |
| B | Business fit | có phục vụ mục tiêu chiến dịch | 0,05 |

`Opportunity = 0,20·R + 0,15·D + 0,15·I + 0,20·O + 0,15·E + 0,10·S + 0,05·B`

### 2.2 Biến thể tin/chuyên gia
Giữ khung trên, đổi nghĩa ba mã: D thành **Timeliness** (còn nóng bao lâu), E thành **chất lượng nguồn** (có nguồn sơ cấp không), O thành **góc phân tích riêng**. Dùng cho kênh bám tin, nơi độ mới và độ tin cậy quyết định khả năng được tìm thấy.

### 2.3 Biến thể có quyền (rights-weighted)
Khi nội dung gốc thuộc bên khác, thay bộ tiêu chí bằng bảng dưới và coi **Rights (Rc)** là điều kiện chặn chứ không chỉ là điểm cộng.

| Mã | Tiêu chí | Trọng số khởi điểm |
|---|---|---:|
| Dm | Demand | 0,20 |
| F | Fit với người xem | 0,15 |
| **Rc** | **Rights clarity** (độ rõ về quyền khai thác) | **0,25** |
| L | Tiềm năng xem/nghe dài | 0,15 |
| C | Tiềm năng cộng đồng | 0,10 |
| O | Giá trị bổ sung mình thêm được | 0,10 |
| P | Khả năng sản xuất | 0,05 |

`Opportunity(rights) = 0,20·Dm + 0,15·F + 0,25·Rc + 0,15·L + 0,10·C + 0,10·O + 0,05·P`

Điều kiện chặn: `Rc < 4` ⇒ không công khai dù tổng điểm cao. Rights là quyền phủ quyết, không lấy trung bình.

### 2.4 Từ điểm tới quyết định (ngưỡng khởi điểm, chưa đo)

| Điểm | Quyết định (`decision`) | Nghĩa |
|---|---|---|
| ≥ 4,0 | `full_campaign` | làm đủ bộ: video chủ lực + asset bổ trợ |
| 3,2 – 3,99 | `short_or_post` | làm gọn: Short, post, hoặc thử 3–5 tập nếu là series |
| 2,5 – 3,19 | `backlog` | để lại, chờ góc nhìn hoặc hook tốt hơn |
| < 2,5 | `reject` | loại |

Biến thể có quyền: bất kể điểm, `Rc < 4` chỉ được nghiên cứu và chuẩn bị metadata.

---

## 3. Risk Score — làm thì dính bẫy gì

Chấm 0–5, **không nhân trọng số**; dùng như đèn cảnh báo. Mỗi tín hiệu dưới đây cộng vào mức rủi ro:
- nguồn gián tiếp, không truy ra gốc;
- khẳng định lớn hơn bằng chứng đang có;
- chưa ai tự chạy thử, chỉ có lời kể;
- sản phẩm hay sự kiện chưa phát hành chính thức;
- nhiều bài đưa tin chép lẫn nhau, không có nguồn sơ cấp;
- (kênh đăng lại) nội dung gần như nguyên bản, thiếu phần mình thêm vào nên dễ bị đánh giá là tái sử dụng.

**Điều kiện chặn: `Risk >= 3`.** Khi đó phải làm đủ ba việc:
1. gắn nhãn `[KIỂM CHỨNG]` nội bộ (cùng cơ chế với `AGENTS.md` và `roles/qa-reviewer.md`);
2. không dùng tiêu đề khẳng định tuyệt đối hay giật gân thiếu căn cứ;
3. chờ nguồn sơ cấp, hoặc đổi sang dạng đặt câu hỏi/phản biện thay vì khẳng định.

Đọc cùng Opportunity: cơ hội cao mà Risk cao nghĩa là đề tài nóng nhưng phải hạ giọng, đóng khung "điều cần kiểm chứng".

---

## 4. Hook Score — đoạn nào đủ sức kéo

Dùng để **chọn đoạn làm Short, chọn tiêu đề, chọn cảnh mở**; không dùng để sửa nội dung gốc. Chấm 0–5 từng tiêu chí:

| Tiêu chí | Câu hỏi kiểm |
|---|---|
| Xung đột | có căng thẳng hay mâu thuẫn rõ ngay đầu đoạn không |
| Chủ thể cụ thể | có người/vật cụ thể để người xem bám vào không |
| Được–mất | mức được/mất có đủ lớn để quan tâm không |
| Khoảng trống tò mò | có câu hỏi THẬT chưa được trả lời không (không dựng giả) |
| Tự hiểu được | người chưa biết bối cảnh có hiểu không |
| Không lộ đáp án | còn giữ lại phần đáng xem tiếp không |

Không có công thức cộng cố định: lấy trung bình hoặc xem tiêu chí thấp nhất. Đoạn điểm cao thành ứng viên Short/tiêu đề/cảnh mở; đoạn điểm thấp để ở thân bài.

Khung hook 30 giây cho video dài nằm ở `YOUTUBE_PLAYBOOK.md` mục 1 và `COPY_FRAMEWORKS.md`; không lặp ở đây.

---

## 5. Rights Gate — cổng quyền khai thác

Áp cho kênh nào đăng lại, lồng tiếng, tổng hợp hay biên tập lại nội dung của bên khác. Cổng này đứng **trước** nghiên cứu và sản xuất tốn công. Nội dung nguyên bản 100% của chủ kênh bỏ qua.

### 5.1 Hồ sơ quyền mỗi series
Mỗi series có một hồ sơ gồm các trường sau (tên trường giữ nguyên để dễ đối chiếu):

| Nhóm | Trường |
|---|---|
| Nguồn gốc | `title`, `original_author`, `original_publisher`, `translation_owner` (nếu là bản dịch) |
| Chủ sở hữu thành phần | `derivative_owner` (bản thu/giọng đọc/bản chỉnh), `visual_assets_owner`, `music_license` |
| Điều kiện cho phép | `commercial_use_allowed`, `youtube_distribution_allowed` (mỗi trường: `yes` / `no` / `unknown`), `territory`, `duration` |
| Chứng từ | `proof_documents`, `restrictions`, `review_date` |
| Kết luận | `rights_status` (tách khỏi trạng thái bài đăng) |

Trường để `unknown` được tính là chưa xác minh, không được hiểu là `yes`.

### 5.2 Ba trạng thái
| `rights_status` | Được làm gì |
|---|---|
| `approved` | sản xuất và công khai bình thường |
| `rights_pending` | chỉ nghiên cứu và chuẩn bị metadata, **chưa công khai** |
| `blocked` | dừng hẳn: chưa dựng, chưa dùng lại |

Nối với điểm: `Rc < 4` kéo `rights_status` về tối đa `rights_pending`.

### 5.3 Có giấy phép chưa chắc được kiếm tiền
Giấy phép chỉ nói mình được dùng; nền tảng vẫn xét kênh có giá trị bổ sung riêng hay không. Nội dung chỉ đọc lại theo khuôn mà không thêm gì dễ bị loại khỏi kiếm tiền. Mỗi tập cần ít nhất **3 lớp giá trị riêng** (ngưỡng khởi điểm, chưa đo), ví dụ lời dẫn biên tập, recap, phân tích, tư liệu bổ sung, âm thanh có quyền. Về dài hạn nên tăng tỷ trọng nội dung có giấy phép rõ, nội dung gốc, hoặc hợp tác có hợp đồng, thay vì dựa vào tên tuổi của bên khác.

---

## 6. Dùng ba điểm cùng nhau

```text
Ứng viên
  → Opportunity  → làm đủ / làm gọn / backlog / loại
  → Risk         → giọng điệu và mức khẳng định
  → (nếu làm)  Hook cho từng đoạn → chọn Short / tiêu đề / cảnh mở
```

Hồ sơ một ứng viên nên ghi tối thiểu:

```yaml
candidate:
  title:
  pillar:
  persona:
  opportunity_score:     # 0-5
  opportunity_variant:   # core | news | rights
  rights_clarity:        # chỉ biến thể rights; < 4 = chưa công khai
  risk_score:            # 0-5
  decision:              # full_campaign | short_or_post | backlog | reject
  hook_candidates:       # đoạn + hook_score
  rationale:
```

Trỏ chéo: tăng trưởng và đóng gói → `YOUTUBE_GROWTH.md`; khâu duyệt → `.agents/roles/qa-reviewer.md`.
