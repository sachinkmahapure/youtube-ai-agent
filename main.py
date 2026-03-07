"""
main.py — CLI entry point for the YouTube AI Agent pipeline.

IMPORTANT: This file contains a sys.path fix so it works correctly whether
you run it from inside or outside the project directory, with or without
'pip install -e .' having been run.

Usage examples
--------------
# Preview 30-day content plan (no video produced)
python main.py plan --topic "Personal Finance for Beginners"

# Produce + upload 1 Short to test end-to-end
python main.py run --topic "Personal Finance" --format short --days 1

# Full 30-day Shorts series with scheduled uploads
python main.py run --topic "Personal Finance" --format short --days 30 \\
    --schedule "2024-12-01T09:00:00"

# Produce only (no upload) — dry run
python main.py run --topic "Personal Finance" --format short --days 3 --no-upload

# Resume from day 12
python main.py run --topic "Personal Finance" --format short --days 19 --start-day 12

# Check pipeline status
python main.py status --topic "Personal Finance"

# Always-on server mode (VPS)
python main.py serve --topic "Personal Finance" --format short
"""
from __future__ import annotations

# ── Path fix (must be before any project imports) ─────────────────────────────
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ─────────────────────────────────────────────────────────────────────────────

import click
from datetime import datetime
from loguru import logger
from rich.console import Console
from rich.table import Table

from youtube_ai_agent.pipeline.crew import YouTubePipeline
from youtube_ai_agent.pipeline.scheduler import DailyScheduler
from youtube_ai_agent.pipeline.state import PipelineState
from youtube_ai_agent.config.settings import settings

console = Console()


def _setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )
    os.makedirs("logs", exist_ok=True)
    logger.add(
        settings.log_file,
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )


@click.group()
def cli() -> None:
    """🎬  YouTube AI Agent — Automated Faceless Video Pipeline"""
    _setup_logging()


# ── plan ──────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--topic", required=True, help="Content topic")
@click.option("--force", is_flag=True, default=False, help="Regenerate even if cached")
def plan(topic: str, force: bool) -> None:
    """Generate and display a 30-day content plan (no video produced)."""
    console.print(f"\n[bold cyan]📋 Generating 30-day plan for:[/bold cyan] {topic}\n")
    pipe = YouTubePipeline()
    content_plan = pipe.generate_plan(topic, force=force)

    table = Table(title=f"30-Day Plan: {topic}", show_lines=True)
    table.add_column("Day", style="cyan", width=4)
    table.add_column("Title", style="white", max_width=48)
    table.add_column("Fmt", style="green", width=5)
    table.add_column("Hook preview", style="yellow", max_width=38)

    for item in content_plan:
        table.add_row(
            str(item.get("day", "")),
            item.get("title", "")[:48],
            item.get("format", ""),
            item.get("hook", "")[:38] + "…",
        )

    console.print(table)
    console.print(
        f"\n[green]✅ Plan ready. "
        f"Run 'python main.py run --topic \"{topic}\"' to produce videos.[/green]\n"
    )


# ── run ───────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--topic", required=True, help="Content topic")
@click.option(
    "--format", "fmt",
    default="short",
    type=click.Choice(["short", "long", "both"]),
    show_default=True,
    help="Video format",
)
@click.option("--days", default=1, show_default=True, help="Days to produce (1-30)")
@click.option("--start-day", default=1, show_default=True, help="Day to start from")
@click.option("--no-upload", is_flag=True, default=False, help="Produce but skip YouTube upload")
@click.option(
    "--schedule",
    "schedule_dt",
    default=None,
    help="ISO-8601 datetime for first upload, e.g. 2024-12-01T09:00:00",
)
def run(
    topic: str,
    fmt: str,
    days: int,
    start_day: int,
    no_upload: bool,
    schedule_dt: str | None,
) -> None:
    """Produce (and optionally upload) videos for a topic."""
    schedule_start: datetime | None = None
    if schedule_dt:
        try:
            schedule_start = datetime.fromisoformat(schedule_dt)
        except ValueError:
            console.print(f"[red]Invalid --schedule value: {schedule_dt}[/red]")
            sys.exit(1)

    console.print(f"\n[bold cyan]🎬 Starting pipeline[/bold cyan]")
    console.print(f"  Topic     : {topic}")
    console.print(f"  Format    : {fmt}")
    console.print(f"  Days      : {start_day} → {start_day + days - 1}")
    console.print(f"  Upload    : {'No (dry run)' if no_upload else 'Yes'}")
    if schedule_start:
        console.print(f"  Scheduled : {schedule_start.isoformat()}")
    console.print()

    YouTubePipeline().run(
        topic=topic,
        fmt=fmt,
        days=days,
        start_day=start_day,
        auto_publish=not no_upload,
        schedule_start=schedule_start,
    )


# ── status ────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--topic", required=True, help="Content topic")
def status(topic: str) -> None:
    """Show pipeline status for a topic."""
    state = PipelineState()
    jobs = state.all_jobs(topic)

    if not jobs:
        console.print(f"[yellow]No jobs found for topic: {topic}[/yellow]")
        return

    table = Table(title=f"Pipeline Status: {topic}", show_lines=True)
    table.add_column("Day", style="cyan", width=4)
    table.add_column("Fmt", style="blue", width=5)
    table.add_column("Title", style="white", max_width=38)
    table.add_column("Status", width=14)
    table.add_column("YouTube URL", style="yellow", max_width=32)

    colour_map = {
        "uploaded": "green", "assembled": "blue",
        "failed": "red", "planned": "white",
    }
    for job in sorted(jobs, key=lambda j: (j["day"], j["format"])):
        s = job.get("status", "unknown")
        c = colour_map.get(s, "white")
        table.add_row(
            str(job.get("day", "")),
            job.get("format", ""),
            job.get("title", "")[:38],
            f"[{c}]{s}[/{c}]",
            job.get("youtube_url") or "—",
        )

    console.print(table)
    summary = state.summary(topic)
    console.print(f"\nTotal: {summary['total']} jobs\n")


# ── serve ─────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--topic", required=True, help="Content topic")
@click.option(
    "--format", "fmt",
    default="short",
    type=click.Choice(["short", "long", "both"]),
    show_default=True,
)
@click.option("--produce-time", default="18:00", show_default=True,
              help="Daily produce time (24 h, local)")
@click.option("--upload-time", default="09:00", show_default=True,
              help="Daily upload time (24 h, local)")
def serve(topic: str, fmt: str, produce_time: str, upload_time: str) -> None:
    """Run in server/VPS mode — produce and upload one video per day automatically."""
    console.print(f"\n[bold cyan]🖥️  Server mode[/bold cyan]")
    console.print(f"  Topic        : {topic}")
    console.print(f"  Format       : {fmt}")
    console.print(f"  Produce time : {produce_time}")
    console.print(f"  Upload time  : {upload_time}")
    console.print("  Press Ctrl+C to stop\n")
    DailyScheduler(topic=topic, fmt=fmt).run_daily(
        produce_time=produce_time, upload_time=upload_time
    )


if __name__ == "__main__":
    cli()
