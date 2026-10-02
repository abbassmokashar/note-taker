"""MeetingBot command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from meetingbot import __version__
from meetingbot.config import ConfigError, Secrets, Settings, load_settings
from meetingbot.db import (
    Meeting,
    create_db_engine,
    init_db,
    make_session_factory,
)
from meetingbot.logging_setup import setup_logging

app = typer.Typer(
    name="meetingbot",
    help="Free self-hosted Google Meet recorder + bilingual (EN/AR-LB) note taker.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _load(config: Path | None, *, require: bool = False) -> Settings:
    try:
        settings = load_settings(config, require_file=require)
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error[/bold red]\n{escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    setup_logging(settings.log_level, settings.data_dir / "meetingbot.log")
    return settings


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"meetingbot {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """MeetingBot: record, transcribe, translate and summarize Google Meet meetings."""


@app.command()
def init(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Create the data directories and initialize the database."""
    settings = _load(config)
    settings.ensure_dirs()
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    console.print(f"[green]Initialized[/green] data dir: {settings.data_dir}")
    console.print(f"Database: {settings.db_path}")


@app.command()
def doctor(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Show configuration and environment health."""
    settings = _load(config)
    secrets = Secrets.from_env()

    table = Table(title="MeetingBot doctor")
    table.add_column("Item")
    table.add_column("Value")

    table.add_row("version", __version__)
    table.add_row("data dir", str(settings.data_dir))
    table.add_row("db path", str(settings.db_path))
    table.add_row("bot display name", settings.bot.display_name)
    table.add_row("bot account", settings.bot.account_email or "[yellow](not set)[/yellow]")
    table.add_row("calendar auto_invite", str(settings.calendar.auto_invite))
    table.add_row("calendar timezone", settings.calendar.timezone)
    table.add_row("transcription provider", settings.transcription.provider)
    table.add_row("transcription model", settings.transcription.model)
    table.add_row("llm provider", settings.llm.provider)
    table.add_row("llm fallback", str(settings.llm.fallback_provider))
    table.add_row(
        "GEMINI_API_KEY",
        "[green]set[/green]" if secrets.gemini_api_key else "[yellow]missing[/yellow]",
    )
    table.add_row(
        "HF_TOKEN", "[green]set[/green]" if secrets.hf_token else "[dim]optional[/dim]"
    )
    table.add_row(
        "SMTP_APP_PASSWORD",
        "[green]set[/green]" if secrets.smtp_app_password else "[dim]optional[/dim]",
    )
    table.add_row("ffmpeg", _which("ffmpeg"))
    table.add_row("docker", _which("docker"))
    console.print(table)

    if settings.calendar.auto_invite and not settings.bot.account_email:
        console.print(
            "[yellow]Warning:[/yellow] calendar.auto_invite is on but bot.account_email "
            "is empty — auto-invite will not work."
        )


@app.command()
def list(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
    status: str | None = typer.Option(None, "--status", help="Filter by status."),
    limit: int = typer.Option(50, "--limit", help="Max rows."),
) -> None:
    """List recorded meetings."""
    settings = _load(config)
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        query = session.query(Meeting).order_by(Meeting.created_at.desc())
        if status:
            query = query.filter(Meeting.status == status)
        rows = query.limit(limit).all()

        table = Table(title="Meetings")
        table.add_column("id", style="cyan")
        table.add_column("title")
        table.add_column("status")
        table.add_column("start")
        for row in rows:
            table.add_row(
                row.id,
                row.title or "-",
                row.status,
                row.scheduled_start.strftime("%Y-%m-%d %H:%M") if row.scheduled_start else "-",
            )
        if not rows:
            console.print("[dim]No meetings yet.[/dim]")
        else:
            console.print(table)


@app.command()
def run(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Run the scheduler + worker loop (joins meetings automatically)."""
    from meetingbot.scheduler.calendar_auth import build_service
    from meetingbot.scheduler.calendar_watcher import CalendarWatcher, GoogleCalendarClient
    from meetingbot.scheduler.scheduler import Scheduler

    settings = _load(config, require=True)
    settings.ensure_dirs()
    try:
        service = build_service(settings)
    except Exception as exc:  # noqa: BLE001 - surface auth problems clearly
        console.print(f"[bold red]Calendar auth failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    watcher = CalendarWatcher(GoogleCalendarClient(service), settings)
    scheduler = Scheduler(settings, watcher)
    console.print(
        f"Watching your calendar every {settings.calendar.poll_seconds}s. "
        "Press Ctrl+C to stop."
    )
    try:
        scheduler.run_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        scheduler.stop()
        console.print("\n[dim]Stopped.[/dim]")


@app.command()
def join(
    meet_url: str = typer.Argument(..., help="Google Meet URL to join."),
    title: str = typer.Option("Manual test", "--title", help="Title for the meeting record."),
    process: bool = typer.Option(
        False, "--process", help="Run transcription/translation after recording."
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Join a Meet URL manually and record it."""
    from meetingbot.bot.joiner import join_meeting

    settings = _load(config)
    console.print(f"Joining [cyan]{meet_url}[/cyan] as {settings.bot.display_name}...")
    try:
        meeting = join_meeting(settings, meet_url, title, process_after=process)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        console.print(f"[bold red]Join failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Done[/green] {meeting.id} status={meeting.status}")


@app.command("login-bot")
def login_bot(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Open a browser once to sign the bot's Google account in (HUMAN STEP)."""
    from meetingbot.bot.login import login_bot_account

    settings = _load(config)
    console.print(
        "A browser window will open. Sign in as the bot account (including 2FA), "
        "then press Enter here to save the session."
    )
    login_bot_account(settings)
    console.print(f"[green]Session saved[/green] to {settings.browser_profile_dir}")


@app.command()
def process(
    audio_path: Path = typer.Argument(..., exists=True, help="Audio/video file to process."),
    title: str = typer.Option("Test", "--title", help="Meeting title."),
    force: bool = typer.Option(False, "--force", help="Ignore cached chunks and re-run."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Process a local audio file through the offline pipeline."""
    from meetingbot.pipeline.runner import process_file

    settings = _load(config)
    console.print(f"Processing [cyan]{audio_path}[/cyan] ({title})...")
    try:
        meeting = process_file(settings, audio_path, title, force=force)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        console.print(f"[bold red]Processing failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    folder = Path(meeting.folder) if meeting.folder else settings.meetings_dir / meeting.id
    console.print(f"[green]Done[/green] meeting id: [cyan]{meeting.id}[/cyan]")
    console.print(f"Output: {folder}")


@app.command()
def reprocess(
    meeting_id: str = typer.Argument(..., help="Meeting id."),
    from_stage: str = typer.Option(
        "normalize", "--from-stage", help="Stage to resume from."
    ),
    force: bool = typer.Option(False, "--force", help="Ignore cached chunks and re-run."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Re-run the pipeline for a meeting from a given stage."""
    from meetingbot.pipeline.runner import PipelineRunner

    settings = _load(config)
    try:
        meeting = PipelineRunner(settings).run(
            meeting_id, from_stage=from_stage, force=force
        )
    except KeyError as exc:
        console.print(f"[bold red]{escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Reprocess failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Done[/green] {meeting.id} status={meeting.status}")


@app.command()
def web(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Start the local web UI."""
    settings = _load(config)
    settings.ensure_dirs()
    host = settings.delivery.web_ui.host
    port = settings.delivery.web_ui.port
    console.print(f"Starting web UI at [cyan]http://{host}:{port}[/cyan]")
    try:
        from meetingbot.web.app import run_server
    except ImportError as exc:  # pragma: no cover - optional extra
        console.print(
            f"[bold red]Web UI dependencies missing:[/bold red] {escape(str(exc))}\n"
            "Install them with: pip install 'meetingbot[web]'"
        )
        raise typer.Exit(code=1) from exc
    run_server(settings)


@app.command()
def auth(
    target: str = typer.Argument(..., help="What to authenticate: 'calendar' or 'drive'."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Run an OAuth flow (calendar or drive)."""
    from meetingbot.scheduler.calendar_auth import run_oauth_flow, scopes_for

    settings = _load(config)
    settings.ensure_dirs()
    if target == "calendar":
        console.print(f"Requesting scopes: {', '.join(scopes_for(settings))}")
        try:
            token = run_oauth_flow(settings)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[bold red]Auth failed:[/bold red] {escape(str(exc))}")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]Saved[/green] credentials to {token}")
        return
    if target == "drive":
        console.print("[yellow]Drive auth arrives in Phase 6.[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"[bold red]Unknown auth target:[/bold red] {escape(target)}")
    raise typer.Exit(code=1)


@app.command()
def eval(
    folder: Path = typer.Argument(..., exists=True, help="Folder of audio + .txt references."),
    output: Path = typer.Option(Path("docs/STT_EVAL.md"), "--out", help="Report path."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Evaluate STT accuracy against reference transcripts (WER/CER)."""
    from meetingbot.eval.runner import evaluate, load_cases, render_report, write_report
    from meetingbot.pipeline.glossary import build_initial_prompt
    from meetingbot.pipeline.runner import make_transcriber

    settings = _load(config)
    cases = load_cases(folder)
    if not cases:
        console.print(
            "[bold red]No cases found.[/bold red] Add audio files with matching "
            "<name>.txt reference transcripts."
        )
        raise typer.Exit(code=1)

    cfg = settings.transcription
    prompt = build_initial_prompt(
        cfg.initial_prompt_ar if cfg.language in ("ar", None) else None, cfg.glossary
    )
    console.print(f"Evaluating {len(cases)} clip(s)...")
    results = evaluate(make_transcriber(settings), cases, language=cfg.language, initial_prompt=prompt)

    table = Table(title="STT evaluation")
    table.add_column("clip")
    table.add_column("words", justify="right")
    table.add_column("WER", justify="right")
    table.add_column("CER", justify="right")
    for result in results:
        table.add_row(result.name, str(result.words), f"{result.wer:.1%}", f"{result.cer:.1%}")
    console.print(table)

    note = (
        f"Model: `{cfg.model}` | device: `{cfg.device}` | compute: `{cfg.compute_type}` "
        f"| language: `{cfg.language}` | beam: {cfg.beam_size}"
    )
    write_report(output, render_report(results, settings_note=note))
    console.print(f"[green]Report written[/green] to {output}")


@app.command("record-local")
def record_local_cmd(
    output: Path = typer.Option(Path("local_recording.wav"), "--out", help="Output WAV path."),
    seconds: int = typer.Option(0, "--seconds", help="Stop after N seconds (0 = until Ctrl+C)."),
    device: str | None = typer.Option(None, "--device", help="Audio input device name."),
    title: str = typer.Option("Local recording", "--title", help="Meeting title."),
    process: bool = typer.Option(True, "--process/--no-process", help="Run the pipeline after."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Record this computer's audio (fallback when the bot cannot join)."""
    from meetingbot.bot.local_capture import LocalCaptureError, record_local
    from meetingbot.pipeline.runner import process_file

    settings = _load(config)
    console.print(f"Recording system audio to [cyan]{output}[/cyan]... (Ctrl+C to stop)")
    try:
        record_local(output, seconds=seconds, device=device)
    except (LocalCaptureError, KeyboardInterrupt) as exc:  # noqa: BLE001
        console.print(f"[bold red]Local capture failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Recorded[/green] {output}")
    if process and output.exists():
        meeting = process_file(settings, output, title)
        console.print(f"[green]Processed[/green] {meeting.id}")


@app.command()
def cleanup(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Delete recordings older than outputs.delete_audio_after_days."""
    from meetingbot.maintenance import cleanup_old_audio

    settings = _load(config)
    removed = cleanup_old_audio(settings)
    console.print(f"Removed [cyan]{removed}[/cyan] old recording(s).")


def _which(name: str) -> str:
    from shutil import which

    found = which(name)
    return f"[green]{found}[/green]" if found else "[red]not found[/red]"


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
