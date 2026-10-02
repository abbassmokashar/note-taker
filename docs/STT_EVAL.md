# STT Evaluation

Measured accuracy for English, MSA, and Lebanese dialect. **Run the harness to fill in
real numbers** — this file ships with the method, not fabricated results.

## Method

1. Collect 3–5 audio clips (2–5 minutes each) from real meetings, including:
   - English,
   - Modern Standard Arabic,
   - **Lebanese colloquial with code-switching** (Arabic/English/French mixed).
2. For each clip, write a human-corrected reference transcript as a sibling `.txt`:

   ```
   samples/
     meeting1.wav
     meeting1.txt
     meeting2.m4a
     meeting2.txt
   ```

3. Run:

   ```bash
   meetingbot eval samples/            # writes docs/STT_EVAL.md
   ```

   The harness transcribes each clip with the configured model/settings and reports
   **WER** and **CER** (punctuation, case, and Arabic diacritics are stripped).

## What to compare

Change one setting at a time in `config.yaml` and re-run:

| Setting | Values to try |
|---|---|
| `transcription.model` | `large-v3`, `large-v3-turbo`, `medium`, `small`, and any free community Arabic/dialect Whisper model converted to CTranslate2 |
| `transcription.language` | `null` (auto) vs `ar` |
| `transcription.beam_size` | `5` vs `1` |
| `transcription.vad_filter` | `true` vs `false` |
| `transcription.initial_prompt_ar` | empty vs your prompt |
| `transcription.glossary` | `[]` vs your names/terms |

Record the model id and license for any community model you use.

## Results (fill in)

| Clip | Language(s) | Words | WER | CER |
|---|---|---|---|---|
| _example_ | Lebanese + English | — | — | — |

## Honest expectation

Whisper's accuracy on **Lebanese dialect** is lower than for MSA or English. Dialect and
heavy code-switching raise WER; expect noticeably worse results than for clean English.
Use `glossary`, `glossary_correction`, and the best model that fits your hardware to
improve it. This tool is a notetaking aid, not a certified transcript.
