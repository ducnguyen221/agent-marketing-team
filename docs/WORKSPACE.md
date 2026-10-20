# Trạm nội dung — hai chế độ cài, và từng thư mục dùng để làm gì

> **Đọc trước khi chạy bộ cài**, và đọc lại khi định xoá một thư mục nào đó trong trạm.

Repo này chỉ chứa **engine**: script, cổng kiểm, quy trình, khuôn mẫu. Nội dung của bạn —
kênh, chiến dịch, bài viết, sản phẩm đã dựng, nhật ký — sống ở một chỗ riêng gọi là **trạm**.
Tách như vậy để `git pull` không bao giờ đụng vào bài của bạn, và để bài của bạn không bao
giờ đi lên một repo công khai.

Trạm là một **khái niệm**, không phải một đường dẫn cố định. Nó nằm ở đâu là do bạn chọn khi
cài.

---

## 1. Hai chế độ cài

| | `embedded` — gọn trong repo | `separate` — trạm ngoài repo |
|---|---|---|
| **Là gì** | trạm = `<repo>/workspaces/` (cài cùng OpcOS thì trạm là `<OPCOS_WORKSPACES>/marketing`), biến cấu hình = `<repo>/.env` | trạm ở thư mục riêng do bạn chọn (không có đường mặc định ở thư mục nhà), bí mật ở kho secret của máy |
| **Lợi** | mở một folder là thấy hết; không phải đặt biến môi trường; sao lưu một phát | repo luôn sạch (an toàn khi repo là bản public của chính bạn); nhiều máy / nhiều repo dùng chung một trạm; cập nhật repo không đụng nội dung |
| **Hại** | xoá folder repo là mất luôn nội dung | thêm một chỗ phải nhớ; phải đặt `MARKETING_STUDIO_DATA` cho lịch chạy thấy trạm |
| **Chọn khi** | một máy, muốn dùng được ngay, không rành kỹ thuật | rành kỹ thuật, nhiều máy, hoặc repo public của chính bạn |

**Khuyến nghị cho người mới: `embedded`.** Bấm Enter ở bộ cài là chọn nó.

```bash
python scripts/pipeline/init_station.py          # hỏi bạn chọn
./install.sh                                     # macOS / Linux — cùng một lõi
.\install.ps1                                    # Windows — cùng một lõi
```

**Máy đã có trạm ngoài thì bộ cài tự chọn `separate`, không hỏi, và không bao giờ tạo
`workspaces/` (trừ khi máy đặt `OPCOS_WORKSPACES` và `<repo>/workspaces` đã có dữ liệu mà chưa chọn lần nào: dữ liệu có sẵn thắng, bộ cài giữ trạm đó).** Nhận diện bằng: đã đặt một trong `MARKETING_STUDIO_DATA`, `VOICE_STATION`,
`VIDEO_STATION`, `OMNIVOICE_DIR`, `VIDEO_ROOT`. Chỉ `MARKETING_STUDIO_DATA` cho biết trạm ở
đâu; các biến còn lại chỉ báo "đã theo mô hình trạm ngoài" nên bộ cài hỏi đường (hoặc đòi
`--station` khi dùng `--yes` / không có người, trừ khi máy đặt `OPCOS_WORKSPACES`). Chọn `separate` thì không có đường mặc định: có
`OPCOS_WORKSPACES` thì đề xuất `<biến>/marketing`, không thì hỏi đường. Có người ngồi, máy đặt
`OPCOS_WORKSPACES`, không `--mode`: Enter/xác nhận ra `<biến>/marketing`; `--yes` và chạy không
người cũng ra đó (một dòng nêu đường) — muốn trạm trong repo thì `--mode embedded`; `<repo>/workspaces`
đã có dữ liệu mà chưa chọn lần nào thì được giữ. Thư mục trạm cũ ẩn trong thư mục cá nhân không còn được dò hay
tự nhận: trỏ vào bằng `--station <đường>`. Lý do: một repo mà có **hai** trạm thì không ai biết
bài mới nằm ở đâu, và `doctor` gọi đó là *hai nguồn sự thật* — nó báo đỏ chứ không đoán hộ.

**Bố cục cũ `<repo>/workspace/` (số ít).** Bản cài trước đặt trạm ở đó. Nó vẫn được nhận nếu
mang `CHANNELS.md` và `<repo>/workspaces/` chưa có (cả hai ngôn ngữ cùng định nghĩa "có thật":
`workspaces` chỉ cần là thư mục, `workspace` phải có `CHANNELS.md`); `init` và `doctor` nhắc một
dòng nên đổi tên thành `workspaces`. Có cả hai thì dùng `workspaces`. Bộ cài mới không bao giờ
tạo thư mục số ít, và không tự dời gì.

