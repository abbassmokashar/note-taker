# Troubleshooting

## Configuration

**`Configuration error ... config file not found`**
Copy the example: `cp config.example.yaml config.yaml`.

**`Invalid configuration in 'config.yaml': calendar.poll_seconds: ...`**
The message names the exact field. Fix it and re-run `meetingbot doctor`.

## Joining meetings (Phase 3+)

**The bot knocks but is never admitted.**
The host must admit it ("Ask to join"). For meetings *you* organize, enable
`calendar.auto_invite: true` so the bot is added as a guest and enters directly.
Some organizations block external accounts entirely — use the local-capture
fallback (Phase 9) for those.

**The bot cannot find the Join button.**
Meet's UI changed. All selectors live in `src/meetingbot/bot/meet_selectors.py` —
update them. A screenshot and HTML dump from the failed run are saved under
`data/meetings/<id>/debug/`. See the "Selector breakage" section below.

**Google blocks the sign-in.**
Never script the login form or 2FA. Log in once by hand in headed mode
(`meetingbot login-bot`), reuse the saved profile, and avoid rapid reconnects.

## Audio

**No audio in the recording.**
Check the PulseAudio null sink exists and is the default output, and that ffmpeg is
reading `meet_sink.monitor`. `meetingbot doctor` reports whether ffmpeg is present.

**Audio drifts out of sync.**
Keep `record_video: false` unless you need it; low-bitrate H.264 muxing is the usual
cause of drift.

## Transcription

**Arabic quality is poor.**
Whisper's Lebanese-dialect accuracy is lower than for MSA or English. See
`docs/STT_EVAL.md` (Phase 7) for measured numbers and tuning (glossary,
`initial_prompt_ar`, beam size, model choice).

## Translation / notes

**Gemini returns 429 / quota errors.**
The bot retries with backoff, then falls back to Ollama if configured. For heavy use,
switch `llm.provider` to `ollama`.

**LLM returns malformed JSON.**
The pipeline validates and retries. Persistent failures usually mean the model name
is wrong — run `meetingbot doctor` to list available models.

## Arabic rendering

**Letters look disconnected or show as boxes.**
Install the Noto fonts (`fonts-noto-core`, `fonts-noto-color-emoji`) — they are in the
Docker image. For PDFs, WeasyPrint must embed Noto Naskh Arabic.

## Docker

**Container exits immediately.**
Phase 0's default command is `meetingbot --help`. Later phases run `meetingbot run`.
Check logs: `docker compose logs meetingbot`.

## Web UI

**The UI refuses to start / returns 503.**
When `delivery.web_ui.host` is not `127.0.0.1`, set `MEETINGBOT_WEB_TOKEN` in `.env`
and pass `?token=...` (or the `X-MeetingBot-Token` header).

**Arabic looks wrong in the browser.**
Check that the page's Arabic blocks render with `dir="rtl"`; install the Noto fonts on
the host if running outside Docker.

## Local capture (fallback)

**`record-local` fails to find an input device.**
- Linux: ensure PulseAudio/PipeWire is running and try `--device default` or a
  specific monitor source (`pactl list short sources`).
- macOS: install a loopback device (BlackHole) and try `--device :1`
  (`ffmpeg -f avfoundation -list_devices true -i ""` to list).
- Windows: enable "Stereo Mix" or install a virtual audio capture device and pass
  `--device "Stereo Mix"`.

Speaker attribution is skipped in this mode (no captions are available).

## Selector breakage (advanced)

1. Find the artifact: `data/meetings/<id>/debug/screenshot.png` and `page.html`.
2. Identify the new stable attribute (`aria-label`, `role`, visible English text).
3. Add it to `meet_selectors.py`. Never edit selectors elsewhere.
4. Add the new pattern to a test fixture in `tests/fixtures/` if possible.
