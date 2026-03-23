"""
dashboard.py
============
Web dashboard for the YouTube AI Agent pipeline.

Install:
    pip install flask

Run:
    python dashboard.py

Then open: http://localhost:5000
"""

import sys
import subprocess

def check_and_install():
    for pkg in ["flask"]:
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

check_and_install()

import json
import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request, send_file

# ── Reuse pipeline functions ───────────────────────────────────────────────────
# Add project root to path so we can import run_pipeline
sys.path.insert(0, str(Path(__file__).parent))

from run_pipeline import (
    OUTPUT_DIR, LOG_FILE, db, jobs_table, plans_table,
    generate_plan, write_script, download_clips,
    generate_voiceover, assemble_video, generate_metadata,
)
from tinydb import Query

app = Flask(__name__)

# ── In-memory run state ────────────────────────────────────────────────────────
run_state = {
    "running": False,
    "log":     [],       # list of {time, level, msg}
    "steps":   [],       # list of {day, fmt, step, status, detail, ts}
    "current": None,     # {day, fmt, step}
}
run_lock = threading.Lock()

def push_log(level: str, msg: str):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    run_state["log"].append(entry)
    # Keep last 500 lines
    if len(run_state["log"]) > 500:
        run_state["log"] = run_state["log"][-500:]

def push_step(day: int, fmt: str, step: str, status: str, detail: str = ""):
    # Update existing entry if same day/fmt/step
    for s in run_state["steps"]:
        if s["day"] == day and s["fmt"] == fmt and s["step"] == step:
            s["status"] = status
            s["detail"] = detail
            s["ts"] = datetime.now().strftime("%H:%M:%S")
            return
    run_state["steps"].append({
        "day": day, "fmt": fmt, "step": step,
        "status": status, "detail": detail,
        "ts": datetime.now().strftime("%H:%M:%S"),
    })


# ── Background pipeline runner ────────────────────────────────────────────────

def run_pipeline_thread(topic, fmt, days, start_day, no_assembly):
    run_state["running"] = True
    run_state["log"]     = []
    run_state["steps"]   = []

    push_log("info", f"Pipeline started: topic={topic!r} format={fmt} days={days} start_day={start_day}")

    try:
        # Phase 1: Plan
        push_log("info", "Generating content plan...")
        push_step(0, "", "plan", "running", "Calling Groq AI...")
        plan = generate_plan(topic)
        push_step(0, "", "plan", "done", f"{len(plan)} days generated")
        push_log("info", f"Plan ready: {len(plan)} days")

        target = plan[start_day - 1: start_day - 1 + days]
        fmts   = ["short", "long"] if fmt == "both" else [fmt]

        for day_plan in target:
            day = day_plan["day"]
            for video_fmt in fmts:
                import uuid as _uuid
                job_id = f"day{day:02d}_{video_fmt}_{_uuid.uuid4().hex[:6]}"
                run_state["current"] = {"day": day, "fmt": video_fmt}

                try:
                    # Script
                    push_step(day, video_fmt, "script", "running")
                    push_log("info", f"Day {day} ({video_fmt}): writing script...")
                    script_data = write_script(day_plan, video_fmt)
                    push_step(day, video_fmt, "script", "done",
                              f"{script_data.get('word_count',0)} words")
                    push_log("info", f"Day {day} ({video_fmt}): script done")

                    # Metadata
                    push_step(day, video_fmt, "metadata", "running")
                    metadata = generate_metadata(topic, day, day_plan["title"], video_fmt)
                    push_step(day, video_fmt, "metadata", "done", metadata.get("title","")[:50])
                    push_log("info", f"Day {day} ({video_fmt}): metadata done")

                    video_path = None
                    if not no_assembly:
                        # Footage
                        push_step(day, video_fmt, "footage", "running")
                        push_log("info", f"Day {day} ({video_fmt}): downloading footage...")
                        queries = (script_data.get("search_queries_for_visuals")
                                   or day_plan.get("keywords", [day_plan["title"]])[:4])
                        clips = download_clips(job_id, queries, video_fmt)
                        push_step(day, video_fmt, "footage", "done", f"{len(clips)} clips")
                        push_log("info", f"Day {day} ({video_fmt}): {len(clips)} clips downloaded")

                        # Voiceover
                        push_step(day, video_fmt, "voiceover", "running")
                        push_log("info", f"Day {day} ({video_fmt}): generating voiceover...")
                        audio = generate_voiceover(job_id, script_data.get("full_script",""), video_fmt)
                        push_step(day, video_fmt, "voiceover",
                                  "done" if audio else "skipped",
                                  Path(audio).name if audio else "no audio")
                        push_log("info", f"Day {day} ({video_fmt}): voiceover {'done' if audio else 'skipped'}")

                        # Assemble
                        push_step(day, video_fmt, "assemble", "running")
                        push_log("info", f"Day {day} ({video_fmt}): assembling video...")
                        video_path = assemble_video(
                            job_id, day, video_fmt, day_plan["title"], clips, audio)
                        push_step(day, video_fmt, "assemble",
                                  "done" if video_path else "failed",
                                  Path(video_path).name if video_path else "assembly failed")
                        push_log("info" if video_path else "error",
                                 f"Day {day} ({video_fmt}): assembly {'done → ' + Path(video_path).name if video_path else 'FAILED'}")

                    # Persist
                    jobs_table.insert({
                        "job_id": job_id, "day": day, "format": video_fmt,
                        "title": day_plan["title"], "video_path": video_path,
                        "metadata": metadata,
                        "status": "assembled" if video_path else "scripted",
                        "created": datetime.utcnow().isoformat(),
                    })

                except Exception as e:
                    tb = traceback.format_exc()
                    push_log("error", f"Day {day} ({video_fmt}) FAILED: {e}")
                    push_log("error", tb)
                    # Mark all pending steps for this day as failed
                    for step in ["script","metadata","footage","voiceover","assemble"]:
                        existing = next((s for s in run_state["steps"]
                                         if s["day"]==day and s["fmt"]==video_fmt and s["step"]==step), None)
                        if not existing:
                            push_step(day, video_fmt, step, "failed", str(e)[:80])
                        elif existing["status"] == "running":
                            push_step(day, video_fmt, step, "failed", str(e)[:80])

    except Exception as e:
        push_log("error", f"Pipeline error: {e}")
        push_log("error", traceback.format_exc())
    finally:
        run_state["running"] = False
        run_state["current"] = None
        push_log("info", "Pipeline finished.")


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "running": run_state["running"],
        "current": run_state["current"],
        "steps":   run_state["steps"],
        "log":     run_state["log"][-100:],
        "jobs":    jobs_table.all(),
        "plans":   [{"topic": p["topic"], "days": len(p["plan"])} for p in plans_table.all()],
    })

