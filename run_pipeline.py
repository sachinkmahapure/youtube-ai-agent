"""
run_pipeline.py
===============
Single-file YouTube AI Agent pipeline.

NO crewai. NO torch. NO transformers. NO heavy dependencies.
Just 4 lightweight packages:

    pip install groq requests python-dotenv rich

What it does:
  1. Calls Groq (free LLM) to generate a 30-day content plan
  2. Writes a script for each video
  3. Downloads stock footage from Pexels
  4. Generates voiceover via gTTS (free, no local model needed)
  5. Assembles the video with moviepy + ffmpeg
  6. Saves everything to output/

Usage:
  python run_pipeline.py --topic "Personal Finance for Beginners" --days 1 --format short
  python run_pipeline.py --topic "Personal Finance for Beginners" --days 30 --format short
  python run_pipeline.py --help
"""

# ── stdlib only until we confirm deps are present ─────────────────────────────
import sys
import subprocess

def check_and_install():
    """Install the small set of required packages if missing."""
    required = {
        "groq":         "groq",
        "requests":     "requests",
        "dotenv":       "python-dotenv",
        "rich":         "rich",
        "gtts":         "gtts",
        "moviepy":      "moviepy==1.0.3",
        "tinydb":       "tinydb",
    }
    missing = []
    for import_name, pkg in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        print("Done. Continuing...\n")

check_and_install()

# ── Now safe to import ─────────────────────────────────────────────────────────
import argparse
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.progress import track
from tinydb import TinyDB, Query

load_dotenv()
console = Console()

# ── Config ────────────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OUTPUT_DIR     = Path(os.getenv("OUTPUT_DIR", "output"))
LOG_FILE       = Path("logs/pipeline.log")

for d in [OUTPUT_DIR/"videos", OUTPUT_DIR/"audio", OUTPUT_DIR/"scripts",
          OUTPUT_DIR/"images", Path("logs")]:
    d.mkdir(parents=True, exist_ok=True)

db = TinyDB(OUTPUT_DIR / "pipeline_state.json")
jobs_table  = db.table("jobs")
plans_table = db.table("plans")


# ══════════════════════════════════════════════════════════════════════════════
# GROQ LLM
# ══════════════════════════════════════════════════════════════════════════════

def call_groq(prompt: str, max_tokens: int = 4096) -> str:
    """Call Groq API directly via requests — no SDK needed."""
    if not GROQ_API_KEY:
        console.print("[red]ERROR: GROQ_API_KEY not set in .env[/red]")
        sys.exit(1)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.HTTPError as e:
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                console.print(f"[yellow]Rate limited — waiting {wait}s...[/yellow]")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(5)
    return ""


def parse_json(text: str):
    """Robustly extract JSON from LLM output."""
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # Find JSON boundaries
    for start, end in [("[", "]"), ("{", "}")]:
        s = text.find(start)
        e = text.rfind(end) + 1
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e])
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — CONTENT PLAN
# ══════════════════════════════════════════════════════════════════════════════

def generate_plan(topic: str, force: bool = False) -> list:
    Q = Query()
    if not force:
        row = plans_table.get(Q.topic == topic)
        if row:
            console.print(f"[green]Using cached plan for '{topic}'[/green]")
            return row["plan"]

    console.print(f"\n[cyan]Generating 30-day content plan for:[/cyan] {topic}")

    prompt = f"""
You are a YouTube content strategist for faceless educational channels.
Create a 30-day content calendar for: "{topic}"

Return ONLY a valid JSON array of 30 objects. Each object must have:
- day (int 1-30)
- title (string, YouTube-optimised, under 70 chars)
- hook (string, opening sentence that creates urgency)
- angle (string, unique perspective for this video)
- keywords (list of 5 strings)
- format (one of: "short", "long", "both")
- thumbnail_concept (string, one sentence visual description)

Rules:
- No two videos should be repetitive
- Day 1 = broad intro, Day 30 = transformation/challenge
- Mix beginner, intermediate, advanced content

Return raw JSON only. No markdown, no explanation.
"""
    raw = call_groq(prompt, max_tokens=6000)
    plan = parse_json(raw)

    if not isinstance(plan, list) or len(plan) == 0:
        console.print("[red]Failed to parse content plan. Raw output:[/red]")
        console.print(raw[:500])
        sys.exit(1)

    plan = plan[:30]
    plans_table.upsert(
        {"topic": topic, "plan": plan, "created": datetime.utcnow().isoformat()},
        Q.topic == topic
    )
    console.print(f"[green]✅ Plan ready: {len(plan)} days[/green]")
    return plan


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2A — SCRIPT
# ══════════════════════════════════════════════════════════════════════════════

