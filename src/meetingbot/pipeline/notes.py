"""Notes stage: bilingual meeting notes via map-reduce over the transcript."""

from __future__ import annotations

import logging
import re

from meetingbot.pipeline.export import format_timestamp_short
from meetingbot.prompts import render
from meetingbot.providers.base import LLM, TranscriptSegment

logger = logging.getLogger(__name__)

LANG_NAMES = {"en": "English", "ar": "Arabic (Lebanon)"}

ARABIC_STYLE_INSTRUCTIONS = {
    "msa_simple": (
        "اكتب بالعربية الفصحى المبسطة والواضحة، بمفردات مألوفة لدى اللبنانيين، "
        "لتكون الملاحظات قابلة للمشاركة."
    ),
    "lebanese_colloquial": (
        "اكتب باللهجة اللبنانية المحكية بالحرف العربي، بلغة مهنية لكن طبيعية، "
        "مع إبقاء المصطلحات التقنية بالإنجليزية حيث يفعل ذلك المهنيون اللبنانيون."
    ),
}

_SECTION_KEYS = {
    "tl;dr": "summary",
    "summary": "summary",
    "الخلاصة السريعة": "summary",
    "key discussion points": "key_points",
    "أبرز نقاط النقاش": "key_points",
    "decisions": "decisions",
    "القرارات": "decisions",
    "action items": "action_items",
    "بنود العمل": "action_items",
    "open questions": "open_questions",
    "أسئلة مفتوحة": "open_questions",
}

_HEADER_RE = re.compile(r"^#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")


def segment_text_for_lang(seg: TranscriptSegment, lang: str) -> str:
    if lang == "en":
        return seg.text_en or seg.text
    if lang == "ar":
        return seg.text_ar or seg.text
    return seg.text


def transcript_to_text(segments: list[TranscriptSegment], lang: str | None = None) -> str:
    """Render the transcript as ``[mm:ss] Speaker: text`` lines."""
    lines: list[str] = []
    for seg in segments:
        text = segment_text_for_lang(seg, lang) if lang else seg.text
        if not text.strip():
            continue
        stamp = format_timestamp_short(seg.start_s)
        speaker = f"{seg.speaker}: " if seg.speaker else ""
        lines.append(f"[{stamp}] {speaker}{text.strip()}")
    return "\n".join(lines)


def chunk_transcript(text: str, chunk_chars: int) -> list[str]:
    """Split into chunks on line boundaries, each under ``chunk_chars``."""
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > chunk_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _system_prompt(lang: str, arabic_style: str) -> str:
    if lang == "ar":
        style = ARABIC_STYLE_INSTRUCTIONS.get(
            arabic_style, ARABIC_STYLE_INSTRUCTIONS["msa_simple"]
        )
        return render("notes_ar", ARABIC_STYLE=style)
    return render("notes_en")


def generate_notes(
    llm: LLM,
    segments: list[TranscriptSegment],
    title: str,
    *,
    lang: str,
    arabic_style: str = "msa_simple",
    chunk_chars: int = 6000,
) -> str:
    """Generate Markdown notes for one language. Uses map-reduce for long meetings."""
    transcript = transcript_to_text(segments, lang)
    if not transcript.strip():
        return f"# {title}\n\n## TL;DR\nnot stated\n"

    chunks = chunk_transcript(transcript, chunk_chars)
    user_body = f"Meeting title: {title}\n\nTranscript:\n{transcript}"

    if len(chunks) == 1:
        return llm.complete(
            system=_system_prompt(lang, arabic_style), user=user_body, json_mode=False
        )

    logger.info("Generating notes with map-reduce over %d chunks", len(chunks))
    partials: list[str] = []
    map_system = render("notes_map", LANG=LANG_NAMES[lang])
    for index, chunk in enumerate(chunks, start=1):
        partials.append(
            llm.complete(
                system=map_system,
                user=f"Meeting title: {title}\nChunk {index}/{len(chunks)}:\n{chunk}",
                json_mode=False,
            )
        )

    merge_system = render("notes_merge", LANG=LANG_NAMES[lang])
    merged = "\n\n---\n\n".join(partials)
    return llm.complete(
        system=merge_system,
        user=f"Meeting title: {title}\n\nPartial notes:\n{merged}",
        json_mode=False,
    )


def parse_notes_markdown(markdown: str) -> dict:
    """Extract the standard sections from generated notes Markdown."""
    sections: dict[str, list[str]] = {
        "summary": [],
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
    }
    current: str | None = None
    for raw_line in markdown.splitlines():
        header = _HEADER_RE.match(raw_line)
        if header:
            title = header.group(1).strip().lower().rstrip(":")
            current = _SECTION_KEYS.get(title)
            continue
        if current is None or not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("|"):
            # Markdown table row (action items).
            if set(raw_line.replace(" ", "")) <= set("|-:"):
                continue
            sections[current].append(raw_line.strip())
            continue
        bullet = _BULLET_RE.match(raw_line)
        sections[current].append((bullet.group(1) if bullet else raw_line).strip())

    return {
        "summary": "\n".join(sections["summary"]).strip(),
        "key_points": sections["key_points"],
        "decisions": sections["decisions"],
        "action_items": sections["action_items"],
        "open_questions": sections["open_questions"],
    }
