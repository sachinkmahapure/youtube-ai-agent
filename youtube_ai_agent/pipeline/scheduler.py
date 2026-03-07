"""
youtube_ai_agent/pipeline/scheduler.py
----------------------------------------
Two automation modes:

  batch  — produce all N days now, schedule uploads staggered 24 h apart
  daily  — server/VPS mode: produce one video per day at a set time,
           upload the next morning
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import schedule
from loguru import logger

from youtube_ai_agent.pipeline.crew import YouTubePipeline
from youtube_ai_agent.pipeline.state import JobStatus, PipelineState


class DailyScheduler:
    """
    Manages daily production and upload scheduling.

    Batch mode (local dev / one-shot):
        s = DailyScheduler("Personal Finance", "short")
        s.run_batch(days=30, first_upload=datetime(2024, 12, 1, 9, 0))

    Daily server mode (VPS):
        s = DailyScheduler("Personal Finance", "short")
        s.run_daily(produce_time="18:00", upload_time="09:00")
    """

    def __init__(self, topic: str, fmt: str = "both") -> None:
        self.topic = topic
        self.fmt = fmt
        self.pipeline = YouTubePipeline()
        self.state = PipelineState()

    # ── Batch mode ────────────────────────────────────────────────────────────
    def run_batch(
        self,
        days: int = 30,
        start_day: int = 1,
        first_upload: datetime | None = None,
    ) -> None:
        if first_upload is None:
            first_upload = datetime.utcnow() + timedelta(minutes=5)

        logger.info(f"Batch: producing {days} days — first upload at {first_upload.isoformat()}")
        self.pipeline.run(
            topic=self.topic,
            fmt=self.fmt,
            days=days,
            start_day=start_day,
            auto_publish=True,
            schedule_start=first_upload,
        )

    # ── Daily server mode ─────────────────────────────────────────────────────
    def run_daily(
        self,
        produce_time: str = "18:00",
        upload_time: str = "09:00",
    ) -> None:
        logger.info(
            f"Daily mode — produce: {produce_time}, upload: {upload_time}. "
            "Press Ctrl+C to stop."
        )
        schedule.every().day.at(produce_time).do(self._produce_next)
        schedule.every().day.at(upload_time).do(self._upload_pending)
        while True:
            schedule.run_pending()
            time.sleep(30)

    def _produce_next(self) -> None:
        """Produce the next unproduced day."""
        plan = self.pipeline.generate_plan(self.topic)
        done_days = {
            j["day"]
            for j in self.state.all_jobs(self.topic)
            if j.get("status") != JobStatus.FAILED
        }
        fmts = ["short", "long"] if self.fmt == "both" else [self.fmt]
        for day_plan in plan:
            if day_plan["day"] not in done_days:
                for fmt in fmts:
                    self.pipeline.produce_video(self.topic, day_plan, fmt)
                return
        logger.info("All 30 days produced!")

    def _upload_pending(self) -> None:
        """Upload the oldest assembled-but-not-yet-uploaded video."""
        pending = sorted(
            self.state.pending_uploads(self.topic), key=lambda j: j["day"]
        )
        if not pending:
            logger.info("No pending uploads.")
            return
        job = pending[0]
        self.pipeline.publish_video(
            job["job_id"], self.topic, job["day"], job["format"]
        )
