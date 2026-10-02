# Progress

Track what works, what does not, and what the human must do next.

---

## Phase 0 — Project skeleton ✅

**Date completed:** 2026-10-02

### What works
- Repo structure, `pyproject.toml` with dependency groups
  (`stt`, `llm`, `calendar`, `bot`, `web`, `pdf`, `dev`, `all`).
- Typed, validated configuration (`src/meetingbot/config.py`) loaded from
  `config.yaml` + `.env`, with readable error messages.
- Structured logging (console + rotating file).
- SQLite data model: `meetings`, `stages`, `segments`, `notes`
  (`src/meetingbot/db.py`).
- CLI (`meetingbot`): `--help`, `--version`, `init`, `doctor`, `list` work.
  `run`, `join`, `process`, `reprocess`, `web`, `auth`, `eval` are wired stubs
  that exit with a clear "arriving in Phase N" message.
- `Dockerfile` (Ubuntu 24.04 + Python, ffmpeg, Xvfb, PulseAudio, Noto fonts, tini)
  and `docker-compose.yml`.
- Tests for config, DB, and CLI.
- Docs: `README.md`, `docs/SETUP.md`, `docs/TROUBLESHOOTING.md`.

### What does not work yet
- No audio processing, transcription, translation, or join logic (Phases 1–9).
- Container default command is `meetingbot --help`; it will become `meetingbot run`
  in Phase 4.

### External calls made
- **None.** Phase 0 makes no network calls.

### What the human must do next
- Nothing blocking. Optional: install Docker, create `config.yaml`/`.env`, run
  `meetingbot doctor`.

### Verification
- `pytest` passes.
- `meetingbot --help` works.

---

## Phase 1 — Offline pipeline on a local audio file ✅

**Date completed:** 2026-10-02

### What works
- `meetingbot process <audio> --title "..."` runs: audio normalization (ffmpeg ->
  16 kHz mono PCM, loudness-normalized) -> transcription -> export.
- `src/meetingbot/providers/base.py`: `Transcriber`/`LLM`/`Notifier` protocols and
  `TranscriptSegment` / `TranscriptionResult` dataclasses.
- `src/meetingbot/pipeline/audio_prep.py`: ffmpeg normalization, duration probing;
  a file already in 16 kHz mono WAV passes through untouched (no ffmpeg needed).
- `src/meetingbot/pipeline/transcribe.py`: chunked transcription (default 10-min
  chunks) with per-chunk JSON checkpoints under `work/parts/`, so a crash resumes
  instead of restarting.
- `src/meetingbot/hardware.py`: tier detection (A/B/C/D) and `auto` model/device/
  compute-type resolution, overridable with `MEETINGBOT_TIER`.
- `src/meetingbot/providers/whisper_local.py`: lazy faster-whisper provider (optional
  `multilingual=True` for code-switching on supporting versions).
- `src/meetingbot/pipeline/export.py`: Markdown, SRT, VTT, JSON exporters.
- `src/meetingbot/pipeline/runner.py`: resumable stage runner (`meetingbot reprocess
  <id> --from-stage <stage>`); meeting folders under `data/meetings/<id>/`.

### What does not work yet
- Translation and notes (Phase 2).
- Speaker attribution (Phase 5) — `speaker` is always null for now.
- `align_speakers` stage is defined but not executed yet.

### External calls made
- **None.** Transcription runs locally; no network calls.

### What the human must do next
- Install the STT extra if you want to run transcription for real:
  `pip install "meetingbot[stt]"`, then install `ffmpeg` for non-WAV inputs.
- Provide real audio (English, Arabic, mixed) to confirm quality.

### Verification note
- The pipeline was verified end-to-end with a **fake transcriber** and a
  stdlib-generated 16 kHz WAV. Real `faster-whisper` inference and `ffmpeg`
  normalization could not be exercised in this environment (neither is installed);
  the code paths are covered by unit tests with substitutes.
- 42 tests pass; `ruff` clean.

---

## Phase 2 — Translation and notes ✅

**Date completed:** 2026-10-02

### What works
- LLM providers: `GeminiLLM` (`google-genai`, free tier) and `OllamaLLM` (local),
  behind the `LLM` protocol, selected by `providers/factory.py` with automatic
  fallback when the primary is unusable.
- `providers/llm_common.py`: `ResilientLLM` with retry/backoff on rate limit /
  unavailable, plus JSON extraction/parsing (`parse_json_list`).
- `pipeline/translate.py`: batched translation to `text_en` and `text_ar`, strict
  `[{"id","text"}]` JSON validation, 3 validation attempts, and a guarantee that
  **no segment is ever lost** (falls back to the original text on failure).
- `pipeline/notes.py`: native EN and AR notes via map-reduce over the transcript,
  with a hallucination guard ("use only information in the transcript") and
  Arabic style policy (`msa_simple` / `lebanese_colloquial`). Parses the standard
  sections for storage.
