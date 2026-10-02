"""Transcript exporters: Markdown, SRT, VTT, JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from meetingbot.providers.base import TranscriptSegment


def format_timestamp_srt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    return format_timestamp_srt(seconds).replace(",", ".")


def format_timestamp_short(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _segment_line(seg: TranscriptSegment) -> str:
    prefix = f"[{format_timestamp_short(seg.start_s)}]"
    if seg.speaker:
        return f"{prefix} **{seg.speaker}:** {seg.text.strip()}"
    return f"{prefix} {seg.text.strip()}"


def segments_to_markdown(
    segments: list[TranscriptSegment], title: str, *, lang_label: str | None = None
) -> str:
    lines = [f"# {title}".rstrip()]
    if lang_label:
        lines.append(f"*Language: {lang_label}*")
    lines.append("")
    for seg in segments:
        if seg.text.strip():
            lines.append(_segment_line(seg))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    blocks: list[str] = []
    for index, seg in enumerate(segments, start=1):
        if not seg.text.strip():
            continue
        speaker = f"{seg.speaker}: " if seg.speaker else ""
        blocks.append(
            f"{index}\n"
            f"{format_timestamp_srt(seg.start_s)} --> {format_timestamp_srt(seg.end_s)}\n"
            f"{speaker}{seg.text.strip()}\n"
        )
    return "\n".join(blocks)


def segments_to_vtt(segments: list[TranscriptSegment]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        if not seg.text.strip():
            continue
        speaker = f"<v {seg.speaker}>" if seg.speaker else ""
        lines.append(f"{format_timestamp_vtt(seg.start_s)} --> {format_timestamp_vtt(seg.end_s)}")
        lines.append(f"{speaker}{seg.text.strip()}")
        lines.append("")
    return "\n".join(lines)


@dataclass
class TranscriptMeta:
    meeting_id: str
    title: str
    language: str | None = None
    duration_s: float | None = None
    source: str = "original"


def build_transcript_json(
    segments: list[TranscriptSegment], meta: TranscriptMeta
) -> dict:
    return {
        "meeting_id": meta.meeting_id,
        "title": meta.title,
        "language": meta.language,
        "duration_s": meta.duration_s,
        "source": meta.source,
        "segments": [asdict(seg) for seg in segments],
    }


def export_transcript(
    segments: list[TranscriptSegment],
    meta: TranscriptMeta,
    out_dir: Path,
    *,
    stem: str = "transcript",
    formats: list[str] | None = None,
) -> list[Path]:
    """Write ``stem.{md,srt,vtt,json}`` and return the created paths."""
    formats = formats or ["md", "srt", "vtt", "json"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if "md" in formats:
        path = out_dir / f"{stem}.md"
        path.write_text(
            segments_to_markdown(segments, meta.title, lang_label=meta.language),
            encoding="utf-8",
        )
        written.append(path)
    if "srt" in formats:
        path = out_dir / f"{stem}.srt"
        path.write_text(segments_to_srt(segments), encoding="utf-8")
        written.append(path)
    if "vtt" in formats:
        path = out_dir / f"{stem}.vtt"
        path.write_text(segments_to_vtt(segments), encoding="utf-8")
        written.append(path)
    if "json" in formats:
        path = out_dir / f"{stem}.json"
        path.write_text(
            json.dumps(build_transcript_json(segments, meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(path)

    return written


def segments_for_lang(segments: list[TranscriptSegment], lang: str) -> list[TranscriptSegment]:
    """Return copies whose ``text`` is the requested language (falling back to original)."""
    out: list[TranscriptSegment] = []
    for seg in segments:
        text = seg.text
        if lang == "en":
            text = seg.text_en or seg.text
        elif lang == "ar":
            text = seg.text_ar or seg.text
        out.append(
            TranscriptSegment(
                id=seg.id,
                start_s=seg.start_s,
                end_s=seg.end_s,
                text=text,
                language=lang,
                speaker=seg.speaker,
                avg_logprob=seg.avg_logprob,
                text_en=seg.text_en,
                text_ar=seg.text_ar,
            )
        )
    return out


def export_bilingual(
    segments: list[TranscriptSegment], meta: TranscriptMeta, out_dir: Path
) -> Path:
    """Write a side-by-side Arabic/English transcript table."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "bilingual.md"
    lines = [
        f"# {meta.title}",
        "",
        "| Time | Speaker | English | Arabic |",
        "| --- | --- | --- | --- |",
    ]
    for seg in segments:
        stamp = format_timestamp_short(seg.start_s)
        speaker = seg.speaker or ""
        en = (seg.text_en or seg.text or "").replace("|", "\\|").replace("\n", " ")
        ar = (seg.text_ar or seg.text or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {stamp} | {speaker} | {en} | {ar} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_meta(out_dir: Path, data: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "meta.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def markdown_to_html(markdown_text: str, *, title: str, lang: str) -> str:
    """Very small Markdown -> HTML for PDF export (headings, bullets, tables)."""
    import html
    import re

    lines = markdown_text.splitlines()
    out: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            text = stripped[level:].strip()
            out.append(f"<h{level}>{html.escape(text)}</h{level}>")
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            row = "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        else:
            if in_table:
                out.append("</table>")
                in_table = False
        if re.match(r"^[-*+]\s+", stripped):
            out.append(f"<li>{html.escape(stripped[2:].strip())}</li>")
        elif stripped:
            out.append(f"<p>{html.escape(stripped)}</p>")
    if in_table:
        out.append("</table>")
    body = "\n".join(out)
    direction = "rtl" if lang == "ar" else "ltr"
    return (
        f"<!doctype html><html lang='{lang}' dir='{direction}'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:'Noto Naskh Arabic','Noto Sans',sans-serif;}"
        f"</style></head><body>{body}</body></html>"
    )


def export_pdf(
    markdown_text: str, out_dir: Path, *, stem: str, title: str, lang: str
) -> Path:
    """Render Markdown to PDF via WeasyPrint, embedding Arabic-capable fonts."""
    from weasyprint import HTML  # lazy: heavy optional dependency

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.pdf"
    html_doc = markdown_to_html(markdown_text, title=title, lang=lang)
    HTML(string=html_doc).write_pdf(str(path))
    return path