### Đừng xoá folder repo để cài lại

Ở chế độ `embedded`, xoá repo là xoá luôn nội dung. Cập nhật engine bằng:

```bash
python scripts/pipeline/studio.py update     # = git pull --ff-only, không xoá gì
python scripts/pipeline/studio.py backup --out ~/sao-luu-tram.zip
```

Đổi ý muốn tách trạm ra ngoài repo:

```bash
python scripts/pipeline/studio.py migrate --to separate [--station <thư-mục-trạm>]
```

Nó **dời** `workspaces/` (hoặc `workspace/` của bố cục cũ) ra ngoài (không chép rồi để lại bản cũ), dời `.env` về kho secret,
rồi ghi lại lựa chọn. Kiểm mọi điều kiện trước khi dời byte đầu tiên; đích không rỗng thì
từ chối và chưa đụng gì.

**Đích dời là việc của bạn chọn — lệnh không có đích ngầm.**

- Không khai `--station` và có người ngồi: lệnh **hỏi** nơi dời. Gợi ý (không áp đặt) là
  `<OPCOS_WORKSPACES>/marketing` nếu biến đó có; không có biến thì **không gợi ý gì** — bạn gõ
  đường (Enter rỗng là dừng). Nó in đường tuyệt đối của đích cùng số file và dung lượng sẽ
  dời, rồi xin `y/N` trước khi dời byte đầu tiên; Enter ở câu xác nhận là **không dời**. Đích
  nằm trong chính trạm nguồn bị từ chối. Đường dán kèm cặp ngoặc kép (Copy as path) vẫn đúng.
- Không có người ngồi (lịch chạy, agent, `--non-interactive`): **bắt buộc** `--station`;
  thiếu thì dừng với mã 2 và chưa đụng gì.
- Có `--station`: dời thẳng, không hỏi. Đường tương đối được đổi thành tuyệt đối.

---

## 2. Thứ tự phân giải — script tìm trạm thế nào

Mọi script đi qua **một** hàm (`scripts/lib/studio_paths.py`), theo đúng thứ tự này:

| # | Nguồn | Khi nào thắng |
|---|---|---|
| 1 | `--station <đường>` | người gõ tay, thắng tất cả |
| 2 | biến `MARKETING_STUDIO_DATA` | máy đã đặt biến (máy chạy lịch thật) |
| 3 | `<repo>/studio.local.json` → `station_path` | bộ cài đã chạy |
| 4 | `<repo>/workspaces/` nếu **có thật** (là thư mục) | chế độ embedded, file cấu hình bị mất |
| 4b | `<repo>/workspace/` (bố cục cũ) nếu có `CHANNELS.md` | bản cài trước, `workspaces/` chưa có |
| 5 | `<repo>/workspaces/` (chưa tạo) | chưa cài gì — `doctor` báo thiếu, bộ cài tạo |

**Không có đường lùi về thư mục trong nhà**: trạm ngoài repo chỉ có khi
bạn chỉ định — biến, `--station`, hoặc chọn `separate` lúc cài.

Biến đứng **trước** `studio.local.json` là có chủ đích: máy nào đã đặt biến từ trước thì một
file cấu hình lạc vào repo không được phép cướp trạm.

**Bí mật** đi theo thứ tự riêng: biến môi trường → `<repo>/.env` (**chỉ** khi
`mode = embedded`) → kho secret của máy. Luật ba tầng không đổi — biến và `.env` giữ **đường
dẫn**, file ngoài git giữ **giá trị**. Chi tiết:
[`knowledge/toolchains/SECRETS.md`](../knowledge/toolchains/SECRETS.md).

**Giới hạn của `.env`, nói rõ một lần:** chỉ biến đi qua `studio_paths.secret_env()` mới
đọc được từ file đó. `.env` tới được **script Python của repo này**, và chỉ thế:

