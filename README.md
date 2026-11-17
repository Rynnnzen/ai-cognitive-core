# AI Cognitive Core — MCP Server

Arsitektur kognitif hibrida **Deterministik + LLM (17 Layer)** — Heart + Conscious + Memory — sebagai MCP server, dengan sinkronisasi state lintas perangkat lewat Google Drive API v3.

Snapshot ini adalah **v0.3.1 (patched)** dari v0.3.0 maintainer. Daftar patch ada di `PATCH_NOTES.md`.

## Instalasi

```bash
git clone https://github.com/<username>/ai-cognitive-core.git
cd ai-cognitive-core
pip install -e .
```

Atau langsung dari GitHub:

```bash
pip install git+https://github.com/<username>/ai-cognitive-core.git
```

Butuh Python >= 3.10. Dependensi: `numpy`, `mcp<2`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `PySocks`.

## Sinkronisasi Google Drive

Autentikasi memakai OAuth (bukan service account). Siapkan `client_secret.json` dari Google Cloud Console (Desktop app, scope Drive), lalu:

```bash
ai-cognitive-auth /path/ke/client_secret.json
```

Token tersimpan di `~/.ai_cognitive_state/token.json`. State lokal (`heart_state.json`, `cognitive_memory.db`) ikut tersinkron ke folder `ai_cognitive_system/live_state` di Drive.

Environment variable yang didukung:

- `GDRIVE_TOKEN_PATH` — path `token.json` (default `~/.ai_cognitive_state/token.json`)
- `GDRIVE_CLIENT_SECRET_PATH` — path `client_secret.json`
- `COGNITIVE_DEVICE_ID` — nama perangkat, misal `hermes_pc` atau `muse_cloud`

## MCP Tools

1. `cognitive_perceive_and_think(user_input: str)` — persepsi + emosi + memori sebelum menjawab
2. `cognitive_commit_turn(user_input: str, agent_response: str, inner_monologue: str, novelty: float, goal_conduciveness: float, coping_potential: float, norm_compatibility: float)` — simpan turn ke memori episodik
3. `cognitive_sleep_cycle()` — konsolidasi memori + isi ulang energi
4. `cognitive_get_status()` — status energi, mood, dan memori
5. `cognitive_configure_persona(...)` — atur persona (hati-hati: nilai default menimpa attachment yang sudah ada)

Jalankan servernya dengan `ai-cognitive-mcp` (stdio).

## File pribadi TIDAK ada di repo ini

Repo ini hanya berisi kode. File berikut disiapkan per perangkat dan tidak pernah di-commit (lihat `.gitignore`):

- `token.json`, `client_secret.json` (kredensial OAuth Drive)
- `heart_state.json`, `cognitive_memory.db` (state + memori personal)
