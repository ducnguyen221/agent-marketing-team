# Cẩm Nang Phân Phối Nội Dung Đa Kênh (Multichannel Publishing Playbook)

Cẩm nang chiến lược và vận hành phân phối nội dung đa kênh (Omnichannel Engine) cho hệ thống Marketing Team.
Tham khảo kiến trúc thiết kế từ Charlie Hills (`charlie947/social-media-skills`, MIT). Viết mới hoàn toàn bằng tiếng Việt, tối ưu hoá cho mô hình chuyển hoá 1 ý tưởng lõi thành 5 định dạng trên các nền tảng số.

---

## 1. Nguyên Lý Cốt Lõi: Đa Kênh Không Phải Là Sao Chép

Một sai lầm phổ biến trong marketing là sao chép nguyên văn một bài viết dài rồi dán lên mọi nền tảng (Facebook, LinkedIn, X, Blog, Newsletter). Cách làm này khiến nội dung bị giảm tương tác vì mỗi nền tảng có một tâm lý tiêu thụ (consumption psychology) và thuật toán phân phối khác nhau:

| Kênh | Tâm lý người đọc | Kỳ vọng định dạng | Nhịp điệu & Độ dài |
|---|---|---|---|
| **Website Blog / CMS** | Tìm kiếm giải pháp, tra cứu chuyên sâu, đọc có hệ thống | Tiêu đề SEO, mục lục rõ ràng, H2/H3 mạch lạc, bảng biểu, ảnh sơ đồ | 1.200 – 2.500 từ, cấu trúc bài giảng hoặc cẩm nang |
| **LinkedIn** | Tìm kiếm bài học nghề nghiệp, case study thực chiến, góc nhìn lãnh đạo | Mở bài ngắn gọn dưới 3 dòng, ngắt dòng thoáng, tập trung vào bài học cá nhân/doanh nghiệp | 150 – 350 từ, ngắt dòng di động, 3-5 hashtag ngành |
| **Facebook Fanpage & Group** | Tìm kiếm câu chuyện, thảo luận cộng đồng, góc nhìn gây tranh luận | Ngôn ngữ gần gũi, câu chuyện cụ thể, hình ảnh trực quan, không dùng cú pháp Markdown lộ liễu | 200 – 450 từ, bắt buộc có comment ghim dẫn link |
| **Short-form Video (Reels/Shorts/TikTok)** | Giải trí có giá trị, muốn nắm bắt thông điệp trong 45 giây | Hook thị giác + âm thanh 3s đầu, phụ đề lớn, nhịp nói dứt khoát | Kịch bản 110 – 160 từ cho video 45 – 60 giây |
| **Slide Carousel (LinkedIn/IG)** | Học nhanh qua hình ảnh, lưu lại (bookmark) để tra cứu | 5–8 slide, tỷ lệ 4:5 (1080x1350), 1 ý chính mỗi slide, visual nổi bật | 15–30 từ mỗi slide, thiết kế dạng thẻ tóm tắt |
| **Email Newsletter** | Nhận thư từ một người bạn/chuyên gia tin cậy | Giọng văn thân mật (1-on-1), góc nhìn hậu trường (insider insights), không giật tít | 500 – 1.000 từ, định dạng thư điện tử tinh giản |

---

## 2. Chuỗi Chuyển Hoá 1-Thành-5 (The 1-to-5 Content Cascade)

Quy trình chuẩn để chuyển hoá một ý tưởng hoặc tài liệu nghiên cứu gốc (Core Asset / Research) thành 5 định dạng phân phối:

