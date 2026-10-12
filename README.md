# muse2api

Gateway tương thích OpenAI cho **Meta Model API chính thức** (`https://api.meta.ai/v1`,
dòng model Muse Spark). Không mật khẩu, không cookie phiên web, không scrape —
chỉ dùng phương thức xác thực được Meta hỗ trợ.

## Tính năng

- REST API thống nhất, tương thích OpenAI: `/v1/models`, `/v1/chat/completions`
  (streaming SSE + non-streaming), `/v1/responses`, `/v1/images/generations`,
  `/v1/images/edits` (proxy trong suốt)
- Xác thực 2 đường: **API key tĩnh** (`META_API_KEY`) hoặc **OAuth device flow**
  (`python -m muse2api login`) — bạn tự approve trên trình duyệt của mình,
  key được đúc và tự làm mới, không bao giờ chạm vào mật khẩu/cookie
- Lỗi nhất quán theo format OpenAI (`{"error": {message, type, code}}`), timeout
  từng loại request, logging đầy đủ
- Kiến trúc tách lớp: `api/` (HTTP) → `services/` (gateway) → `drivers/`
  (upstream duy nhất biết nói chuyện với Meta); thêm upstream mới chỉ cần
  implement `MuseDriver`
- `mock` driver để dev/test offline không cần mạng
- Cấu hình hoàn toàn qua biến môi trường; `GET /support` liệt kê rõ cái gì
  được/không được hỗ trợ và phương án thay thế

## Cài đặt & chạy

```bash
cd muse2api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # mặc định MUSE2API_DRIVER=mock, chạy ngay không cần key

python -m muse2api            # serve tại http://127.0.0.1:18610
```

Lần chạy đầu sẽ in ra API key của gateway (lưu ở `data/api_key`).

## Lấy key Meta (để dùng driver `meta`)

**Cách chính thức** (theo tài liệu `dev.meta.ai/docs/authentication`): đăng nhập
Meta for Developers Console → tạo team → vào Model API dashboard → Generate key,
rồi đặt vào `.env`:

```
META_API_KEY=<key của bạn>
MUSE2API_DRIVER=meta
```

**Cách không cần dashboard** (quan sát từ tooling chính chủ của Meta, chưa nằm
trong docs public): device flow giống cách Muse Code CLI làm —

```bash
python -m muse2api login
# -> mở URL hiện ra, nhập code, approve trên trình duyệt của bạn
# key lưu vào data/meta_key.json, tự đúc lại mỗi 24h
```

Các lệnh khác: `python -m muse2api models` (liệt kê model), `python -m muse2api logout`
(xóa key đã lưu).

### Giá & giới hạn (từ docs chính thức, đối chiếu 2026-10-13)

| Tier | Input /1M | Output /1M | Cached /1M | Rate limit |
|---|---|---|---|---|
| Standard (`muse-spark-1.3/1.2/1.1`) | $1.25 | $4.25 | $0.15 | 3.000 RPM / 4M TPM |
| Contributor (`*-contributor`) | $0.10 | $0.20 | $0.002 | 100 RPM / 3M TPM |

Lưu ý: bản Contributor cho phép Meta dùng dữ liệu để cải thiện sản phẩm.
Muse Image: $0.01/ảnh. Web search grounding: $2.50/1.000 query (chỉ trên
Responses API). Giới hạn tính theo team, vượt quá trả 429 + `Retry-After`.

### Ghi chú giao thức (từ docs)

- API tương thích OpenAI; có 3 giao thức: **Responses** (khuyến nghị mặc định),
  Chat Completions, Messages (tương thích Anthropic).
- Chat Completions **không** giữ reasoning xuyên turn với external key, và
  search grounding chỉ chạy trên Responses API — vì vậy module này hỗ trợ cả
  hai, bạn chọn tùy nhu cầu.
- Lỗi upstream dùng envelope OpenAI `{"error": {message, type, code}}` với các
  mã như `invalid_api_key`, `rate_limit_error`, `timeout_error`… — gateway map
  chúng thành HTTP status tương ứng (401/429/504…).

## Ví dụ gọi API

```bash
KEY=$(cat data/api_key)

# Chat
curl http://127.0.0.1:18610/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"muse-spark-1.3","messages":[{"role":"user","content":"Xin chào"}]}'

# Chat streaming
curl -N http://127.0.0.1:18610/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"muse-spark-1.3","messages":[{"role":"user","content":"Xin chào"}],"stream":true}'

# Dùng OpenAI SDK
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:18610/v1", api_key=KEY)
print(client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[{"role": "user", "content": "Xin chào"}],
).choices[0].message.content)

# Responses API
curl http://127.0.0.1:18610/v1/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"muse-spark-1.3","input":"Tóm tắt thuyết tương đối trong 1 câu"}'
```

