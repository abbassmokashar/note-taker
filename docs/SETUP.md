# Setup

This guide takes you from a fresh machine to a working bot. Steps marked
**HUMAN STEP** cannot be automated — you must do them once, by hand.

---

## 1. Install prerequisites

**HUMAN STEP.**

- **Docker Desktop** (Windows/macOS) or `docker` + `docker compose` (Linux).
- If you have an NVIDIA GPU, install the **NVIDIA Container Toolkit** so the
  container can use it for faster-whisper.

For the development (non-Docker) path you also need **Python 3.11+**.

```bash
docker --version
docker compose version
```

## 2. Create the bot's Google account

**HUMAN STEP.**

Create a **dedicated** Google account for the bot (e.g. `yourname.notetaker@gmail.com`).
Use a separate account — not your main one — so the bot is not your identity and can be
removed from meetings independently.

> Why: Google Meets' bots are visible participants. A dedicated account keeps the
> bot's profile, calendar access and cookies isolated from you.

## 3. Configure and start the container

```bash
cp config.example.yaml config.yaml
cp .env.example .env
# edit config.yaml (time zone, display name, join rules, bot.account_email)
docker compose up --build -d
docker compose exec meetingbot meetingbot doctor
```

`meetingbot doctor` prints your configuration and which secrets/tools are present.
Fix anything marked *missing* before continuing.

## 4. Sign the bot into Google (one-time)

**HUMAN STEP.** (Available from Phase 3.)

```bash
meetingbot login-bot
```

This opens a browser you can see (via VNC/noVNC or on the host) so you can sign the
bot account in once — including 2FA. The session is saved to `data/browser_profile`.
You will not have to do this again unless Google invalidates the session.

## 5. Google Cloud: Calendar API

**HUMAN STEP.**

1. Go to <https://console.cloud.google.com/> and create a project (free).
2. **APIs & Services → Library** → enable **Google Calendar API**
   (and **Google Drive API** only if you want Drive upload later).
3. **APIs & Services → OAuth consent screen** → choose **External**, fill in the
   minimal fields, and add your own account as a **test user**.
4. **APIs & Services → Credentials** → **Create credentials → OAuth client ID** →
   Application type **Desktop app** → download the JSON.
5. Save it as `data/credentials.json`.
6. Run:

   ```bash
   meetingbot auth calendar
   ```

   Sign in with the account whose calendar the bot should watch (usually **you**,
   the meeting host — not the bot account). A `data/token.json` is created.

Scopes used:
- `calendar.readonly` — default, enough to discover meetings.
- `calendar.events` — only requested when `calendar.auto_invite: true`, so the bot can
  add itself as a guest to events you organize.

## 6. Gemini API key (default LLM)

**HUMAN STEP.**

1. Visit <https://aistudio.google.com/app/apikey> and create a free API key.
2. Put it in `.env`:

   ```
   GEMINI_API_KEY=your-key-here
   ```

Verify the free-tier model name matches `llm.gemini_model` in `config.yaml`
(model names change over time — `meetingbot doctor` lists what is available).

## 7. (Optional) Ollama — fully local mode

**HUMAN STEP.**

Install [Ollama](https://ollama.com/), then:

```bash
ollama pull qwen2.5:7b-instruct
```

Set `llm.provider: ollama` in `config.yaml` for a fully local, private pipeline.

## 8. (Optional) other integrations

- **Hugging Face token** (`HF_TOKEN`) — for `pyannote.audio` diarization fallback
  (Phase 5). You must also accept the model terms on Hugging Face.
- **Gmail app password** (`SMTP_APP_PASSWORD`) — for emailing the notes.
- **Auto-invite** — set `calendar.auto_invite: true` and `bot.account_email` in
  `config.yaml`, then re-run `meetingbot auth calendar` to grant the write scope.

## 9. Running it

```bash
meetingbot doctor                 # verify config + secrets + tools
meetingbot run                    # watch your calendar and join meetings
meetingbot web                    # browse results at http://127.0.0.1:8080
meetingbot list                   # list meetings
meetingbot cleanup                # retention
meetingbot record-local           # fallback if the bot cannot join
```

With Docker, prefix commands with `docker compose exec meetingbot ...`
(e.g. `docker compose exec meetingbot meetingbot doctor`).

## 10. (Phase 7) evaluation clips

**HUMAN STEP.** Provide 3–5 short clips (2–5 min) of your real meetings with
human-corrected reference transcripts, including Lebanese dialect and code-switching.
See `scripts/eval_stt.py` (Phase 7).
