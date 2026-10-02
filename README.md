# MeetingBot

A **free, self-hosted** bot that joins your Google Meet meetings, records them, and
produces for every meeting:

1. The **recording** (audio always; video optional).
2. A **full transcript** in the spoken language(s) with timestamps and speaker labels.
3. Transcripts and notes in **both English and Arabic (Lebanese, `ar-LB`)**.
4. **Meeting notes** in both languages — summary, key points, decisions, action items
   (owner + due when stated), and open questions.

Cost: **$0**. No paid APIs, no paid hosting, no credit card.

---

## How it works

```
 Google Calendar ─▶ Scheduler ─▶ Join Bot (Playwright + Xvfb + PulseAudio + ffmpeg)
   (read-only)       (60s poll)         │
                                        ▼  recording.opus + events.jsonl
                            Processing Pipeline (resumable)
                            normalize ▶ faster-whisper STT ▶ speaker alignment
                                      ▶ translate EN/AR ▶ notes EN/AR ▶ export
                                        │
                                        ▼
                            SQLite + files on disk + local web UI
```

Every external dependency (STT, LLM, notifications) sits behind an interface so it
can be swapped. See `docs/` for setup, progress, and troubleshooting.

## Status

This project is built phase by phase. See `docs/PROGRESS.md` for the live status.

| Phase | Description | Status |
|---|---|---|
| 0 | Project skeleton | ✅ done |
| 1 | Offline pipeline on local audio | ✅ done |
| 2 | Translation + notes | ✅ done |
| 3 | Google Meet join bot | ✅ code — live test pending (human) |
| 4 | Calendar scheduler + auto-invite | ✅ code — live test pending (human) |
| 5 | Speaker attribution | ✅ done |
| 6 | Web UI, exports, delivery | ✅ done |
| 7 | Lebanese Arabic STT evaluation | ✅ done (needs your clips) |
| 8 | Hardening, ops, docs | ✅ done |
| 9 | Local capture fallback (optional) | ✅ done |

**153 tests pass; `ruff` clean.** See `docs/PROGRESS.md` for the honest status of each
phase (including what could not be verified in a headless dev environment).

### Commands

```
meetingbot init            # create data dirs + database
meetingbot doctor          # show config / env health
meetingbot process <audio> # offline pipeline on a local file
meetingbot join <url>      # join a Meet URL and record
meetingbot login-bot       # one-time sign-in for the bot account (HUMAN STEP)
meetingbot auth calendar   # Google Calendar OAuth (HUMAN STEP)
meetingbot run             # watch your calendar and join meetings automatically
meetingbot web             # local web UI
meetingbot list            # list meetings
meetingbot reprocess <id> --from-stage translate
meetingbot eval <folder>   # WER/CER report -> docs/STT_EVAL.md
meetingbot record-local    # fallback: record this computer's audio
meetingbot cleanup         # retention: delete old recordings
```

## Quickstart (development)

```bash
# Create an environment (Python 3.11+). uv is recommended:
uv venv --python 3.11
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # Linux/macOS

uv pip install -e ".[dev]"
cp config.example.yaml config.yaml
cp .env.example .env               # then edit .env

meetingbot --help
meetingbot doctor
meetingbot init
pytest
```

## Quickstart (Docker)

```bash
cp config.example.yaml config.yaml
cp .env.example .env               # then edit .env
docker compose up --build
docker compose exec meetingbot meetingbot doctor
```

## Configuration & secrets

- `config.yaml` — non-secret settings (see `config.example.yaml`).
- `.env` — secrets only: `GEMINI_API_KEY`, and optionally `HF_TOKEN`,
  `SMTP_APP_PASSWORD`, `GROQ_API_KEY`, `MEETINGBOT_WEB_TOKEN`.
  **Never commit `.env`.**

## Privacy and consent

- All data stays **local** except text sent to the LLM provider. Set
  `llm.provider: ollama` for a fully local/private mode.
- The bot **announces itself** in the meeting (display name + chat message). This is
  mandatory, not optional. Do not disable it and record people without their knowledge.
- You are responsible for complying with your workplace policies, local law, and
  Google's terms. Automated participants in Meet may be restricted by an
  organization's settings.