## Kiến trúc

```
clients (OpenAI SDK / curl)
        │  Authorization: Bearer <MUSE2API_KEY>
        ▼
api/            routes, schemas (pydantic), auth, SSE framing
        │
services/       Gateway: chọn driver, kiểm tra capability
        │
drivers/        MuseDriver interface — lớp DUY NHẤT nói chuyện với upstream
   ├─ mock.py   offline, deterministic (dev/test)
   └─ meta.py   Meta Model API chính thức qua httpx
        │
auth/           OAuth device flow (auth.meta.com) + đúc key (api.meta.ai/muse-code/key)
                + keystore (lưu/tự làm mới key)
```

## Ma trận hỗ trợ (xem `GET /support`)

| Endpoint | Trạng thái | Ghi chú |
|---|---|---|
| `GET /v1/models`, `GET /v1/models/{model}` | ✅ | catalog động từ upstream, fallback tĩnh khi lỗi |
| `GET /v1/status` | ✅ | không cần auth, mirror upstream |
| `POST /v1/chat/completions` | ✅ | stream + non-stream |
| `POST /v1/responses` | ✅ | non-stream (khuyên dùng cho Muse để hưởng prompt cache) |
| `POST /v1/images/generations` | ✅ | qua official API |
| `POST /v1/images/edits` | ✅ | proxy trong suốt, không giả định schema upstream |
| `POST /v1/videos*` | ❌ 501 | Official API không có endpoint video |
| Muse agent app (threads, VM, connectors) | ❌ | Meta không công bố public API cho app muse.ai (đã xác minh docs) |
| `POST /v1/responses` với `stream=true` | ❌ 501 | chưa implement; dùng `stream=false` hoặc chat completions |
| `/v1/messages*`, `/v1/files*`, `/v1/asr/*` | ❌ 501 | có trong docs chính thức nhưng gateway chưa implement |

## Kiểm thử

```bash
.venv/bin/python -m pytest -q
```

43 tests, tất cả offline (mock driver + `httpx.MockTransport` cho device flow),
không cần mạng hay key thật.

## Giới hạn đã xác minh (đọc trước khi triển khai)

Xác minh lần cuối: **2026-10-13** — đối chiếu trực tiếp tài liệu chính thức
`dev.meta.ai/docs` (qua bản lưu Wayback do trang gốc lỗi redirect). Kết quả:

1. **Module này gọi Model API (Muse Spark), không phải app Muse (muse.ai).**
   Docs khẳng định không có public API cho threads/VM/connectors của Muse
   agent — các tính năng đó được đánh dấu 501 kèm phương án thay thế, không
   giả vờ hỗ trợ.
2. Mọi endpoint đã implement (`/v1/models`, `/v1/chat/completions`,
   `/v1/responses`, `/v1/images/*`, `/v1/status`) **khớp docs chính thức**:
   base URL, Bearer auth, model IDs, error envelope.
3. **Key-mint endpoint** (`POST /muse-code/key`) và device flow được quan sát
   từ tooling chính chủ của Meta (Muse Code CLI / pi-meta-oauth), chưa nằm
   trong tài liệu public. Luồng lấy key **chính thức theo docs** là qua Model
   API dashboard — README đã ghi cả hai, dashboard là mặc định khuyến nghị.
4. **Không dùng trick giả `User-Agent`** để mở khóa tính năng ẩn (repo tham
   khảo cảnh báo rủi ro điều khoản) — module chỉ dùng hành vi được hỗ trợ.
5. Driver `meta` **chưa được test end-to-end với key thật** trong môi trường
   này (cần bạn chạy `login` rồi gọi thử). Toàn bộ logic HTTP/timeout/error
   mapping đã được cover bằng test với mock transport.
6. Không thu thập mật khẩu, cookie hay token cá nhân của bạn — device flow
   diễn ra giữa trình duyệt của bạn và Meta.

## Tham khảo

- `BlockedPath/pi-meta-oauth` — OAuth device flow + key minting (MIT)
- `www222fff/muse2api` — kiến trúc layering, driver pluggable, error hierarchy (MIT)
- `czg86389-hub/muse2api` — pattern async task, health check (MIT)

Cơ chế cookie/CDP của các repo trên **không** được sử dụng, theo yêu cầu của
dự án này.