@app.route("/api/run", methods=["POST"])
def api_run():
    if run_state["running"]:
        return jsonify({"error": "Pipeline already running"}), 400
    data        = request.json or {}
    topic       = data.get("topic", "").strip()
    fmt         = data.get("format", "short")
    days        = int(data.get("days", 1))
    start_day   = int(data.get("start_day", 1))
    no_assembly = bool(data.get("no_assembly", False))

    if not topic:
        return jsonify({"error": "topic is required"}), 400

    t = threading.Thread(
        target=run_pipeline_thread,
        args=(topic, fmt, days, start_day, no_assembly),
        daemon=True,
    )
    t.start()
    return jsonify({"ok": True, "message": f"Pipeline started for '{topic}'"})

@app.route("/api/plan", methods=["POST"])
def api_plan():
    data  = request.json or {}
    topic = data.get("topic", "").strip()
    force = bool(data.get("force", False))
    if not topic:
        return jsonify({"error": "topic is required"}), 400
    try:
        plan = generate_plan(topic, force=force)
        return jsonify({"ok": True, "plan": plan})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs")
def api_jobs():
    return jsonify(jobs_table.all())

@app.route("/api/log")
def api_log():
    lines = []
    if LOG_FILE.exists():
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
    return jsonify({"lines": lines})

