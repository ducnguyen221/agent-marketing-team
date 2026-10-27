# Checklist QA một asset — chạy TRƯỚC khi đẩy sang người duyệt

Agent tự chạy. Mục nào trượt thì sửa trước, đừng đẩy sang người kèm lỗi bạn tự thấy được.
Kết quả ghi vào `05_Approval` (11 cột `chk_*`) khi người duyệt xác nhận.

## Nguồn và tính đúng đắn

- [ ] `chk_primary_source` — mọi số liệu có nguồn sơ cấp, ghi rõ ngày
- [ ] `chk_fact_opinion` — đã tách rõ *"Theo [nguồn]…"* với *"Theo mình…"*
- [ ] `chk_quote_attribution` — rà từng câu mở bằng «Theo X» và từng đoạn trong ngoặc kép:
      lời gán cho nguồn nào thì nguồn đó có thật trong tư liệu đang cầm, truy được tới đoạn
      cụ thể; tiêu đề bài báo không được trích như lời của toà soạn; mốc thời gian và quan hệ
      nhân quả cũng là dữ kiện, phải có nguồn
- [ ] Mọi claim chưa xác minh được đều mang tag `[KIỂM CHỨNG]`, và
      `verification_open` đã đếm đúng số tag còn mở
- [ ] Không bịa số, không bịa tỷ lệ, không bịa tên khách hàng
- [ ] Danh sách «không bịa»: số liệu, trích dẫn, khách hàng, kết quả đạt được, trải nghiệm
      cá nhân. Chưa có thật thì nói rõ là giả định hoặc tổng hợp, không viết như đã xảy ra

## Đóng gói

- [ ] `chk_title_no_overclaim` — title không hứa quá nội dung thật đưa được
- [ ] Hook khớp title (không promise mismatch)
- [ ] `chk_thumbnail_honest` — thumbnail không đánh lừa; chữ trên thumbnail 2–4 từ
- [ ] Số tập đặt ở **cuối** title, không phải đầu

## Giữ chân và chuyển đổi

- [ ] `chk_subscribe_reason` — có lý do rõ ràng để đăng ký, không phải "nhớ subscribe nhé"
- [ ] `chk_next_bridge` — có đường xem tiếp (playlist, related video, link bài trước)
- [ ] Asset này có chức năng riêng, không trùng hook + luận điểm + CTA với asset khác
      trong cùng chiến dịch
- [ ] Asset đã được ghi vào kế hoạch tái chế (recycling plan) của chiến dịch

## Kênh

- [ ] `chk_hashtag_ok` — đúng giới hạn: YouTube ≤3 · Shorts 3–5 · Reel ≤6 · Facebook 6–13
- [ ] Định dạng đúng kênh (FB dùng Unicode bold + `———` chứ không dùng markdown)
- [ ] Link đặt đúng chỗ theo kênh (Facebook: link ở **COMMENT đầu tiên**; thân bài **không có URL ngoài**)
- [ ] Độ dài trong khoảng của kênh (xem bảng nhịp điệu & độ dài ở `knowledge/playbooks/MULTICHANNEL_PUBLISHING.md`)

## Cổng đếm được — chạy máy, không chấm bằng cảm giác

Checklist ở trên là phần người đọc. Phần máy đo chạy bằng lệnh, và **kết quả phải được dán
vào review** — nói "đã kiểm rồi" mà không có JSON thì coi như chưa kiểm.

```bash
python scripts/pipeline/blog_gates.py <thư mục bài>      # 24 cổng -> gates.json, exit!=0 khi đỏ
python scripts/pipeline/fb_format.py --check facebook/post.txt --comment facebook/comment.txt
```

**Luật phát ngôn của cổng:** cổng chỉ được nói **cái nó đo được**.

- Đúng: *"`facebook/post.txt` có 2 URL trong thân bài (dòng 1, dòng 7); luật hiện hành = 0"*.
- Sai: *"bài này sẽ bị Facebook bóp reach"* — cổng không đo được reach, đó là suy đoán.

Cổng đỏ → `quality_check = failed` + ghi `review_feedback`. **Không** tự sửa rồi cho qua im lặng.