```
                  ┌──────────────────────────────────────────────┐
                  │          Ý TƯỞNG CỐT LÕI (Core Asset)        │
                  │   Case study / Báo cáo phân tích / Insight   │
                  └──────────────────────┬───────────────────────┘
                                         │
        ┌───────────────────┬────────────┴────────────┬───────────────────┐
        ▼                   ▼                         ▼                   ▼
┌───────────────┐   ┌───────────────┐         ┌───────────────┐   ┌───────────────┐
│ ① Long-form   │   │ ② Social Post │         │ ③ Visual      │   │ ④ Short Video │
│ Blog & Email  │   │ LinkedIn / FB │         │ Slide Carousel│   │ Reels / Shorts│
└───────┬───────┘   └───────┬───────┘         └───────┬───────┘   └───────┬───────┘
        │                   │                         │                   │
        └───────────────────┴────────────┬────────────┴───────────────────┘
                                         ▼
                            ┌────────────────────────┐
                            │ ⑤ Pinned Comment       │
                            │ Lead Magnet & Link phễu│
                            └────────────────────────┘
```

1. **Bước 1 (Đúc kết Anchor Asset):** Viết bài phân tích chuyên sâu cho Website / Blog. Đây là tài sản tri thức gốc chứa đầy đủ dữ kiện, số liệu và lập luận.
2. **Bước 2 (Chuyển thể Social Post):** Dùng công thức PAS / BAB / STAR (theo [`COPY_FRAMEWORKS.md`](COPY_FRAMEWORKS.md)) để cô đọng câu chuyện thành bài đăng ngắn trên LinkedIn hoặc Facebook.
3. **Bước 3 (Chuyển thể Slide Carousel):** Rút ra 5–7 luận điểm quan trọng nhất, chuyển thành kịch bản Slide Carousel dạng hình ảnh/infographic (theo [`CAROUSEL_INFOGRAPHIC_PLAYBOOK.md`](CAROUSEL_INFOGRAPHIC_PLAYBOOK.md)).
4. **Bước 4 (Chuyển thể Kịch bản Video ngắn):** Chọn 1 xung đột hoặc 1 kết quả bất ngờ nhất, viết thành kịch bản 45 giây 3 cột (theo [`SHORT_FORM_VIDEO_PLAYBOOK.md`](SHORT_FORM_VIDEO_PLAYBOOK.md)) chuyển sang `agent-voice-studio` lồng tiếng và `agent-video-studio` dựng video.
5. **Bước 5 (Gắn Pinned Comment & Phễu Chuyển Đổi):** Soạn sẵn bình luận ghim kèm hình ảnh minh họa dẫn link về bài blog dài hoặc tài liệu tặng kèm (theo [`PINNED_COMMENT_PLAYBOOK.md`](PINNED_COMMENT_PLAYBOOK.md)).

---

## 3. Quy Chuẩn Trình Bày Trên Thiết Bị Di Động (Mobile-First Formatting)

Hơn 85% người đọc mạng xã hội lướt bằng điện thoại di động. Một đoạn văn 4 dòng trên màn hình máy tính sẽ biến thành một khối chữ dày đặc 10 dòng trên điện thoại, gây ngợp mắt và khiến người đọc lướt qua ngay lập tức.

### Nguyên tắc ngắt nhịp:
- **Câu mở đầu (Hook):** Tối đa 8 từ. Phải nằm trọn vẹn trong dòng đầu tiên trước nút "Xem thêm" (See more).
- **Đoạn văn đơn câu:** Giữa các câu quan trọng có khoảng trống dòng trắng (`\n\n`).
- **Quy tắc 1-3 dòng:** Không có đoạn văn nào dài quá 3 dòng trên màn hình điện thoại.
- **Biến thiên độ dài câu:** Xen kẽ câu cực ngắn (2–5 từ) với câu giải thích vừa phải (12–18 từ). Nhịp điệu này tạo lực hút thị giác tự nhiên.
- **Biểu tượng cảm xúc (Emoji):** Dùng có chủ đích làm điểm neo phân cách ý (tối đa 2–3 emoji trong toàn bài). Tuyệt đối không rải emoji đầu mọi dòng biến bài viết thành văn mẫu quảng cáo.

---

## 4. Bộ Lọc Chống AI Slop (Anti-AI Clichés Filter)