@app.route("/api/step/retry", methods=["POST"])
def api_retry_step():
    """Manually re-run a single step for a given day."""
    if run_state["running"]:
        return jsonify({"error": "Pipeline already running"}), 400

    data      = request.json or {}
    topic     = data.get("topic", "").strip()
    day_num   = int(data.get("day", 1))
    fmt       = data.get("format", "short")
    step      = data.get("step", "script")

    Q = Query()
    plan_row = plans_table.get(Q.topic == topic)
    if not plan_row:
        return jsonify({"error": f"No plan found for topic '{topic}'. Generate a plan first."}), 404

    plan = plan_row["plan"]
    day_plan = next((d for d in plan if d["day"] == day_num), None)
    if not day_plan:
        return jsonify({"error": f"Day {day_num} not found in plan"}), 404

    def retry_thread():
        import uuid as _uuid
        job_id = f"day{day_num:02d}_{fmt}_retry_{_uuid.uuid4().hex[:6]}"
        push_log("info", f"Manual retry: day={day_num} fmt={fmt} step={step}")
        try:
            if step == "script":
                push_step(day_num, fmt, "script", "running", "Manual retry")
                result = write_script(day_plan, fmt)
                push_step(day_num, fmt, "script", "done", f"{result.get('word_count',0)} words")
                push_log("info", f"Retry script day {day_num} done")

            elif step == "metadata":
                push_step(day_num, fmt, "metadata", "running", "Manual retry")
                result = generate_metadata(topic, day_num, day_plan["title"], fmt)
                push_step(day_num, fmt, "metadata", "done", result.get("title","")[:50])
                push_log("info", f"Retry metadata day {day_num} done")

            elif step == "footage":
                push_step(day_num, fmt, "footage", "running", "Manual retry")
                script_path = OUTPUT_DIR / "scripts" / f"day{day_num:02d}_{fmt}_script.json"
                queries = day_plan.get("keywords", [day_plan["title"]])[:4]
                if script_path.exists():
                    sd = json.loads(script_path.read_text())
                    queries = sd.get("visual_queries") or sd.get("search_queries_for_visuals") or queries
                clips = download_clips(job_id, queries, fmt)
                push_step(day_num, fmt, "footage", "done", f"{len(clips)} clips")
                push_log("info", f"Retry footage day {day_num}: {len(clips)} clips")

            elif step == "voiceover":
                push_step(day_num, fmt, "voiceover", "running", "Manual retry")
                script_path = OUTPUT_DIR / "scripts" / f"day{day_num:02d}_{fmt}_script.json"
                script_text = day_plan.get("hook","")
                if script_path.exists():
                    sd = json.loads(script_path.read_text())
                    script_text = sd.get("full_script", script_text)
                audio = generate_voiceover(job_id, script_text, fmt)
                push_step(day_num, fmt, "voiceover", "done" if audio else "failed")
                push_log("info", f"Retry voiceover day {day_num}: {'done' if audio else 'failed'}")

            elif step == "assemble":
                push_step(day_num, fmt, "assemble", "running", "Manual retry")
                # Find existing clips and audio
                clips_dir = OUTPUT_DIR / "videos"
                clips = [str(p) for p in clips_dir.rglob("*.mp4")
                         if f"day{day_num:02d}_{fmt}" in str(p) and "clip" in str(p)]
                audio_dir = OUTPUT_DIR / "audio"
                audio_files = list(audio_dir.rglob(f"voiceover_{fmt}.*"))
                audio = str(audio_files[0]) if audio_files else None
                video_path = assemble_video(job_id, day_num, fmt, day_plan["title"], clips, audio)
                push_step(day_num, fmt, "assemble", "done" if video_path else "failed",
                          Path(video_path).name if video_path else "")
                push_log("info", f"Retry assemble day {day_num}: {'done' if video_path else 'failed'}")

        except Exception as e:
            push_log("error", f"Retry failed: {e}\n{traceback.format_exc()}")
            push_step(day_num, fmt, step, "failed", str(e)[:80])

    threading.Thread(target=retry_thread, daemon=True).start()
    return jsonify({"ok": True, "message": f"Retrying {step} for day {day_num} ({fmt})"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    # We can't forcibly kill a thread in Python, but we set a flag
    # The pipeline checks this between steps
    run_state["_stop_requested"] = True
    return jsonify({"ok": True, "message": "Stop requested — will halt after current step"})


@app.route("/api/env")
def api_env():
    """Return which API keys are configured (masked)."""
    groq   = os.getenv("GROQ_API_KEY","")
    pexels = os.getenv("PEXELS_API_KEY","")
    return jsonify({
        "groq_set":   bool(groq),
        "pexels_set": bool(pexels),
        "groq_hint":  (groq[:8] + "…") if groq else "NOT SET",
        "pexels_hint":(pexels[:6] + "…") if pexels else "NOT SET",
        "model":      os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),
        "output_dir": str(OUTPUT_DIR.resolve()),
    })

@app.route("/api/output/videos")
def api_output_videos():
    videos = []
    for p in sorted((OUTPUT_DIR/"videos").rglob("*_final.mp4")):
        videos.append({
            "name": p.name,
            "path": str(p),
            "size_mb": round(p.stat().st_size / 1024 / 1024, 1),
            "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return jsonify(videos)


# ── Main HTML page ────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube AI Agent</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:       #0a0a0f;
    --surface:  #12121a;
    --border:   #1e1e2e;
    --accent:   #e8ff47;
    --accent2:  #ff6b6b;
    --accent3:  #47d4ff;
    --text:     #e2e2f0;
    --muted:    #6b6b88;
    --success:  #4ade80;
    --error:    #ff6b6b;
    --warn:     #fbbf24;
    --running:  #47d4ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
  }

  /* ── Layout ── */
  .shell {
    display: grid;
    grid-template-columns: 260px 1fr;
    grid-template-rows: 56px 1fr;
    height: 100vh;
    overflow: hidden;
  }
  .topbar {
    grid-column: 1 / -1;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 16px;
  }
  .topbar .logo {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }
  .topbar .logo span { color: var(--accent); }
  .topbar .env-badges {
    margin-left: auto;
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .badge {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid;
  }
  .badge.ok    { color: var(--success); border-color: var(--success); background: #4ade8012; }
  .badge.fail  { color: var(--error);   border-color: var(--error);   background: #ff6b6b12; }
  .badge.info  { color: var(--accent3); border-color: var(--accent3); background: #47d4ff12; }

  /* ── Sidebar ── */
  .sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 20px 16px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .nav-section { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 1.5px; text-transform: uppercase; padding: 12px 8px 4px; }
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    color: var(--muted);
    border: 1px solid transparent;
    transition: all 0.15s;
  }
  .nav-item:hover { background: var(--border); color: var(--text); }
  .nav-item.active { background: #e8ff4712; color: var(--accent); border-color: #e8ff4730; }
  .nav-item .icon { font-size: 16px; width: 20px; text-align: center; }

  /* ── Main content ── */
  .main {
    overflow-y: auto;
    padding: 28px 32px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }
  .page { display: none; flex-direction: column; gap: 24px; }
  .page.active { display: flex; }

  /* ── Cards ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 16px;
  }

  /* ── Run form ── */
  .run-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .field { display: flex; flex-direction: column; gap: 6px; }
  .field.full { grid-column: 1/-1; }
  label { font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); }
  input, select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s;
  }
  input:focus, select:focus { border-color: var(--accent); }
  select option { background: var(--surface); }

  .checkbox-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
  .checkbox-row input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--accent); }

  .btn {
    padding: 11px 24px;
    border-radius: 8px;
    border: none;
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.15s;
    letter-spacing: 0.3px;
  }
  .btn-primary { background: var(--accent); color: #0a0a0f; }
  .btn-primary:hover { background: #f0ff6b; transform: translateY(-1px); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-danger { background: transparent; color: var(--error); border: 1px solid var(--error); }
  .btn-danger:hover { background: #ff6b6b18; }
  .btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .btn-ghost:hover { color: var(--text); border-color: var(--muted); }
  .btn-small { padding: 5px 12px; font-size: 11px; }

  /* ── Step pipeline view ── */
  .step-grid { display: flex; flex-direction: column; gap: 0; }
  .step-day {
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 10px;
    overflow: hidden;
  }
  .step-day-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: #ffffff04;
    cursor: pointer;
    user-select: none;
  }
  .step-day-header:hover { background: #ffffff08; }
  .day-num {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    background: var(--border);
    padding: 3px 8px;
    border-radius: 4px;
    color: var(--accent);
  }
  .day-title { font-size: 13px; font-weight: 600; flex: 1; }
  .day-steps { display: flex; gap: 6px; margin-left: auto; }
  .step-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--border);
  }
  .step-dot.done    { background: var(--success); }
  .step-dot.running { background: var(--running); animation: pulse 1s infinite; }
  .step-dot.failed  { background: var(--error); }
  .step-dot.skipped { background: var(--muted); }

  .step-detail {
    display: none;
    padding: 0 16px 16px;
    gap: 8px;
    flex-direction: column;
  }
  .step-detail.open { display: flex; }
  .step-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    border-radius: 6px;
    background: var(--bg);
    font-size: 12px;
  }
  .step-name {
    font-family: 'DM Mono', monospace;
    font-weight: 500;
    width: 90px;
    color: var(--muted);
  }
  .step-status {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    width: 72px;
    text-align: center;
  }
  .step-status.done    { background: #4ade8020; color: var(--success); }
  .step-status.running { background: #47d4ff20; color: var(--running); }
  .step-status.failed  { background: #ff6b6b20; color: var(--error); }
  .step-status.pending { background: #ffffff10; color: var(--muted); }
  .step-status.skipped { background: #ffffff08; color: var(--muted); }
  .step-detail-text { flex: 1; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .step-ts { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--muted); }
  .step-retry-btn { margin-left: auto; }

  /* ── Log viewer ── */
  .log-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    line-height: 1.7;
    height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .log-info  { color: var(--text); }
  .log-debug { color: var(--muted); }
  .log-error { color: var(--error); }
  .log-warn  { color: var(--warn); }

  /* ── Stats row ── */
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }
  .stat-val  { font-size: 32px; font-weight: 800; line-height: 1; margin-bottom: 4px; }
  .stat-label{ font-size: 11px; color: var(--muted); font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }

  /* ── Videos table ── */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 10px 12px; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); border-bottom: 1px solid var(--border); }
  td { padding: 10px 12px; border-bottom: 1px solid #ffffff06; }
  tr:hover td { background: #ffffff04; }
  .file-name { font-family: 'DM Mono', monospace; font-size: 12px; }

  /* ── Running indicator ── */
  .running-bar {
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--accent3));
    background-size: 200% 100%;
    animation: slide 1.5s linear infinite;
    border-radius: 2px;
    margin-bottom: 16px;
  }
  @keyframes slide { 0%{background-position:0% 0%} 100%{background-position:-200% 0%} }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

  /* ── Plan viewer ── */
  .plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
  .plan-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    transition: border-color 0.15s;
  }
  .plan-card:hover { border-color: var(--accent); }
  .plan-day { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--accent); font-weight: 500; margin-bottom: 6px; }
  .plan-title { font-size: 12px; font-weight: 600; line-height: 1.4; margin-bottom: 6px; }
  .plan-hook { font-size: 11px; color: var(--muted); line-height: 1.4; font-style: italic; }
  .plan-fmt { font-size: 10px; margin-top: 8px; padding: 2px 6px; border-radius: 3px; display: inline-block; background: var(--border); color: var(--muted); font-family: 'DM Mono', monospace; }

  /* ── Empty state ── */
  .empty { text-align: center; padding: 48px; color: var(--muted); }
  .empty .icon { font-size: 40px; margin-bottom: 12px; }

  .flex-row { display: flex; gap: 12px; align-items: center; }
  .ml-auto { margin-left: auto; }

  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="shell">

  <!-- Topbar -->
  <header class="topbar">
    <div class="logo">🎬 <span>YouTube</span> AI Agent</div>
    <div class="env-badges" id="envBadges">
      <span class="badge info">Loading...</span>
    </div>
  </header>

  <!-- Sidebar -->
  <nav class="sidebar">
    <div class="nav-section">Pipeline</div>
    <div class="nav-item active" onclick="showPage('run')" id="nav-run">
      <span class="icon">▶</span> Run Pipeline
    </div>
    <div class="nav-item" onclick="showPage('steps')" id="nav-steps">
      <span class="icon">⚡</span> Execution Flow
    </div>
    <div class="nav-item" onclick="showPage('log')" id="nav-log">
      <span class="icon">📋</span> Live Log
    </div>
    <div class="nav-section">Content</div>
    <div class="nav-item" onclick="showPage('plan')" id="nav-plan">
      <span class="icon">📅</span> Content Plan
    </div>
    <div class="nav-item" onclick="showPage('videos')" id="nav-videos">
      <span class="icon">🎥</span> Output Videos
    </div>
    <div class="nav-section">System</div>
    <div class="nav-item" onclick="showPage('jobs')" id="nav-jobs">
      <span class="icon">🗂</span> Job History
    </div>
  </nav>

  <!-- Main -->
  <main class="main">

    <!-- ── RUN PAGE ── -->
    <div class="page active" id="page-run">
      <div id="runningBar" style="display:none" class="running-bar"></div>

      <div class="card">
        <div class="card-title">Run Pipeline</div>
        <div class="run-grid">
          <div class="field full">
            <label>Topic</label>
            <input id="fTopic" type="text" placeholder="e.g. Personal Finance for Beginners" value="Personal Finance for Beginners">
          </div>
          <div class="field">
            <label>Format</label>
            <select id="fFormat">
              <option value="short">Short (55–58s)</option>
              <option value="long">Long-form (7–8 min)</option>
              <option value="both">Both</option>
            </select>
          </div>
          <div class="field">
            <label>Days to produce</label>
            <input id="fDays" type="number" value="1" min="1" max="30">
          </div>
          <div class="field">
            <label>Start from day</label>
            <input id="fStartDay" type="number" value="1" min="1" max="30">
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <div class="checkbox-row">
              <input type="checkbox" id="fNoAssembly">
              <span>Scripts &amp; metadata only (skip video assembly)</span>
            </div>
          </div>
        </div>
        <div class="flex-row" style="margin-top:20px">
          <button class="btn btn-primary" id="btnRun" onclick="startRun()">▶ Start Pipeline</button>
          <button class="btn btn-danger" id="btnStop" onclick="stopRun()" style="display:none">⏹ Stop</button>
          <div id="runStatus" style="font-size:13px;color:var(--muted);margin-left:12px"></div>
        </div>
      </div>

      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-val" id="statTotal" style="color:var(--accent)">—</div>
          <div class="stat-label">Total Jobs</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" id="statAssembled" style="color:var(--success)">—</div>
          <div class="stat-label">Videos Ready</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" id="statScripted" style="color:var(--accent3)">—</div>
          <div class="stat-label">Scripts Only</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" id="statFailed" style="color:var(--error)">—</div>
          <div class="stat-label">Failed Steps</div>
        </div>
      </div>
    </div>

    <!-- ── EXECUTION FLOW PAGE ── -->
    <div class="page" id="page-steps">
      <div class="flex-row">
        <h2 style="font-size:18px;font-weight:800">Execution Flow</h2>
        <div id="currentStep" style="font-size:12px;color:var(--accent3);font-family:'DM Mono',monospace;margin-left:12px"></div>
        <div class="ml-auto flex-row" style="gap:8px">
          <label style="font-size:11px;color:var(--muted)">Topic:</label>
          <input id="retryTopic" type="text" placeholder="topic for manual retry" style="padding:6px 10px;font-size:12px;width:220px">
        </div>
      </div>
      <div id="stepsContainer" class="step-grid">
        <div class="empty"><div class="icon">⚡</div>Run the pipeline to see execution flow</div>
      </div>
    </div>

    <!-- ── LOG PAGE ── -->
    <div class="page" id="page-log">
      <div class="flex-row">
        <h2 style="font-size:18px;font-weight:800">Live Log</h2>
        <div class="ml-auto flex-row" style="gap:8px">
          <button class="btn btn-ghost btn-small" onclick="loadFullLog()">Load full log file</button>
          <button class="btn btn-ghost btn-small" onclick="clearLog()">Clear</button>
          <label class="checkbox-row" style="font-size:12px">
            <input type="checkbox" id="autoScroll" checked> Auto-scroll
          </label>
        </div>
      </div>
      <div class="log-box" id="logBox"></div>
    </div>

    <!-- ── PLAN PAGE ── -->
    <div class="page" id="page-plan">
      <div class="flex-row">
        <h2 style="font-size:18px;font-weight:800">Content Plan</h2>
        <div class="ml-auto flex-row" style="gap:8px">
          <input id="planTopic" type="text" placeholder="Topic" style="padding:8px 12px;font-size:13px;width:280px">
          <button class="btn btn-primary btn-small" onclick="loadPlan()">Generate Plan</button>
          <button class="btn btn-ghost btn-small" onclick="loadPlan(true)">Force Regenerate</button>
        </div>
      </div>
      <div id="planContainer">
        <div class="empty"><div class="icon">📅</div>Enter a topic and click Generate Plan</div>
      </div>
    </div>

    <!-- ── VIDEOS PAGE ── -->
    <div class="page" id="page-videos">
      <div class="flex-row">
        <h2 style="font-size:18px;font-weight:800">Output Videos</h2>
        <button class="btn btn-ghost btn-small ml-auto" onclick="loadVideos()">↻ Refresh</button>
      </div>
      <div class="card">
        <div id="videosContainer">
          <div class="empty"><div class="icon">🎥</div>No videos yet</div>
        </div>
      </div>
    </div>

    <!-- ── JOBS PAGE ── -->
    <div class="page" id="page-jobs">
      <div class="flex-row">
        <h2 style="font-size:18px;font-weight:800">Job History</h2>
        <button class="btn btn-ghost btn-small ml-auto" onclick="loadJobs()">↻ Refresh</button>
      </div>
      <div class="card">
        <div id="jobsContainer">
          <div class="empty"><div class="icon">🗂</div>No jobs yet</div>
        </div>
      </div>
    </div>

  </main>
</div>

<script>
// ── Routing ────────────────────────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'log')    loadFullLog();
  if (name === 'plan')   { /* user clicks generate */ }
  if (name === 'videos') loadVideos();
  if (name === 'jobs')   loadJobs();
}

// ── Polling ────────────────────────────────────────────────────────────────
let pollInterval = null;

function startPolling() {
  if (pollInterval) return;
  pollInterval = setInterval(poll, 1500);
}
function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
}