| Nhóm biến | `.env` có tác dụng? | Phải đặt ở đâu |
|---|---|---|
| Trạm & cấu hình máy — `VOICE_STATION`, `VIDEO_STATION`, `OMNIVOICE_PY`, `VOICES_DIR`, `HYPERFRAMES_VERSION`, `WEB_REPO_DIR`, `TG_CONFIG`, `TG_CHAT`, `CHROME_BIN`, `FFMPEG_DIR`, `FFPROBE`, `VIDEO_FONT`, `AGENT_CALL_ENGINES`, `CODEX_BRIDGE` | **có** | `<repo>/.env` là đủ |
| Biến của `.ps1` (`$env:X`) — `MARKETING_STUDIO_DATA`, `MARKETING_STUDIO_HOME`, `MARKETING_STUDIO_PY` | **không** | cấp user (`setx`) / môi trường của scheduled task |
| Đường tới file bí mật mà **hook đăng bài của bạn** đọc — `YT_TOKEN_PATH`, `YT_CLIENT_SECRET`, `FB_CONFIG`, `EMAIL_CONFIG` (kèm hậu tố kênh, vd `YT_TOKEN_PATH__KENH_B`) | **có, qua hai đường** | hook do bước `release` gọi nhận `studio_paths.hook_env()` (môi trường thật + đúng các con trỏ này từ `.env`); job launchd nhận giá trị do `install_launchd.py` điền vào plist ([`launchd.md`](launchd.md)). Script của trạm bạn **chạy tay từ shell** thì không — đặt biến ở shell, hoặc chạy qua lịch |

Không phải đoán: `doctor` liệt kê thẳng dòng **đã điền** nào trong `.env` mà không script
Python nào đọc, và nói rõ dòng nào là biến của `.ps1`. Dòng `TÊN=` còn để trống thì nó im
— bộ cài chép nguyên `.env.example` sang, và chưa điền thì chưa có gì để cảnh báo.

`studio.local.json` (bị gitignore) giữ đúng năm khoá:

```json
{
  "mode": "embedded",
  "station_path": "workspaces",
  "secrets": ".env",
  "voice_station": "…",
  "video_station": "…"
}
```

Hai khoá cuối chỉ có khi máy đã cài `agent-voice-studio` / `agent-video-studio`; bộ cài dò
và ghi hộ để `doctor` khỏi phải đoán.

---

## 3. Rào của chế độ `embedded`

Trạm nằm trong một repo có remote công khai, nên nó có **ba** lớp rào — mỗi lớp bắt cái mà
lớp trước để lọt:

| Lớp | Là gì | Bắt được gì |
|---|---|---|
| `.gitignore` | `/workspaces/` (và `/workspace/` của bố cục cũ), `.env`, `.env.*`, `studio.local.json` | commit vô ý |
| `templates/hooks/pre-commit` | hook do bộ cài cài vào `.git/hooks/` | `git add -f`, `.gitignore` bị sửa, dòng thêm mới trông giống token |
| `scripts/pipeline/doctor.py` | kiểm lại hai lớp trên + quyền `.env` + thư mục đồng bộ đám mây | rào đã chết mà không ai biết |

Cổng `tests/test_gitignore_guard.py` canh **từng dòng** của `.gitignore` theo tên — xoá một
dòng là test đỏ, kể cả khi một mẫu rộng hơn tình cờ vẫn chặn (mẫu rộng hơn có thể biến mất
ở lần dọn sau).

Repo hoặc trạm nằm trong OneDrive / Google Drive / Dropbox / iCloud: `doctor` **cảnh báo**.
Git trong thư mục đồng bộ hay hỏng index hoặc treo, và mọi thứ trong đó — gồm `.env` — đi
lên cloud.

---

## 4. Từng thư mục của trạm

Giống nhau ở cả hai chế độ, chỉ khác gốc.

| Đường | Loại | Ai/cái gì ghi | Vào `backup` / gói chuyển máy? | Nhạy cảm? | Xoá được? |
|---|---|---|---|---|---|
| `CHANNELS.md` | quản lý | bạn · `new_channel.py` | **có** | không | **không** — mất là mọi script hết thấy kênh |
| `AUTHOR.md` | nội dung | bạn | **có** | có (tên thật, liên hệ) | không |
| `<kênh>/channel.yml` | quản lý | bạn · `new_channel.py` | **có** | vừa (chỉ TÊN biến secret) | không |
| `<kênh>/brand.md` | nội dung | bạn | **có** | có (hồ sơ cá nhân) | không |
| `<kênh>/CAMPAIGNS.md` | quản lý | `new_campaign.py` | **có** | không | không |
| `<kênh>/continuity.json` | trạng thái | script lúc đăng | **có** | không | **không** — mất là đăng trùng đề tài |
| `<kênh>/assets/` | nội dung | bạn (logo, ảnh nền, font) | **có** | không | không |
| `<chiến-dịch>/campaign.md` | nội dung + cấu hình | bạn · agent | **có** | không | không |
| `<chiến-dịch>/prompt.txt` | nội dung | bạn | **có** | không | không |
| `<chiến-dịch>/run.ps1` | quản lý | chép từ khuôn của repo | **có** | không | được — chép lại từ `templates/station/` |
| `<chiến-dịch>/out/` | sản phẩm | script dựng ảnh/video/trang | `backup`: cả; gói chuyển máy: **chỉ `*-top.json` và `*.published.json`** | không | mp4/ảnh **được** — dựng lại được; hai loại JSON kia **không** |
| `<chiến-dịch>/logs/` | nhật ký + trạng thái | script | `backup`: cả; gói chuyển máy: chỉ khi `--include-logs-state`, và chỉ tin duyệt chờ · việc chờ · nhật ký sự kiện | vừa (có thể lẫn đường dẫn máy) | `*.log` được; `tg-approve.json`, `jobs/pending/` thì không |
| `<bài>/research.md`, `content.md` | nội dung | agent · bạn | **có** | không | **không** |
| `<bài>/publish.json` | trạng thái | `register_publish.py` | **có** | có (link thật, ID bài) | **không** — mất là mất dấu đã đăng gì |
| `engine/` | mã | chép từ pipeline tin | **có** | không | được nếu bạn không chạy pipeline tin |
| `Auto Task.xlsx` | bản xuất | `export_excel.py` | **có** | vừa | được — xuất lại được |
| `_backup/`, `_task-backup/`, `.tmp*` | rác | công cụ cũ / đồng bộ cloud | **không** | — | được |