def write_script(day_plan: dict, fmt: str) -> dict:
    day   = day_plan["day"]
    title = day_plan["title"]
    hook  = day_plan["hook"]
    angle = day_plan["angle"]

    if fmt == "short":
        prompt = f"""
You are a viral YouTube Shorts scriptwriter.

Title : {title}
Hook  : {hook}
Angle : {angle}
Day   : {day} of 30
Target: 55-58 seconds at natural reading pace (~130 wpm)

Structure:
1. HOOK (0-3s): Start with exactly: {hook}
2. SETUP (3-15s): 2-3 punchy sentences why this matters
3. VALUE (15-45s): Core insight in 5-7 sentences, max 12 words each
4. CTA (45-58s): "Follow for Day {day+1}. Save this."

Rules: No filler words. Short sentences. Talk directly to viewer.

Return ONLY valid JSON:
{{
  "hook": "...",
  "full_script": "...",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "scene_breaks": ["0s: ...", "15s: ...", "45s: ..."]
}}
"""
    else:
        prompt = f"""
You are a scriptwriter for faceless YouTube educational videos (7-8 min).

Title : {title}
Hook  : {hook}
Angle : {angle}
Target: 1,050-1,200 words

Structure:
1. HOOK (0-15s): Start with exactly: {hook}
2. PROMISE (15-45s): What viewer will learn
3. SECTION 1 (45s-2:30): First point + real-world example
4. SECTION 2 (2:30-4:30): Second point + real-world example
5. SECTION 3 (4:30-6:30): Most surprising insight
6. RECAP (6:30-7:30): Summarise all 3 points
7. CTA (7:30-8:00): Like, subscribe, comment question

Return ONLY valid JSON:
{{
  "hook": "...",
  "full_script": "...",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "search_queries_for_visuals": ["query1", "query2", "query3", "query4", "query5"]
}}
"""

    console.print(f"  [cyan]Writing {fmt} script for Day {day}...[/cyan]")
    raw    = call_groq(prompt)
    result = parse_json(raw)

    if not result:
        console.print(f"[yellow]  Script parse failed, using raw text[/yellow]")
        result = {"full_script": raw, "hook": hook, "word_count": len(raw.split()),
                  "estimated_duration_seconds": 58 if fmt == "short" else 480,
                  "scene_breaks": [], "search_queries_for_visuals": [title, angle]}

    # Save script to file
    script_path = OUTPUT_DIR / "scripts" / f"day{day:02d}_{fmt}_script.json"
    script_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    console.print(f"  [green]✅ Script saved: {script_path.name}[/green]")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2B — STOCK FOOTAGE
# ══════════════════════════════════════════════════════════════════════════════

def download_clips(job_id: str, queries: list, fmt: str) -> list:
    if not PEXELS_API_KEY:
        console.print("[yellow]  PEXELS_API_KEY not set — skipping footage download[/yellow]")
        return []

    n      = 4 if fmt == "short" else 6
    clips  = []
    dest   = OUTPUT_DIR / "videos" / job_id / "clips"
    dest.mkdir(parents=True, exist_ok=True)

    for i, query in enumerate(queries[:n]):
        try:
            console.print(f"  [cyan]Searching footage: '{query}'...[/cyan]")
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "per_page": 3, "orientation": "landscape"},
                timeout=15,
            )
            r.raise_for_status()
            videos = r.json().get("videos", [])
            if not videos:
                continue

            # Pick best quality ≤ 1080p mp4
            url = None
            for v in videos:
                for f in sorted(v["video_files"], key=lambda x: x.get("height", 0), reverse=True):
                    if f.get("height", 0) <= 1080 and f.get("file_type") == "video/mp4":
                        url = f["link"]
                        break
                if url:
                    break

            if not url:
                continue

            safe  = re.sub(r"[^\w]", "_", query)[:25]
            fpath = dest / f"clip_{i:02d}_{safe}.mp4"

            if not fpath.exists():
                console.print(f"  [dim]Downloading clip {i+1}/{n}...[/dim]")
                with requests.get(url, stream=True, timeout=60) as dl:
                    dl.raise_for_status()
                    with open(fpath, "wb") as fh:
                        for chunk in dl.iter_content(8192):
                            fh.write(chunk)

            clips.append(str(fpath))
            console.print(f"  [green]✅ Clip {i+1}: {fpath.name}[/green]")
            time.sleep(0.5)   # be polite to the API

        except Exception as e:
            console.print(f"  [yellow]  Clip {i+1} failed ({e}), skipping[/yellow]")

    return clips


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2C — VOICEOVER (gTTS — no local model, no torch)
# ══════════════════════════════════════════════════════════════════════════════

