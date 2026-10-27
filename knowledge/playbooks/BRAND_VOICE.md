# Brand voice playbook — dựng, ghi và kiểm giọng kênh

Quy trình dựng một hồ sơ giọng từ tư liệu thật, ghi vào đúng chỗ, rồi dùng nó để kiểm bài. Đây là thủ tục, không phải kho giọng có sẵn: mỗi giọng thuộc về một kênh và nằm ở trạm của kênh đó.

## Dùng khi
- Kênh mới chưa có mục «Giọng & chính kiến» trong `brand.md`, hoặc mục đó còn trống.
- Cần viết hộ một tác giả mà chưa có hồ sơ giọng khớp với tư liệu gần đây.
- Cần rà một bản nháp xem có lệch giọng không (trước Cổng duyệt).

Không dùng khi chỉ cần luật chung về nguồn, claim, giới hạn kênh: đọc `.agents/checklists/QA_ASSET.md`.

---

## 1. Nguồn mẫu theo bậc

Chọn tập nguồn mạnh nhất đang có, theo thứ tự ưu tiên giảm dần:

| Bậc | Loại nguồn | Ghi chú |
|---|---|---|
| 1 | Bài gốc gần đây do chính tác giả đăng (post, thread, video script) | Chất liệu tốt nhất vì phản ánh cách viết hiện tại |
| 2 | Bài dài: blog, newsletter, ghi chú ra mắt, bản nhận định | Cho thấy cách lập luận và chuyển ý |
| 3 | Thư hoặc tin nhắn thật đã có phản hồi tốt | Cho thấy giọng một-một; bỏ tên, liên hệ và nội dung riêng của người khác trước khi trích, hồ sơ chỉ giữ đặc điểm giọng |
| 4 | Tài liệu sản phẩm, changelog, chữ trên trang đích | Chỉ làm nền; thường khô hơn giọng thật |

Quy tắc thu thập:
1. Lấy khoảng 5–20 mẫu nếu có (ngưỡng khởi điểm, chưa đo). Ít hơn thì ghi `confidence` thấp trong hồ sơ.
2. Ưu tiên mẫu mới; chỉ dùng mẫu cũ khi tác giả nói đó mới là giọng chuẩn.
3. Không dùng ví dụ mẫu chung của một nền tảng làm nguồn: đó không phải giọng của ai.
4. **Giọng ra mắt vs giọng làm việc.** Nếu tập mẫu tách hẳn hai nhóm (bài công bố trang trọng; trao đổi nội bộ suồng sã), ghi thành hai hồ sơ nhỏ và nói rõ hồ sơ nào áp cho kênh nào. Đừng lấy trung bình hai nhóm thành một giọng nhạt.
5. Nếu nội dung trang đích hoặc định vị sản phẩm có ảnh hưởng, thêm chữ hiện hành của chúng vào tập mẫu.

## 2. Khuôn hồ sơ giọng: một chuẩn

Khuôn chuẩn của repo là khối `VOICE PROFILE` ở `output_styles/WEBSITE_BLOG_GUIDELINE.md` (mục 1, dòng 10–33). Không tạo khuôn thứ hai. Khi dựng hồ sơ mới, điền đúng các trường đó, và **chỉ bổ sung ba chiều** khuôn hiện chưa hỏi:

| Chiều thêm | Câu cần trả lời từ tư liệu |
|---|---|
| Ngoặc đơn | Dùng để thu hẹp, bổ nghĩa, hay đùa? Hay hầu như không dùng? |
| Tần suất số liệu · cơ chế · biên nhận | Bao lâu thì bài có một con số, một lời giải thích cơ chế, một bằng chứng cụ thể? |
| Cách chuyển ý | Chuyển bằng từ nối, bằng câu hỏi, bằng ngắt dòng, hay nhảy thẳng? |

Các chiều đã có sẵn trong khuôn (nhịp câu, mức nén, viết hoa, câu hỏi, cách đưa chính kiến) giữ nguyên, không hỏi lại.

Giữ hồ sơ ngắn, dạng gạch đầu dòng, dùng lại được trong ngữ cảnh một phiên. Mục đích là tái sử dụng khi viết, không phải phê bình văn chương.