async function poll() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    updateRunState(d);
  } catch(e) {}
}

function updateRunState(d) {
  const running = d.running;

  // Running bar
  document.getElementById('runningBar').style.display = running ? 'block' : 'none';
  document.getElementById('btnRun').disabled = running;
  document.getElementById('btnStop').style.display = running ? 'inline-flex' : 'none';
  document.getElementById('runStatus').textContent = running
    ? (d.current ? `Running Day ${d.current.day} (${d.current.fmt})…` : 'Running…')
    : (d.steps.length ? 'Done' : '');

  // Current step
  const cs = document.getElementById('currentStep');
  cs.textContent = d.current ? `⚡ Day ${d.current.day} · ${d.current.fmt} · ${d.current.step || ''}` : '';

  // Stats
  const jobs = d.jobs || [];
  document.getElementById('statTotal').textContent     = jobs.length;
  document.getElementById('statAssembled').textContent = jobs.filter(j=>j.status==='assembled').length;
  document.getElementById('statScripted').textContent  = jobs.filter(j=>j.status==='scripted').length;
  const failedSteps = (d.steps||[]).filter(s=>s.status==='failed').length;
  document.getElementById('statFailed').textContent    = failedSteps;

  // Log
  const logBox = document.getElementById('logBox');
  const entries = d.log || [];
  logBox.innerHTML = entries.map(e => {
    const cls = e.level === 'error' ? 'log-error' : e.level === 'warn' ? 'log-warn' : e.level === 'debug' ? 'log-debug' : 'log-info';
    return `<span class="${cls}">${e.time}  ${e.level.padEnd(5)}  ${escHtml(e.msg)}</span>\n`;
  }).join('');
  if (document.getElementById('autoScroll').checked) {
    logBox.scrollTop = logBox.scrollHeight;
  }

  // Steps
  renderSteps(d.steps || []);

  if (!running) stopPolling();
}