def generate_voiceover(job_id: str, script: str, fmt: str) -> str | None:
    audio_dir = OUTPUT_DIR / "audio" / job_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_mp3 = audio_dir / f"voiceover_{fmt}.mp3"
    out_wav = audio_dir / f"voiceover_{fmt}.wav"

    if out_wav.exists():
        return str(out_wav)
    if out_mp3.exists():
        return str(out_mp3)

    console.print(f"  [cyan]Generating voiceover ({len(script)} chars)...[/cyan]")
    try:
        from gtts import gTTS
        gTTS(text=script, lang="en", slow=False).save(str(out_mp3))
        console.print(f"  [green]✅ Voiceover saved: {out_mp3.name}[/green]")

        # Try converting to wav via ffmpeg (optional)
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(out_mp3), str(out_wav)],
                capture_output=True, timeout=60
            )
            if result.returncode == 0:
                out_mp3.unlink(missing_ok=True)
                return str(out_wav)
        except Exception:
            pass  # ffmpeg not found — mp3 is fine for moviepy

        return str(out_mp3)

    except Exception as e:
        console.print(f"  [yellow]  Voiceover failed: {e}[/yellow]")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2D — VIDEO ASSEMBLY (moviepy)
# ══════════════════════════════════════════════════════════════════════════════

def assemble_video(job_id: str, day: int, fmt: str, title: str,
                   clip_paths: list, voiceover_path: str | None) -> str | None:
    out_dir = OUTPUT_DIR / "videos" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"day{day:02d}_{fmt}_final.mp4"

    if out_path.exists():
        console.print(f"  [green]✅ Video already exists: {out_path.name}[/green]")
        return str(out_path)

    console.print(f"  [cyan]Assembling video...[/cyan]")

    try:
        from moviepy.editor import (
            AudioFileClip, ColorClip, CompositeVideoClip,
            TextClip, VideoFileClip, concatenate_videoclips,
        )
        from moviepy.video.fx.all import crop, resize

        w, h       = (1080, 1920) if fmt == "short" else (1920, 1080)
        target_dur = 58.0        if fmt == "short" else 480.0

        # Load voiceover and set actual duration
        if voiceover_path and os.path.exists(voiceover_path):
            vo         = AudioFileClip(voiceover_path)
            actual_dur = min(vo.duration, target_dur)
        else:
            vo         = None
            actual_dur = target_dur

        # Background
        valid = [p for p in clip_paths if p and os.path.exists(p)]
        bg_clips = []

        if valid:
            per = actual_dur / len(valid)
            for cp in valid:
                try:
                    c = VideoFileClip(cp).without_audio()
                    # Fit to target resolution
                    if c.w / c.h > w / h:
                        c = c.fx(resize, height=h).fx(crop, width=w, x_center=c.w/2 if hasattr(c,'w') else 0)
                    else:
                        c = c.fx(resize, width=w).fx(crop, height=h, y_center=c.h/2 if hasattr(c,'h') else 0)
                    if c.duration < per:
                        from moviepy.editor import concatenate_videoclips as cv
                        loops = int(per / c.duration) + 1
                        c = cv([c] * loops)
                    bg_clips.append(c.subclip(0, per))
                except Exception as e:
                    console.print(f"  [dim]Skipping clip: {e}[/dim]")

        if not bg_clips:
            bg_clips = [ColorClip(size=(w, h), color=(15, 15, 30), duration=actual_dur)]

        background = concatenate_videoclips(bg_clips).subclip(0, actual_dur)

        # Day counter
        layers = [background]
        try:
            wm = (TextClip(f"Day {day}/30", fontsize=36, color="white", font="Arial")
                  .set_position(("right", "top")).set_opacity(0.7).set_duration(actual_dur))
            layers.append(wm)
        except Exception:
            pass

        final = CompositeVideoClip(layers, size=(w, h)).subclip(0, actual_dur)
        if vo:
            final = final.set_audio(vo)

        console.print(f"  [cyan]Rendering → {out_path.name} (this takes a minute)...[/cyan]")
        final.write_videofile(
            str(out_path), fps=30, codec="libx264", audio_codec="aac",
            temp_audiofile=str(out_dir / "tmp_audio.m4a"), remove_temp=True,
            preset="fast", ffmpeg_params=["-crf", "23"], logger=None,
        )

        for c in bg_clips:
            try: c.close()
            except: pass
        try: final.close()
        except: pass
        if vo:
            try: vo.close()
            except: pass

        console.print(f"  [green]✅ Video rendered: {out_path.name}[/green]")
        return str(out_path)

    except ImportError:
        console.print("  [yellow]moviepy not installed — skipping assembly[/yellow]")
        console.print("  [dim]Run: pip install moviepy==1.0.3[/dim]")
        return None
    except Exception as e:
        console.print(f"  [red]  Assembly failed: {e}[/red]")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — SEO METADATA