- Prompts versioned in `src/meetingbot/prompts/*.md`.
- Pipeline stages extended: `translate` and `summarize`; exports now write
  `transcript.en.*`, `transcript.ar.*`, `bilingual.md`, `notes.en.md`, `notes.ar.md`,
  and `meta.json`, and populate the `segments`/`notes` tables.

### What does not work yet
- Speaker attribution (Phase 5).
- PDF export (Phase 6).
- Real Gemini/Ollama calls were not exercised (no API key / no local server here).

### External calls made
- **None** during tests. In production: text is sent to the configured LLM
  (Gemini by default, or Ollama for a fully local mode).

### What the human must do next
- Put a free `GEMINI_API_KEY` in `.env` (or install Ollama and set
  `llm.provider: ollama`) to try translation/notes for real.

### Verification note
- Verified with a deterministic `MockLLM` (no network). 53 tests pass; `ruff` clean.

---

## Phase 3 — Google Meet join bot ✅ (code); live test pending human

**Date completed:** 2026-10-02 (code)

### What works
- `src/meetingbot/bot/meet_selectors.py`: **all** DOM selectors in one file, each with
  ordered English + Arabic fallbacks, plus `resolve`/`resolve_all` helpers.
- `src/meetingbot/bot/meet_session.py`: the state machine
  `INIT -> NAVIGATING -> PRE_JOIN -> WAITING_ADMIT -> IN_MEETING -> LEAVING -> ENDED|FAILED`.
  Dismisses popups, sets the display name, mutes mic/camera, clicks Join/Ask-to-join,
  waits with a timeout, detects denied/ended, posts the EN+AR chat announcement,
  watches for end conditions (ended screen, removed, alone, max hours, SIGTERM).
- `src/meetingbot/bot/browser.py`: Playwright persistent-context launcher (headed on
  Xvfb, forced locale, mic/camera auto-grant).
- `src/meetingbot/bot/audio_capture.py`: PulseAudio null sink + segmented ffmpeg
  capture (`meet_sink.monitor` -> Opus), concatenated on exit.
- `src/meetingbot/bot/caption_logger.py`: MutationObserver caption scraping ->
  `events.jsonl` (speaker + timing only).
- `src/meetingbot/bot/health.py`: failure screenshots/HTML, heartbeat, disk guard.
- `src/meetingbot/bot/joiner.py`: end-to-end record orchestration and DB status.
- `src/meetingbot/bot/login.py` + `scripts/login_bot_account.py`: one-time headed login.
- CLI: `meetingbot join <url>` and `meetingbot login-bot`.
- `Dockerfile` + `scripts/docker-entrypoint.sh`: Xvfb + PulseAudio null sink + Chromium.