## Tuân thủ và an toàn

- [ ] `chk_cta_ok` — CTA thương mại chỉ xuất hiện ở tập được phép
      (`01_Brief.commercial_cta_episodes`)
- [ ] Nhắc tổ chức hay sản phẩm của tác giả chỉ khi làm bài thực tế hơn, ở dạng trải nghiệm;
      bỏ tên đi mà bài vẫn nguyên nghĩa thì bỏ. Không biến bài thành quảng cáo
- [ ] `chk_no_internal_tool` — **grep toàn bộ nội dung, kết quả phải rỗng**: tên công cụ
      và hạ tầng sản xuất nội bộ, cụm "giọng AI"
- [ ] `chk_no_pii` — không có thông tin định danh cá nhân, không credential, không token
- [ ] Ảnh/nhạc/tư liệu đều rõ quyền sử dụng

### Rights Gate series
Áp khi sắp công khai một series hoặc tái dùng nội dung của bên thứ ba (theo `knowledge/playbooks/YOUTUBE_SCORING.md` mục 5):
- [ ] Hồ sơ quyền của series có `rights_status = approved`, tức đủ: `youtube_distribution_allowed = yes`, `territory = yes`, `duration = yes`, có `proof_documents`, `Rc ≥ 4` (kênh bật kiếm tiền thêm `commercial_use_allowed = yes`).
- [ ] Trường điều kiện `unknown`/bỏ trống ⇒ `rights_pending`; trường nào `no` ⇒ `blocked`. `rights_pending` hoặc `blocked` ⇒ **không công khai**; ghi vào báo QA đúng trường đang chặn.

## Giọng

- [ ] Đúng giọng tác giả của kênh: đối chiếu với hồ sơ giọng (`brand.md`) của chính kênh;
      chưa có hồ sơ thì ghi «chưa đo», không tự suy quy tắc từ một bài mẫu
- [ ] Xưng hô, ký hiệu chốt ý và thủ pháp câu quen khớp hồ sơ; không «làm đều, làm đẹp» những
      nét hồ sơ ghi là đặc trưng
- [ ] Có luận điểm riêng, không phải tóm tắt trung tính
- [ ] Có ví dụ hoặc số cụ thể
- [ ] Có ẩn dụ đời thường (với bài dài)
- [ ] Kết luận có tiêu chí, không lửng kiểu "tùy nhu cầu"
- [ ] Không buzzword rỗng, không giật gân, không listicle "Top 10"
- [ ] Self-check giọng, thêm ba dòng: (1) xưng hô nhất quán từ đầu đến cuối; (2) mỗi thuật ngữ
      giải nghĩa ở lần đầu xuất hiện; (3) có mở rộng sang khái niệm lân cận để người đọc biết
      đường đào tiếp

---

## Luật vàng khi phát hiện lỗi trong nội dung public-facing

Nội dung công khai mang giọng của tác giả. **Sửa sai còn tệ hơn để nguyên.**

Khi phát hiện lỗi, đừng tự sửa. Ghi thành danh sách, mỗi mục có:

| Trường | |
|---|---|
| Vị trí | file + dòng |
| Hiện tại | trích nguyên văn |
| Đề xuất | bản sửa cụ thể |
| **Độ tự tin** | **cao** = suy ra chắc chắn · **thấp** = có nhiều khả năng |

Mục **độ tự tin cao** → đề xuất và chờ một tiếng gật.
Mục **độ tự tin thấp** → nêu 2 phương án, để người chọn. Không đoán.

Ví dụ thật: heading `𝐄̆𝐈𝐄̂̉𝐌 𝐂𝐇𝐔𝐍𝐆` suy ra được là `ĐIỂM CHUNG` (tự tin cao, vì
`Đ` → `Ĕ` là lỗi chuyển Unicode bold đã biết). Nhưng `𝐐𝐔𝐀𝐍 𝐄̆𝐁𝐈𝐄̣̂𝐓 𝐍𝐇𝐀̂́𝐓`
thì không suy được — phải hỏi.