# ══════════════════════════════════════════════════════════════════════════════

def generate_metadata(topic: str, day: int, title: str, fmt: str) -> dict:
    prompt = f"""
Generate YouTube SEO metadata for:
  Title  : {title}
  Topic  : {topic}
  Day    : {day} of 30
  Format : {fmt}

Return ONLY valid JSON:
{{
  "title": "optimised title under 70 chars",
  "description": "200-word engaging description with keywords and CTA to subscribe",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
  "category_id": "27",
  "thumbnail_prompt": "one sentence visual description for thumbnail"
}}
"""
    raw    = call_groq(prompt)
    result = parse_json(raw)
    if not isinstance(result, dict):
        result = {"title": title, "description": topic, "tags": [topic], "category_id": "27"}
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run(topic: str, fmt: str, days: int, start_day: int, no_assembly: bool):
    console.print(f"\n[bold cyan]{'='*55}[/bold cyan]")
    console.print(f"[bold cyan]  🎬 YouTube AI Pipeline[/bold cyan]")
    console.print(f"[bold cyan]{'='*55}[/bold cyan]")
    console.print(f"  Topic    : {topic}")
    console.print(f"  Format   : {fmt}")
    console.print(f"  Days     : {start_day} → {start_day + days - 1}")
    console.print(f"  Assembly : {'Off (scripts + metadata only)' if no_assembly else 'On'}")
    console.print()

    # Validate keys
    if not GROQ_API_KEY:
        console.print("[red]ERROR: GROQ_API_KEY missing from .env[/red]")
        sys.exit(1)

    plan   = generate_plan(topic)
    target = plan[start_day - 1: start_day - 1 + days]
    fmts   = ["short", "long"] if fmt == "both" else [fmt]

    results = []

    for day_plan in target:
        day = day_plan["day"]
        console.print(f"\n[bold]{'─'*55}[/bold]")
        console.print(f"[bold]  Day {day:02d}/{len(plan)} — {day_plan['title'][:50]}[/bold]")
        console.print(f"[bold]{'─'*55}[/bold]")

        for video_fmt in fmts:
            job_id = f"day{day:02d}_{video_fmt}_{uuid.uuid4().hex[:6]}"

            try:
                # Script
                script_data = write_script(day_plan, video_fmt)
                full_script = script_data.get("full_script", "")

                # Metadata
                metadata = generate_metadata(topic, day, day_plan["title"], video_fmt)

                video_path = None
                if not no_assembly:
                    # Footage
                    queries = (script_data.get("search_queries_for_visuals")
                               or day_plan.get("keywords", [day_plan["title"]])[:4])
                    clips = download_clips(job_id, queries, video_fmt)

                    # Voiceover
                    audio = generate_voiceover(job_id, full_script, video_fmt)

                    # Assemble
                    video_path = assemble_video(
                        job_id, day, video_fmt, day_plan["title"], clips, audio
                    )

                # Save metadata
                meta_path = OUTPUT_DIR / "scripts" / f"day{day:02d}_{video_fmt}_metadata.json"
                meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

                # Record result
                record = {
                    "job_id":     job_id,
                    "day":        day,
                    "format":     video_fmt,
                    "title":      day_plan["title"],
                    "video_path": video_path,
                    "metadata":   metadata,
                    "status":     "assembled" if video_path else "scripted",
                    "created":    datetime.utcnow().isoformat(),
                }
                jobs_table.insert(record)
                results.append(record)

            except Exception as e:
                console.print(f"[red]  ❌ Day {day} ({video_fmt}) failed: {e}[/red]")
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]{'='*55}[/bold cyan]")
    console.print("[bold cyan]  ✅ Pipeline Complete — Summary[/bold cyan]")
    console.print(f"[bold cyan]{'='*55}[/bold cyan]\n")

    table = Table(show_lines=True)
    table.add_column("Day",    style="cyan",  width=4)
    table.add_column("Format", style="blue",  width=6)
    table.add_column("Title",  style="white", max_width=40)
    table.add_column("Status", style="green", width=10)
    table.add_column("Output", style="dim",   max_width=30)

    for r in results:
        table.add_row(
            str(r["day"]),
            r["format"],
            r["title"][:40],
            r["status"],
            Path(r["video_path"]).name if r["video_path"] else "script only",
        )

    console.print(table)
    console.print(f"\nAll outputs saved to: [cyan]{OUTPUT_DIR.resolve()}[/cyan]")
    console.print(f"Scripts & metadata : [cyan]{OUTPUT_DIR/'scripts'}[/cyan]")
    if not no_assembly:
        console.print(f"Videos             : [cyan]{OUTPUT_DIR/'videos'}[/cyan]")
        console.print(f"Audio              : [cyan]{OUTPUT_DIR/'audio'}[/cyan]")
    console.print()


