"""
youtube_ai_agent/pipeline/crew.py
-----------------------------------
Core pipeline orchestrator.  Three phases:

  Phase 1 — generate_plan()   : Research Agent → 30-day content calendar
  Phase 2 — produce_video()   : Script → Media → Voice → Editor agents
  Phase 3 — publish_video()   : Publisher Agent → YouTube upload

The run() method chains all three phases for N days.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from crewai import Crew, Process
from loguru import logger

from youtube_ai_agent.agents import (
    create_editor_agent,
    create_media_agent,
    create_publisher_agent,
    create_research_agent,
    create_script_agent,
    create_voice_agent,
)
from youtube_ai_agent.config.settings import settings
from youtube_ai_agent.pipeline.state import JobStatus, PipelineState
from youtube_ai_agent.tasks.video_tasks import (
    assembly_task,
    content_plan_task,
    long_script_task,
    media_collection_task,
    publish_task,
    shorts_script_task,
    voiceover_task,
)


class YouTubePipeline:
    """
    Orchestrates the full YouTube content pipeline.

    Quick start:
        pipe = YouTubePipeline()
        pipe.run(topic="Personal Finance for Beginners", fmt="short", days=30)
    """

    def __init__(self, db_path: str = "output/pipeline_state.json") -> None:
        self.state = PipelineState(db_path=db_path)
        logger.info("YouTubePipeline initialised")

    # ── Phase 1 ───────────────────────────────────────────────────────────────
    def generate_plan(self, topic: str, force: bool = False) -> list[dict]:
        """Generate (or load cached) 30-day content calendar."""
        if not force:
            cached = self.state.get_plan(topic)
            if cached:
                logger.info(f"Using cached plan for '{topic}' ({len(cached)} days)")
                return cached

        logger.info(f"Generating 30-day plan for '{topic}'…")
        agent = create_research_agent()
        task = content_plan_task(agent, topic)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
        result = crew.kickoff()
        raw = result.raw if hasattr(result, "raw") else str(result)
        plan = _parse_json(raw)

        if not isinstance(plan, list) or not plan:
            raise ValueError(f"Content plan parsing failed. Raw output:\n{raw[:500]}")

        plan = plan[:30]
        self.state.save_plan(topic, plan)
        logger.info(f"✅ Plan ready: {len(plan)} days")
        return plan

    # ── Phase 2 ───────────────────────────────────────────────────────────────
    def produce_video(self, topic: str, day_plan: dict, fmt: str) -> str | None:
        """
        Run the production crew for one day's video.
        Returns job_id on success, None if already uploaded/skipped.
        """
        day: int = day_plan["day"]
        title: str = day_plan["title"]
        hook: str = day_plan["hook"]
        angle: str = day_plan["angle"]
        keywords: list[str] = day_plan.get("keywords", [title, topic])

        if self.state.is_uploaded(topic, day, fmt):
            logger.info(f"Day {day} ({fmt}) already uploaded — skipping")
            return None

        job_id = _make_job_id(topic, day, fmt)
        self.state.create_job(job_id, topic, day, fmt, title)
        logger.info(f"\n{'─'*60}")
        logger.info(f"Producing  Day {day:02d} | {fmt.upper()} | '{title}'")
        logger.info(f"Job ID   : {job_id}")
        logger.info(f"{'─'*60}")

        try:
            # ── Build agents ───────────────────────────────────────────
            s_agent = create_script_agent()
            m_agent = create_media_agent()
            v_agent = create_voice_agent()
            e_agent = create_editor_agent()

            # ── Build tasks with dependency chain ──────────────────────
            if fmt == "short":
                script_t = shorts_script_task(s_agent, title, hook, angle, day)
            else:
                script_t = long_script_task(s_agent, title, hook, angle, day)

            media_t = media_collection_task(
                m_agent, job_id, keywords, fmt, context=[script_t]
            )
            voice_t = voiceover_task(v_agent, job_id, fmt, context=[script_t])
            edit_t = assembly_task(
                e_agent, job_id, title, day, fmt,
                context=[script_t, media_t, voice_t],
            )

            # ── Kick off production crew ───────────────────────────────
            crew = Crew(
                agents=[s_agent, m_agent, v_agent, e_agent],
                tasks=[script_t, media_t, voice_t, edit_t],
                process=Process.sequential,
                verbose=True,
                memory=False,
            )
            result = crew.kickoff()
            video_path = (result.raw if hasattr(result, "raw") else str(result)).strip().strip("'\"")

            if not Path(video_path).exists():
                raise FileNotFoundError(f"Expected video at {video_path}")

            self.state.update(
                job_id, JobStatus.ASSEMBLED, artifacts={"video_path": video_path}
            )
            logger.info(f"✅ Assembled: {video_path}")
            return job_id

        except Exception as exc:
            logger.error(f"Production failed — Day {day} ({fmt}): {exc}")
            self.state.update(job_id, JobStatus.FAILED, error=str(exc))
            raise

    # ── Phase 3 ───────────────────────────────────────────────────────────────
    def publish_video(
        self,
        job_id: str,
        topic: str,
        day: int,
        fmt: str,
        schedule_dt: str | None = None,
    ) -> str:
        """Upload a produced video to YouTube. Returns YouTube URL."""
        job = self.state.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        video_path = job.get("artifacts", {}).get("video_path")
        if not video_path:
            raise ValueError(f"No video_path in job {job_id}")

        title = job["title"]
        agent = create_publisher_agent()
        task = publish_task(agent, job_id, title, topic, day, fmt, schedule_dt)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
        result = crew.kickoff()
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = _parse_json(raw)
        url = parsed.get("url", raw) if isinstance(parsed, dict) else raw

        self.state.update(job_id, JobStatus.UPLOADED, youtube_url=str(url))
        logger.info(f"✅ Published: {url}")
        return str(url)

    # ── Full pipeline ─────────────────────────────────────────────────────────
    def run(
        self,
        topic: str,
        fmt: str = "both",
        days: int = 30,
        start_day: int = 1,
        auto_publish: bool = True,
        schedule_start: datetime | None = None,
    ) -> None:
        """
        Run the complete pipeline for a topic.

        Args:
            topic          : Content niche (e.g. "Personal Finance for Beginners")
            fmt            : "short" | "long" | "both"
            days           : Number of days to produce (1-30)
            start_day      : Which day to start from (1-30) — for resuming
            auto_publish   : Upload to YouTube after producing each video
            schedule_start : If set, videos are scheduled from this datetime,
                             24 hours apart per video
        """
        logger.info("=" * 60)
        logger.info("🎬 YouTube AI Pipeline starting")
        logger.info(f"   Topic    : {topic}")
        logger.info(f"   Format   : {fmt}")
        logger.info(f"   Days     : {start_day} → {start_day + days - 1}")
        logger.info(f"   Publish  : {'Yes' if auto_publish else 'No (dry run)'}")
        logger.info("=" * 60)

        plan = self.generate_plan(topic)
        target = plan[start_day - 1: start_day - 1 + days]
        formats = ["short", "long"] if fmt == "both" else [fmt]
        upload_offset = 0

        for day_plan in target:
            day = day_plan["day"]
            for video_fmt in formats:
                try:
                    job_id = self.produce_video(topic, day_plan, video_fmt)

                    if job_id and auto_publish:
                        sched = None
                        if schedule_start:
                            sched = (
                                schedule_start + timedelta(hours=upload_offset)
                            ).isoformat() + "Z"
                            upload_offset += 24
                        self.publish_video(job_id, topic, day, video_fmt, sched)

                except Exception as exc:
                    logger.error(f"Pipeline error Day {day} ({video_fmt}): {exc}")
                    logger.info("Continuing with next video…")

        self.state.print_summary(topic)
        logger.info("🎉 Pipeline run complete!")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_job_id(topic: str, day: int, fmt: str) -> str:
    slug = topic[:20].lower().replace(" ", "_")
    return f"{slug}_day{day:02d}_{fmt}_{uuid.uuid4().hex[:6]}"


def _parse_json(raw: str) -> dict | list | None:
    """Robustly parse JSON from an LLM response (handles markdown fences)."""
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json … ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:] if lines[-1].strip() == "```" else lines[1:])
        text = text.rstrip("`").strip()
    # Find JSON boundaries
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        end = text.rfind(end_char) + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse JSON. Preview: {text[:200]}")
        return None
