# Manual tests

Some things cannot be tested in CI (they need Google's servers, your account, and a
real meeting). Run this checklist once per phase upgrade.

## Preparation

```bash
cp config.example.yaml config.yaml
# edit config.yaml: bot.account_email, calendar.timezone, display_name
meetingbot doctor
meetingbot login-bot          # sign in the bot's Google account once
```

## Phase 3 — join + record

1. Start a Meet meeting from your personal account and copy the link.
2. `meetingbot join <url> --title "Test"`.
3. ✅ The bot is admitted (or you admit it) and posts the EN + AR chat announcement.
4. Speak English for 1 minute, then Arabic (Lebanese) for 1 minute.
5. End the meeting.
6. ✅ `data/meetings/<id>/recording.opus` exists and contains both languages.
7. ✅ The bot left automatically.

Also test the failure paths:
- Host clicks "Deny": ✅ status `failed`, screenshot under `debug/`.
- Never admit the bot: ✅ `failed` after `waiting_room_timeout_minutes`.

## Phase 4 — calendar

1. `meetingbot auth calendar` (grant read scope; if `auto_invite` is on, the write
   scope is requested too).
2. Create three events starting soon, one of them **declined**, all with Meet links.
3. `meetingbot run`.
4. ✅ The bot joins the first two at the right time and skips the declined one.
5. Reschedule an event: ✅ the job moves.
6. Delete an event: ✅ the job is cancelled (`skipped`).
7. Restart the container: ✅ no duplicate jobs.

Auto-invite (optional): set `calendar.auto_invite: true` +
`bot.account_email`, re-run `meetingbot auth calendar`, and confirm the bot appears
as a guest on events you organize.

## Phase 5 — speakers

1. In a 3-person meeting, speak in turn for a minute each.
2. ✅ ≥ 80% of segments are attributed to the right person in the web UI.
3. Rename a speaker in the UI: ✅ transcripts re-export with the new name.

## Phase 7 — accuracy

1. Collect 3–5 clips (2–5 min) with human-corrected reference `.txt` files,
   including Lebanese dialect and code-switching.
2. `meetingbot eval samples/`
3. ✅ `docs/STT_EVAL.md` shows measured WER/CER and a justified default.

## Soak test (Phase 8)

Leave `meetingbot run` going for 3 days with real calendar events. ✅ No crashes, no
disk blowup, memory stable.