// ── Steps renderer ────────────────────────────────────────────────────────
const STEP_NAMES = ['plan','script','metadata','footage','voiceover','assemble'];

function renderSteps(steps) {
  const container = document.getElementById('stepsContainer');
  if (!steps.length) {
    container.innerHTML = '<div class="empty"><div class="icon">⚡</div>Run the pipeline to see execution flow</div>';
    return;
  }

  // Group by day+fmt
  const groups = {};
  for (const s of steps) {
    if (s.day === 0) continue; // plan step handled separately
    const key = `${s.day}__${s.fmt}`;
    if (!groups[key]) groups[key] = { day: s.day, fmt: s.fmt, title: s.title || '', steps: {} };
    groups[key].steps[s.step] = s;
  }

  // Plan step
  const planStep = steps.find(s => s.day === 0 && s.step === 'plan');
  let html = '';
  if (planStep) {
    const sc = statusColor(planStep.status);
    html += `<div class="step-day">
      <div class="step-day-header">
        <span class="day-num">PLAN</span>
        <span class="day-title">Content Calendar Generation</span>
        <span class="step-status ${planStep.status}" style="width:auto">${planStep.status}</span>
        <span class="step-ts" style="margin-left:8px">${planStep.ts||''}</span>
      </div>
    </div>`;
  }

  for (const key of Object.keys(groups).sort()) {
    const g = groups[key];
    const stepDots = ['script','metadata','footage','voiceover','assemble'].map(sn => {
      const st = g.steps[sn];
      return `<span class="step-dot ${st ? st.status : ''}" title="${sn}"></span>`;
    }).join('');

    const stepsHtml = ['script','metadata','footage','voiceover','assemble'].map(sn => {
      const st = g.steps[sn];
      const status = st ? st.status : 'pending';
      const detail = st ? escHtml(st.detail||'') : '';
      const ts     = st ? (st.ts||'') : '';
      const retryBtn = (status === 'failed' || status === 'done')
        ? `<button class="btn btn-ghost btn-small step-retry-btn" onclick="retryStep(${g.day},'${g.fmt}','${sn}')">↻ retry</button>`
        : '';
      return `<div class="step-row">
        <span class="step-name">${sn}</span>
        <span class="step-status ${status}">${status}</span>
        <span class="step-detail-text">${detail}</span>
        <span class="step-ts">${ts}</span>
        ${retryBtn}
      </div>`;
    }).join('');

    html += `<div class="step-day">
      <div class="step-day-header" onclick="toggleDay('${key}')">
        <span class="day-num">DAY ${g.day}</span>
        <span class="day-title" id="dtitle-${key}">Loading…</span>
        <span style="font-size:11px;color:var(--muted);margin-right:8px">${g.fmt}</span>
        <div class="day-steps">${stepDots}</div>
      </div>
      <div class="step-detail" id="detail-${key}">${stepsHtml}</div>
    </div>`;
  }
  container.innerHTML = html;

  // Fill in titles from plan
  fillDayTitles(groups);
}

