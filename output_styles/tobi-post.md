# Output Style — Facebook Post dài (khuôn giọng kênh)

> Khuôn chuẩn cho **bài post Facebook dạng dài** của một kênh/Page. Đây là **khuôn điền chỗ trống**:
> mỗi kênh thay các ô `<...>` bằng thông tin của mình (tên kênh, người viết, hashtag thương hiệu, lĩnh vực).
> FB post = **bản full-content** đăng thẳng trên feed, KHÔNG phải teaser ngắn.
> Agent đọc file này + [WEBSITE_BLOG_GUIDELINE](WEBSITE_BLOG_GUIDELINE.md) + lăng kính góc nhìn của kênh
> (khối `> **Góc nhìn:**` ở mục "Checklist trước khi xuất bản" trong `WEBSITE_BLOG_GUIDELINE.md`) trước khi viết.
> Tên file giữ nguyên để các tài liệu khác còn trỏ tới được; nội dung không gắn với một người hay Page cụ thể.

---

## VOICE PROFILE (machine-readable)

```yaml
channel: <TÊN KÊNH>
author: <TÊN NGƯỜI VIẾT HOẶC PAGE>
domain: <lĩnh vực>
relation_to_blog: mỗi blog có 1 FB post tương ứng. Post = viết lại blog cho feed FB
                  (giữ trọn lập luận, đổi format sang FB-native). KHÔNG chỉ dán link + 2 câu.
length: 4.000–7.500 KÝ TỰ — đo bằng KÝ TỰ, không phải từ. Facebook đếm ký tự, và một bài
        tiếng Việt vài nghìn từ vượt xa trần hiển thị. Ngưỡng lấy từ các bài đã đăng của kênh
        (xem `fixtures/baseline/blog_baseline.md`), không lấy từ cảm giác.
xung_ho: <cách tự xưng của người viết> (thân mật hơn blog). Độc giả "bạn" / "anh chị em".
tone: thân thiết + chuyên môn + hài hước nhẹ, không lên giọng.
opening_hook:
  - câu hỏi/đối lập đặt thẳng vào vấn đề của người đọc
  - hoặc câu hỏi thật từ khách hàng/người đọc.
  - link blog đặt ở ĐẦU bài (FB ưu tiên reach khi link sớm + nội dung đầy đủ bên dưới).
never:
  - teaser cụt "đọc full ở blog 👇" mà không có nội dung
  - clickbait rỗng, "excited to share"
  - markdown (** _ #heading) — FB render literal, KHÔNG dùng
```

---

## FORMAT FACEBOOK-NATIVE (khác blog — vì FB không có markdown)

1. **Tiêu đề phụ = Unicode bold** (vì FB không in đậm được). Dùng ký tự toán học đậm:
   - Ví dụ: `𝐇𝐞𝐚𝐝𝐢𝐧𝐠 𝟏` · `𝐓𝐢𝐞𝐮 𝐝𝐞 𝐩𝐡𝐮`
   - Bảng mã (dán trực tiếp, KHÔNG có font nào phải cài):
     | Kiểu | Khoảng Unicode | A | a | 0 |
     |---|---|---|---|---|
     | Bold hoa/thường | U+1D400 / U+1D41A | 𝐀 | 𝐚 | — |
     | Bold số | U+1D7CE | — | — | 𝟎 |
   - Chữ có dấu tiếng Việt KHÔNG có bản bold trong Unicode. Cách duy nhất đúng: tách
     dấu ra (NFD), bold chữ cái nền, giữ nguyên dấu tổ hợp — `fb_format.py` làm việc này.
   - Kiểm bằng `python scripts/pipeline/fb_format.py --check fb_post.txt` (in JSON, exit≠0 khi trượt).
2. **Ngắt section** bằng dòng `———————` hoặc `-----` (3+ ký tự).
3. **Emoji số** cho danh sách bước: 1️⃣ 2️⃣ 3️⃣… ; **emoji nhóm** đầu mỗi phần (🧠 🚀 🎯 💡 ⚠️ ✅ ❌).
4. **Emoji action** rải vừa phải trong thân: 👉 😄 🔥 🤔 (1–2/đoạn, không lạm dụng).
5. **Đoạn ngắn** — 2–4 câu/đoạn, nhiều khoảng trắng để dễ đọc trên mobile.