def show_plan(topic: str, force: bool):
    plan = generate_plan(topic, force=force)
    table = Table(title=f"30-Day Plan: {topic}", show_lines=True)
    table.add_column("Day",  style="cyan",   width=4)
    table.add_column("Title",style="white",  max_width=50)
    table.add_column("Fmt",  style="green",  width=5)
    table.add_column("Hook", style="yellow", max_width=40)
    for item in plan:
        table.add_row(
            str(item.get("day","")),
            item.get("title","")[:50],
            item.get("format",""),
            item.get("hook","")[:40] + "…",
        )
    console.print(table)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🎬 YouTube AI Agent — Automated Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview 30-day content plan
  python run_pipeline.py plan --topic "Personal Finance for Beginners"

  # Generate scripts + metadata only (no video rendering)
  python run_pipeline.py run --topic "Personal Finance" --days 1 --no-assembly

  # Full pipeline: scripts + footage + voiceover + video
  python run_pipeline.py run --topic "Personal Finance" --days 1 --format short

  # Full 30-day run
  python run_pipeline.py run --topic "Personal Finance" --days 30 --format short
        """
    )

    sub = parser.add_subparsers(dest="command")

    # plan
    p_plan = sub.add_parser("plan", help="Generate 30-day content plan")
    p_plan.add_argument("--topic",  required=True, help="Content topic")
    p_plan.add_argument("--force",  action="store_true", help="Regenerate even if cached")

    # run
    p_run = sub.add_parser("run", help="Run the pipeline")
    p_run.add_argument("--topic",     required=True)
    p_run.add_argument("--format",    default="short", choices=["short","long","both"])
    p_run.add_argument("--days",      type=int, default=1)
    p_run.add_argument("--start-day", type=int, default=1, dest="start_day")
    p_run.add_argument("--no-assembly", action="store_true",
                       help="Skip footage+voiceover+video. Output scripts and metadata only.")

    args = parser.parse_args()

    if args.command == "plan":
        show_plan(args.topic, args.force)
    elif args.command == "run":
        run(args.topic, args.format, args.days, args.start_day, args.no_assembly)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