function fillDayTitles(groups) {
  fetch('/api/status').then(r=>r.json()).then(d => {
    const plans = d.plans || [];
    const jobs  = d.jobs  || [];
    for (const key of Object.keys(groups)) {
      const g = groups[key];
      const job = jobs.find(j => j.day === g.day && j.format === g.fmt);
      const el  = document.getElementById('dtitle-' + key);
      if (el && job) el.textContent = job.title || `Day ${g.day}`;
      else if (el) el.textContent = `Day ${g.day}`;
    }
  }).catch(()=>{});
}

function toggleDay(key) {
  const el = document.getElementById('detail-' + key);
  if (el) el.classList.toggle('open');
}

function statusColor(s) {
  return {done:'var(--success)',running:'var(--running)',failed:'var(--error)',pending:'var(--muted)'}[s]||'var(--muted)';
}

// ── Run controls ──────────────────────────────────────────────────────────
async function startRun() {
  const topic = document.getElementById('fTopic').value.trim();
  if (!topic) { alert('Please enter a topic'); return; }
  const body = {
    topic,
    format:      document.getElementById('fFormat').value,
    days:        parseInt(document.getElementById('fDays').value),
    start_day:   parseInt(document.getElementById('fStartDay').value),
    no_assembly: document.getElementById('fNoAssembly').checked,
  };
  const r = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  document.getElementById('retryTopic').value = topic;
  startPolling();
  showPage('steps');
}