### What does not work yet / not verified
- **No live Google Meet test has been run** (needs the human's account + a meeting).
- Selectors are best-effort and will need updating when Meet's UI changes.

### External calls made
- **None** in tests. Live joins would contact Google Meet.

### What the human must do next
1. Create the dedicated bot Google account and run `meetingbot login-bot`.
2. Host a test meeting and run `meetingbot join <url>`, then verify the recording,
   the chat announcement, and auto-leave (also test the denied/timeout paths).

---

## Phase 4 — Calendar scheduler + auto-invite ✅ (code); live test pending human

### What works
- `scheduler/calendar_auth.py`: OAuth with `calendar.readonly`, plus `calendar.events`
  **only** when `calendar.auto_invite` is on. `meetingbot auth calendar` runs the flow.
- `scheduler/rules.py`: pure join rules (cancelled, no Meet link, `#nobot`, all-day,
  declined, title filters, default skip) and Meet-link extraction from the description.
- `scheduler/calendar_watcher.py`: `CalendarClient` protocol, real
  `GoogleCalendarClient`, event normalization (dateTime/date/conferenceData), and
  `invite_bot` (adds the bot only to events **you** organize).
- `scheduler/scheduler.py`: `sync_jobs` (create/update/cancel jobs by event id,
  restart-safe because it dedupes on `calendar_event_id`), `due_meetings`, and
  `run_forever` with a `max_concurrent_bots` thread pool. CLI `run` starts it.

### What does not work yet / not verified
- No live Calendar test (needs the human's OAuth token).

### What the human must do next
1. Google Cloud: enable Calendar API, create a Desktop OAuth client, save as
   `data/credentials.json`, run `meetingbot auth calendar`.
2. Create three test events (now / +5 min / declined) and run `meetingbot run`.

---

## Phase 5 — Speaker attribution ✅

### What works
- `pipeline/speakers.py`: aligns Whisper segments to the caption timeline by maximum
  time overlap (captions give speaker + timing, never the transcript), merges
  consecutive same-speaker segments (gap < 2 s), and never crashes when
  `events.jsonl` or `recording_meta.json` is missing (speaker stays null).
- New `align_speakers` pipeline stage wired between `transcribe` and `translate`.
- The joiner writes `recording_meta.json` (`start_wall`) so caption wall-clock times
  map to audio offsets.

### What does not work yet
- Optional pyannote diarization fallback is not implemented (needs a Hugging Face
  token — HUMAN STEP). Caption-based attribution is the primary method.

### Verification
- Verified with unit tests. 110 tests pass; `ruff` clean.

---

## Phase 6 — Web UI, exports, delivery ✅

### What works
- `web/app.py`: FastAPI UI — meeting list, detail page with an audio player synced to
  the transcript (click a line to seek), **Bilingual / English / Arabic** view toggle,
  bilingual notes tabs, speaker rename, file downloads, and a reprocess button.
  Path traversal is blocked; a token is required if the UI is exposed beyond localhost.
  `/health` endpoint.
- RTL correctness: Arabic blocks use `dir="rtl" lang="ar"`; mixed lines use
  `unicode-bidi: plaintext`; Noto Naskh Arabic is used for PDFs.
- Exports per meeting: `transcript.original|en|ar.{md,srt,vtt,json}`, `bilingual.md`,
  `notes.{en,ar}.md`, `notes.{en,ar}.pdf` (WeasyPrint, optional), `meta.json`.
- `providers/notifiers.py`: `LocalFilesNotifier`, `EmailNotifier` (Gmail app password),
  `DriveUploader` (placeholder, logs a warning — not implemented).
- `pipeline/admin.py`: `rename_speaker` (updates DB + cached JSON + re-exports) and
  `deliver_meeting` (emails notes + attachments when enabled).
- CLI `web` command.

### What does not work yet
- Google Drive upload is a logged placeholder.
- PDF export requires the optional `pdf` extra (WeasyPrint).

### External calls made
- **None** during tests. Email/Drive only run when enabled in `config.yaml`.

---

## Phase 7 — Lebanese Arabic STT evaluation ✅ (needs your clips)

### What works
- `eval/metrics.py`: WER and CER with normalization (case, punctuation, Arabic
  diacritics stripped).
- `eval/runner.py`: loads `<name>.wav` + `<name>.txt` cases, transcribes, and writes a
  Markdown report with per-clip and mean WER/CER.
- `meetingbot eval <folder>` and `scripts/eval_stt.py`.
- `pipeline/glossary.py`: glossary terms biasing via `initial_prompt`, plus an optional
  LLM "fix obvious ASR errors" pass (`transcription.glossary_correction`).
- `docs/STT_EVAL.md` explains the method; real numbers need your reference clips.

### What the human must do next
- Provide 3–5 clips with corrected reference transcripts and run `meetingbot eval`.

---

## Phase 8 — Hardening, ops, docs ✅

### What works
- Health endpoint (`/health`), disk guard (refuses to record under 5 GB), heartbeat
  helper, graceful shutdown (SIGTERM/SIGINT -> leave meeting and finalize files).
- `maintenance.cleanup_old_audio` + `meetingbot cleanup` for retention.
- Docker `restart: unless-stopped`; entrypoint brings up Xvfb + PulseAudio.
- Docs: `README.md`, `docs/SETUP.md`, `docs/TROUBLESHOOTING.md`, `docs/MANUAL_TESTS.md`.
- Privacy: `llm.provider: ollama` is a fully local mode; nothing sensitive is logged at
  INFO.

---

## Phase 9 — Local capture fallback (optional) ✅

### What works
- `bot/local_capture.py`: OS-specific ffmpeg system-audio capture (PulseAudio on Linux,
  AVFoundation/BlackHole on macOS, DirectShow on Windows).
- `meetingbot record-local` records and (by default) feeds the same pipeline.

---

## External calls audit (Definition of Done)

The entire system runs with **zero paid services**. Every external call:

| Call | Cost | When |
|---|---|---|
| Google Meet (browser) | free | joining a meeting |
| Google Calendar API | free | read-only polling; write only if `auto_invite` |
| Gemini API (free tier) | free | translation + notes **unless** `llm.provider: ollama` |
| Ollama (local) | free | optional, fully offline |
| Gmail SMTP | free | email delivery, only if enabled |
| Google Drive | free | **not implemented** |
| Hugging Face (pyannote) | free | **not implemented** (optional diarization) |

All speech recognition (`faster-whisper`) runs locally. Tests make **no** network calls.

## Final test status

- **153 tests pass**, `ruff` clean.
- Phases 3 and 4 are code-complete and unit-tested but have **not been run against live
  Google Meet / Calendar** — that requires the human's accounts and a test meeting. See
  `docs/MANUAL_TESTS.md`.