Để bài viết mang đậm bản sắc chuyên gia và không bị nhận diện là văn bản máy sinh tự động, bắt buộc kiểm duyệt qua danh sách cấm dưới đây trước khi xuất bản:

| Cụm từ cấm (AI Clichés) | Vì sao cấm | Cách diễn đạt thay thế bằng tiếng Việt thực chiến |
|---|---|---|
| "Trong kỷ nguyên số ngày nay..." / "Trong thế giới không ngừng biến đổi..." | Mở đầu sáo rỗng, vô nghĩa, không mang lại thông tin mới. | Vào thẳng vấn đề: "3 tháng trước, team tôi gặp sự cố...", "Đa số doanh nghiệp đang lãng phí 40% chi phí vào..." |
| "Không thể phủ nhận rằng..." / "Đóng vai trò quan trọng..." | Lời đệm thừa thãi, thể hiện sự thiếu tự tin trong lập luận. | Khẳng định trực tiếp hoặc đưa số liệu đo lường cụ thể. |
| "Hãy cùng khám phá..." / "Cùng đào sâu vào bức tranh toàn cảnh..." | Giọng văn thuyết trình trường lớp, xa cách người đọc. | Nói như hai đồng nghiệp: "Dưới đây là 3 thứ bạn cần sửa ngay hôm nay:", "Cách tôi làm:" |
| "Là chìa khoá vạn năng...", "Đột phá ngoạn mục" | Cường điệu hoá không có căn cứ. | Nêu rõ điều kiện áp dụng: "Công cụ này giải quyết đúng bài toán X, nhưng sẽ vô dụng nếu hệ thống thiếu Y." |
| "Tóm lại...", "Kết luận lại là..." | Kết bài máy móc. | Dùng câu kết mở, câu hỏi gợi mở thảo luận hoặc một hành động cụ thể có thể làm ngay trong 5 phút. |

---

## 5. Quy Trình Xuất Bản Đồng Bộ (Cross-Platform Cadence)

Theo hợp đồng Khâu ⑥ ([`workflows/06_publish.md`](../../workflows/06_publish.md)):
1. **Lên sóng nội dung dài trước:** Xuất bản bài viết trên Website/Blog và video dài trên YouTube.
2. **Kích hoạt mạng xã hội:** Xuất bản bài post rút gọn trên LinkedIn / Facebook, kèm theo:
   - File Slide Carousel hoặc Video Short nhúng kèm.
   - Bình luận đầu tiên (`--comment-id`) dẫn đường link quay ngược về bài viết dài.
3. **Phân phối vòng 2 (Community & Newsletter):** Gửi bản tin Newsletter tóm lược đến danh sách người đăng ký và chia sẻ thảo luận vào Group chuyên môn liên quan.

---

## 6. Vai của từng kênh

Không kênh nào làm hết mọi việc. Gán vai trước khi lên lịch, rồi chọn định dạng theo vai:

| Vai | Mục tiêu | Định dạng mạnh | Ví dụ kênh |
|---|---|---|---|
| Khám phá | kéo người chưa biết mình | video có hook mạnh, bài tối ưu tìm kiếm | YouTube, tìm kiếm tự nhiên, video ngắn |
| Uy tín | đào sâu, chứng minh năng lực | bài dài, hướng dẫn dài, video dài | blog trên tên miền riêng, bài dài trên mạng nghề nghiệp |
| Cộng đồng | nuôi quan hệ bằng câu chuyện | post kể chuyện, clip ngắn | Facebook, nhóm |
| Giữ chân và chuyển đổi | giữ người đã quen và dẫn tới hành động | bản tin có chọn lọc, nhận định riêng, một CTA | email |

Khi kênh chọn YouTube làm trục: video dài là trục của trụ nội dung, Short kéo khám phá, các kênh còn lại phát lại và nuôi cộng đồng. Bảng «Vai từng kênh» trong `templates/station/_channel/_campaign/campaign.md` là chỗ điền vai cụ thể của chiến dịch.