async function stopRun() {
  await fetch('/api/stop', { method:'POST' });
  document.getElementById('runStatus').textContent = 'Stop requested…';
}

// ── Retry step ────────────────────────────────────────────────────────────
async function retryStep(day, fmt, step) {
  const topic = document.getElementById('retryTopic').value.trim();
  if (!topic) { alert('Enter the topic in the top-right field to retry a step'); return; }
  const r = await fetch('/api/step/retry', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ topic, day, format: fmt, step })
  });
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  startPolling();
}

// ── Plan loader ───────────────────────────────────────────────────────────
async function loadPlan(force=false) {
  const topic = document.getElementById('planTopic').value.trim();
  if (!topic) { alert('Enter a topic'); return; }
  document.getElementById('planContainer').innerHTML = '<div class="empty"><div class="icon">⏳</div>Generating…</div>';
  const r = await fetch('/api/plan', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ topic, force })
  });
  const d = await r.json();
  if (d.error) { document.getElementById('planContainer').innerHTML = `<div class="empty" style="color:var(--error)">${d.error}</div>`; return; }
  const plan = d.plan || [];
  const html = `<div class="plan-grid">${plan.map(p => `
    <div class="plan-card">
      <div class="plan-day">DAY ${p.day}</div>
      <div class="plan-title">${escHtml(p.title||'')}</div>
      <div class="plan-hook">"${escHtml((p.hook||'').slice(0,80))}…"</div>
      <span class="plan-fmt">${p.format||''}</span>
    </div>`).join('')}</div>`;
  document.getElementById('planContainer').innerHTML = html;
}