**Quy tắc đọc bảng:** cột *Xoá được?* nói về việc dựng lại. "Không" nghĩa là **không có cách
nào dựng lại từ máy** — chỉ còn bản sao lưu.

`backup` mặc định **không** kèm `.env`; muốn kèm phải `--with-env`. Và nó **từ chối** đóng
gói khi trong trạm có file trông giống secret (`*token*`, `*credential*`, `*.pem`, `*.key`):
những thứ đó phải nằm ở kho secret của máy, biến chỉ trỏ đường tới.

**`backup` khác gói chuyển máy.** Cột trên nhắc tới hai thứ khác nhau, đừng lẫn:

```
python scripts/pipeline/studio.py  backup --out ~/sao-luu-tram.zip     # ảnh chụp cho mình
python scripts/pipeline/station.py export --station <trạm> --out <zip> \
       --with-git --include-logs-state                                 # gói bàn giao
python scripts/pipeline/station.py import <zip> --station <trạm mới>
```

`export` đi theo **danh sách khai rõ** (`scripts/lib/station_manifest.py`) nên gói nhẹ hơn
hẳn — trên một trạm 929 MB, gói kèm `.git` chỉ 38 MB — và kèm manifest + sha256 để bên
nhận đếm lại rồi **báo thiếu**. `import` **không đè** file đã có, kiểm sha256 trước khi ghi
byte nào, và đổi đường của máy cũ thành `~`.

---

## 5. Cây mẫu

`templates/workspace/` là cái mà bộ cài chép vào gốc trạm: `CHANNELS.md` (sổ kênh **rỗng**),
`AUTHOR.md` (khuôn danh tính, toàn chỗ trống), `README.md` (bản rút gọn của trang này, để
người mở thư mục trạm đọc được ngay mà không phải quay lại repo).

Ba tầng còn lại **mọc ra bằng lệnh**, mỗi lệnh chép khuôn từ `templates/station/`:

```bash
python scripts/pipeline/new_channel.py  --id <kênh> --label "…" --path ./<kênh>
python scripts/pipeline/new_campaign.py --channel <kênh> --id <mã> --name "…" --prefix XXX
python scripts/pipeline/new_post.py     --campaign <mã> --id XXX-001 --slug … --title "…"
python scripts/pipeline/check_tree.py                       # soi lại cả cây
```

Đừng tạo tay: tên thư mục và khoá trong file phải khớp nhau thì cổng kiểm mới soi được, và
`new_*.py` là chỗ duy nhất biết quy ước đó.

Muốn xem một trạm **đã điền sẵn** trước khi tự dựng — `examples/` trong repo là một trạm
hoàn chỉnh:

```bash
python scripts/pipeline/check_tree.py --station ./examples
```

---

## 6. Khi có gì đó không đúng

```bash
python scripts/pipeline/doctor.py           # trạm ở đâu, rào còn sống không, thiếu gì
python scripts/pipeline/doctor.py --json    # cho máy đọc
```

Mã thoát: `0` đủ để chạy · `2` cấu hình sai, phải **sửa** · `3` chưa cài xong, phải **làm
tiếp**. Phân biệt hai cái sau là để bạn biết mình đang ở đâu: "làm nốt bước còn thiếu" khác
hẳn "cái bạn đã làm đang sai".