## 3. «Banned move» phải quan sát được

Mỗi mục trong danh sách «không bao giờ» của một hồ sơ cần một trong hai lý do:
- **Quan sát được:** nêu được ít nhất một chỗ trong tập mẫu cho thấy tác giả tránh thủ pháp đó, hoặc
- **Do người dùng yêu cầu rõ:** ghi «theo yêu cầu của tác giả».

Điều cấm không có bằng chứng thì chỉ là sở thích của người viết hồ sơ. Khi tập mẫu mâu thuẫn nhau, ghi chỗ tách ra thay vì trộn.

> **Danh sách cấm thuộc từng giọng, không có danh sách chung.** Một thủ pháp bị cấm ở giọng này có thể là chữ ký của giọng khác (ví dụ: câu chốt đối lập «không phải X, mà là Y» là bắt buộc ở khuôn blog của repo này). Vì vậy repo không giữ danh sách cấm toàn cục; mỗi hồ sơ tự liệt kê và tự chứng minh.

## 4. Kiểm bài theo giọng: PASS / REVISE / BLOCK

Dùng khi rà bản nháp so với hồ sơ giọng. Ánh xạ sang thang A–D của `.agents/roles/qa-reviewer.md`, không thêm từ vựng mới:

| Kết luận | Tương ứng | Làm gì |
|---|---|---|
| **PASS** | không có mục loại A hoặc B về giọng | Giọng đạt. PASS không phải lệnh được đăng — vẫn đi hết cổng duyệt |
| **REVISE** | có mục loại B (giọng lệch, sửa được) | Bảng: trích đoạn · vấn đề · cách sửa; kèm bản sửa chỉ ở các đoạn trượt, giữ nguyên dữ kiện đã duyệt |
| **BLOCK** | có mục loại A (claim không kiểm chứng được hoặc bịa) | Liệt kê nguồn hoặc xác nhận còn thiếu; không sửa cho trôi |

Danh sách «không bao giờ bịa» (số liệu, trích dẫn, khách hàng, kết quả) nằm ở `.agents/checklists/QA_ASSET.md`; không chép lại ở đây.

## 5. Thủ pháp đặc thù theo giọng: nói rõ vị thế trước khi phản biện

Một số giọng có thủ pháp riêng; ghi vào mục «Preferred Moves» của hồ sơ chứ không đưa thành luật chung. Ví dụ hữu ích khi viết bài phản biện một công cụ hay quan điểm đang được tranh luận: mở bằng một câu nói rõ mình đứng ở góc nhìn nào và không nhằm mục đích gì, rồi mới chỉ ra điểm chưa ổn.

Mẫu trung tính (bịa, chỉ để minh hoạ cấu trúc): «Mình viết phần này từ góc nhìn của người dùng công cụ hằng ngày, không nhằm chê ai. Có ba chỗ mình thấy chưa khớp với cách nó được giới thiệu.»

Giữ dữ kiện tách khỏi ý kiến: câu vị thế không thay cho nguồn.

## 6. Lưu hồ sơ ở đâu

- **Hồ sơ giọng của một người cụ thể không vào repo này.** Lưu ở `brand.md` của trạm kênh (mục «Giọng & chính kiến»), nơi chỉ chủ kênh thấy; `channel.yml` đã ghi rõ phần đó không vào repo.
- Dùng lại hồ sơ đã xác nhận gần nhất cho các việc liên quan trong cùng phiên; đừng dựng lại từ đầu.
- Muốn lưu thành tệp bền, chỉ lưu khi người dùng yêu cầu, và ở trạm, không ở repo.

## Liên kết
- Khuôn hồ sơ: `output_styles/WEBSITE_BLOG_GUIDELINE.md` · Trạm: `templates/station/_channel/brand.md`
- Kiểm bài: `.agents/checklists/QA_ASSET.md`, `.agents/roles/qa-reviewer.md`

Thiết kế tham khảo: affaan-m/ECC skill `brand-voice` (MIT), viết lại bằng tiếng Việt, không chép đoạn.