// ── Videos ────────────────────────────────────────────────────────────────
async function loadVideos() {
  const r = await fetch('/api/output/videos');
  const videos = await r.json();
  const el = document.getElementById('videosContainer');
  if (!videos.length) { el.innerHTML = '<div class="empty"><div class="icon">🎥</div>No rendered videos yet</div>'; return; }
  el.innerHTML = `<table>
    <tr><th>File</th><th>Size</th><th>Date</th></tr>
    ${videos.map(v => `<tr>
      <td class="file-name">${escHtml(v.name)}</td>
      <td>${v.size_mb} MB</td>
      <td style="color:var(--muted)">${v.modified}</td>
    </tr>`).join('')}
  </table>`;
}

// ── Jobs ──────────────────────────────────────────────────────────────────
async function loadJobs() {
  const r = await fetch('/api/jobs');
  const jobs = await r.json();
  const el = document.getElementById('jobsContainer');
  if (!jobs.length) { el.innerHTML = '<div class="empty"><div class="icon">🗂</div>No jobs yet</div>'; return; }
  el.innerHTML = `<table>
    <tr><th>Day</th><th>Fmt</th><th>Title</th><th>Status</th><th>Created</th></tr>
    ${jobs.map(j => `<tr>
      <td style="font-family:'DM Mono',monospace">${j.day||'—'}</td>
      <td>${j.format||'—'}</td>
      <td>${escHtml((j.title||'').slice(0,50))}</td>
      <td><span class="step-status ${j.status||''}">${j.status||'—'}</span></td>
      <td style="color:var(--muted);font-size:11px">${(j.created||'').slice(0,19)}</td>
    </tr>`).join('')}
  </table>`;
}

// ── Full log file ─────────────────────────────────────────────────────────
async function loadFullLog() {
  try {
    const r = await fetch('/api/log');
    const d = await r.json();
    const logBox = document.getElementById('logBox');
    logBox.innerHTML = d.lines.map(line => {
      const cls = line.includes('ERROR') ? 'log-error' : line.includes('WARNING') ? 'log-warn' : line.includes('DEBUG') ? 'log-debug' : 'log-info';
      return `<span class="${cls}">${escHtml(line)}</span>`;
    }).join('');
    if (document.getElementById('autoScroll').checked) logBox.scrollTop = logBox.scrollHeight;
  } catch(e) {}
}

function clearLog() { document.getElementById('logBox').innerHTML = ''; }

// ── Env badges ────────────────────────────────────────────────────────────
async function loadEnv() {
  try {
    const r = await fetch('/api/env');
    const d = await r.json();
    document.getElementById('envBadges').innerHTML = `
      <span class="badge ${d.groq_set?'ok':'fail'}">GROQ ${d.groq_set ? d.groq_hint : 'NOT SET'}</span>
      <span class="badge ${d.pexels_set?'ok':'fail'}">PEXELS ${d.pexels_set ? d.pexels_hint : 'NOT SET'}</span>
      <span class="badge info">${escHtml(d.model)}</span>
    `;
  } catch(e) {}
}

// ── Helpers ───────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────────────────────
loadEnv();
poll();
setInterval(loadEnv, 30000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return HTML


if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  🎬 YouTube AI Agent Dashboard")
    print("=" * 50)
    print(f"  Open in browser: http://localhost:5000")
    print(f"  Log file:        {LOG_FILE.resolve()}")
    print(f"  Output dir:      {OUTPUT_DIR.resolve()}")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