## 7. Lưới nhịp tuần và giờ đăng

**Nhịp tuần mẫu** (chỉnh theo năng lực sản xuất; lịch cố định tốt hơn «nhớ thì đăng»):

| Thứ | Hai | Ba | Tư | Năm | Sáu | Bảy | CN |
|---|---|---|---|---|---|---|---|
| Việc | bài uy tín | khám phá (vài mẩu ngắn) | uy tín + cộng đồng | khám phá | bài uy tín | nghỉ hoặc trả lời | câu chuyện cộng đồng |

- Trục dài (blog/video): 1–2 lần mỗi tuần hoặc hai tuần một lần, giờ cố định. Bản tin: hàng tuần hoặc hai tuần một lần, giờ cố định.
- Mẩu ngắn rải đều, mỗi ngày ít nhất một điểm chạm ở kênh khám phá.
- Mỗi nội dung xuất hiện ít nhất ở hai kênh để không phụ thuộc một nơi. Nhịp thực tế của chiến dịch lấy từ `cadence` của kênh.

**Giờ vàng** — *điểm khởi đầu, chưa đo* (người xem ở Việt Nam; thay bằng giờ có CTR/retention thật cao nhất sau 4–6 tuần dữ liệu của chính kênh):

| Kênh | Khung thử đầu tiên |
|---|---|
| Mạng nghề nghiệp | giờ đi làm và giờ tan làm |
| Facebook | quanh giờ nghỉ trưa và buổi tối |
| YouTube | trước khung xem buổi tối, để thuật toán có vài giờ «chín» |

Kênh X chưa bật trong pipeline hiện tại nên không có khung giờ ở đây. Vị trí link và hashtag theo kênh nằm ở `output_styles/multichannel-style.md`; thứ tự đăng lấy ở mục 5 của file này.

## 8. Cửa sổ phản hồi sau khi đăng

Đăng xong chưa phải xong phân phối:

| Mốc | Việc |
|---|---|
| T+0 đến T+2 giờ | trả lời mọi comment ngay |
| T+2 đến T+24 giờ | trả lời tin nhắn, quay lại với người đã bình luận |
| T+1 ngày | rà để chia sẻ lại hoặc ghim comment hay nhất |
| T+3 ngày | chốt tương tác, ghi hook thắng cho bài sau |

## 9. Năm nguyên tắc tái chế

1. **Không dán lại nguyên bản.** Mỗi lát phải đổi góc nhìn, độ sâu hoặc định dạng; tái chế không đồng nghĩa với repost.
2. **Lát nào cũng trỏ về trục.** Bài ngắn, Short, post dẫn về nội dung dài.
3. **Giãn nhịp.** Rải đều trong 30 ngày, không phát cùng lúc; mỗi nền tảng có nhịp tiếp cận riêng.
4. **Giữ continuity.** Dùng đúng thuật ngữ đã chốt ở nguồn để các lát không mâu thuẫn nhau.
5. **Đo rồi học.** Ghi lát nào ra tương tác hay lead để lần sau ưu tiên định dạng đó.

### 9.1 Lịch 30 ngày và bốn mốc kiểm
Hai thứ này khác nhau, đừng nhầm:
- **Lịch 30 ngày** là khuôn mẫu: `templates/RECYCLING_PLAN_TEMPLATE.md` (Day 0 đến Day 30, mỗi lát một định dạng; cần ít nhất 5 định dạng khác nhau từ một nguồn).
- **D+3 / D+14 / D+21 / D+30** là bốn mốc kiểm cho nội dung đã chạy tốt, để quyết định có tiếp tục tái chế hay không (xem `.agents/roles/content-strategist.md`).

Lát nào có số liệu thì ghi vào bảng theo dõi của template; mục tái chế chưa đo thì ghi «chưa đo», không đoán.