---

## CẤU TRÚC POST CHUẨN
```
[Hook 1–2 câu: đối lập / câu hỏi thật]  🚀
← KHÔNG có link nào ở đây. Thân bài 0 URL.

———————
𝐇𝐞𝐚𝐝𝐢𝐧𝐠 𝟏  🧠
[2–4 đoạn ngắn + bullet/emoji-số]

———————
𝐇𝐞𝐚𝐝𝐢𝐧𝐠 𝟐  🚀
…

———————
[Câu chốt mạnh — dạng "không phải X mà là Y", đứng riêng 1 dòng]

[CTA mềm: mời theo dõi / hẹn bài sau của <TÊN KÊNH>]

[6–13 hashtag]
```

---

## HASHTAG (6–13 cái, cuối bài)
- **Thương hiệu cố định** (luôn có 2–3): `<hashtag thương hiệu 1>` `<hashtag thương hiệu 2>` `<hashtag thương hiệu 3>`
- **Chủ đề** theo pillar của kênh: `<hashtag chủ đề 1..n>` (điền theo <lĩnh vực>).
- Mix tiếng Anh (reach) + tiếng Việt (thương hiệu). Không spam >13.

---

## CTA (luôn mềm, không bán hàng cứng)
- Xây kỳ vọng bài sau: "Bài tiếp theo mình sẽ quay lại chủ đề này, đi sâu vào…"
- Đồng hành: "Mình sẽ đồng hành cùng các bạn trong hành trình này nhé 😊"
- Mời đọc full/blog: **KHÔNG dán link vào thân bài.** Chốt bằng chữ ("bản đầy đủ mình để dưới
  comment nhé") rồi đặt link ở comment đầu tiên — nội dung comment nằm ở `fb_comment.txt`.

---

## VÍ DỤ HOOK + CHỐT THẬT (minh hoạ, điền theo kênh)
Các ví dụ dưới đây là **hư cấu, minh hoạ cấu trúc** — không phải bài đã đăng. Mỗi kênh tự viết hook và câu chốt của riêng mình.

| Chủ đề | Hook | Câu chốt |
|--------|------|----------|
| Công cụ ghi chú | "Dùng ba ứng dụng ghi chú cùng lúc mà vẫn không tìm ra ý tưởng tuần trước. Vấn đề nằm ở đâu?" | "Không phải thêm công cụ, mà là bớt đi một bước." |
| Học một kỹ năng mới | "Xem 20 video hướng dẫn rồi vẫn chưa làm được gì. Nghe quen không?" | "Học xong một việc nhỏ còn hơn xem hết một khoá dài." |
| Tự động hoá việc lặp lại | "Mỗi sáng mất 30 phút copy số liệu giữa hai bảng tính… có cách nào khác không?" | "Máy làm phần lặp lại, mình giữ phần quyết định." |
| Làm việc nhóm | "Cả nhóm đều bận, nhưng không ai biết ai đang làm gì. Bắt đầu sửa từ đâu?" | "Rõ việc trước, nhanh việc sau." |

---

## CHECKLIST TRƯỚC KHI XUẤT
- [ ] Thân bài **0 URL**, và có `fb_comment.txt` chứa link atlas + link video?
- [ ] Hook đối lập/câu hỏi thật?
- [ ] Tiêu đề phụ Unicode bold + ngắt `———`?
- [ ] Đoạn ngắn 2–4 câu, emoji vừa phải?
- [ ] Câu chốt mạnh đứng riêng?
- [ ] CTA mềm + 6–13 hashtag (có hashtag thương hiệu của kênh)?
- [ ] KHÔNG markdown literal, KHÔNG teaser cụt?
- [ ] Mọi ô `<...>` đã được điền theo kênh?
