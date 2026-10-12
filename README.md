# muse2api

OpenAI-compatible API gateway for **muse.ai** (your Muse personal agent) via the
**direct protocol** — cookie-only, no browser, no paid API key.

```
You ──POST /v1/chat/completions──▶ muse2api ──Noise XX──▶ your Muse VM
```

## How it works

1. **HTTPS bootstrap** with your muse.ai cookies (Chrome TLS fingerprint):
   `POST /api/auth/check` → access token, `GET /api/session` → VM id,
   `POST /api/hatch/token` → hatch token.
2. **WebSocket** to `wss://hatch.metaaivm.com/v1/noise` +
   `Noise_XX_25519_AESGCM_SHA256` handshake (ephemeral key — nothing to extract
   from the browser besides cookies).
3. **Chat**: `POST /chat/stream` (fire-and-forget), then poll `chat/history`
   for new assistant messages → translated to OpenAI SSE / JSON.

Protocol layer adapted from [nikships/muse-cli](https://github.com/nikships/muse-cli)
(MIT). Meta's internal APIs are unversioned and may change without notice.

## Quick start

**1. Export cookies.** In your browser, open a logged-in `muse.ai` tab →
DevTools (F12) → Application → Cookies → copy these values:

| Cookie | Required |
|---|---|
| `hatch_sess` | yes |
| `hatch_gw` | yes |
| `datr` | recommended |
| `hatch_vml`, `hatch_native_auth_device` | if present |

**2. Run.**

```bash
pip install -e .
export MUSE_COOKIES="hatch_sess=...; hatch_gw=...; datr=..."
export MUSE2API_KEY="pick-a-secret"   # protects /v1/* with Bearer auth
python -m muse2api
# → http://127.0.0.1:8000
```

Multiple accounts (request rotation): `MUSE_COOKIES_FILE` pointing to JSON —
`{"accounts": [{"name": "a", "cookies": "..."}]}` — or `MUSE_COOKIES_1`,
`MUSE_COOKIES_2`, …

**3. Use it like OpenAI.**

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer pick-a-secret" -H "Content-Type: application/json" \
  -d '{"model": "muse", "messages": [{"role": "user", "content": "Xin chào"}]}'
```

## Endpoints

| Endpoint | Notes |
|---|---|
| `GET /v1/models` | `[{"id": "muse", ...}]` |
| `POST /v1/chat/completions` | `stream: true/false`; `messages[]` → one prompt |
| `GET /health` | no auth; per-account status |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MUSE_COOKIES` | — | single account cookie header |
| `MUSE_COOKIES_FILE` | — | JSON file with one or many accounts |
| `MUSE_COOKIES_1…N` | — | extra accounts |
| `MUSE2API_KEY` | — | Bearer key for `/v1/*` (empty = open) |
| `MUSE2API_HOST` / `MUSE2API_PORT` | `127.0.0.1` / `8000` | listen address |
| `MUSE2API_MODEL` | `muse` | model id reported |
| `MUSE2API_POLL_INTERVAL` | `2.0` | seconds between history polls |
| `MUSE2API_WAIT_S` | `300` | max wait for first reply |
| `MUSE2API_QUIET_S` | `10` | silence after reply = done |

## Limitations — read before relying on it

- **Experimental.** The protocol was reverse-engineered by the community and
  verified by its authors, but I could not test it live (no cookies here).
  Expect breakage when Meta updates the web bundle.
- **No true streaming.** Deltas come from polling history every couple of
  seconds — chunky, not token-by-token.
- **One conversation per account.** Requests on the same account are serialized
  and share your main chat. Add accounts for parallelism.
- **ToS gray area.** Muse's supplemental terms prohibit reverse engineering;
  use at your own risk, personal use only.
- **Cookies = your account.** Never commit them, never share the cookie file.
  If cookies expire (401), re-export from the browser.
