"""
youtube_ai_agent/pipeline/state.py
------------------------------------
Lightweight job-state tracker backed by TinyDB (local JSON file).

Job lifecycle:
  planned → scripted → media_ready → voiced → assembled → uploaded
                                                        ↘ failed (any stage)

Resumable: re-running the pipeline skips jobs that have already reached
'assembled' or 'uploaded' status.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from loguru import logger
from tinydb import Query, TinyDB


class JobStatus(str, Enum):
    PLANNED = "planned"
    SCRIPTED = "scripted"
    MEDIA_READY = "media_ready"
    VOICED = "voiced"
    ASSEMBLED = "assembled"
    UPLOADED = "uploaded"
    FAILED = "failed"


class PipelineState:
    def __init__(self, db_path: str = "output/pipeline_state.json") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(db_path)
        self.jobs = self._db.table("jobs")
        self.plans = self._db.table("content_plans")

    # ── Content plan ──────────────────────────────────────────────────────────
    def save_plan(self, topic: str, plan: list[dict]) -> None:
        Q = Query()
        self.plans.upsert(
            {"topic": topic, "plan": plan, "saved_at": _now()},
            Q.topic == topic,
        )
        logger.info(f"Content plan saved for '{topic}' ({len(plan)} days)")

    def get_plan(self, topic: str) -> list[dict] | None:
        Q = Query()
        row = self.plans.get(Q.topic == topic)
        return row["plan"] if row else None

    # ── Job CRUD ───────────────────────────────────────────────────────────────
    def create_job(
        self, job_id: str, topic: str, day: int, fmt: str, title: str
    ) -> dict:
        job = {
            "job_id": job_id,
            "topic": topic,
            "day": day,
            "format": fmt,
            "title": title,
            "status": JobStatus.PLANNED,
            "artifacts": {},
            "youtube_url": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.jobs.insert(job)
        return job

    def update(
        self,
        job_id: str,
        status: JobStatus,
        artifacts: dict | None = None,
        youtube_url: str | None = None,
        error: str | None = None,
    ) -> None:
        Q = Query()
        patch: dict = {"status": status, "updated_at": _now()}

        if artifacts:
            existing = self.jobs.get(Q.job_id == job_id) or {}
            merged = {**existing.get("artifacts", {}), **artifacts}
            patch["artifacts"] = merged

        if youtube_url:
            patch["youtube_url"] = youtube_url
        if error:
            patch["error"] = error

        self.jobs.update(patch, Q.job_id == job_id)
        logger.debug(f"Job {job_id} → {status}")

    def get_job(self, job_id: str) -> dict | None:
        Q = Query()
        return self.jobs.get(Q.job_id == job_id)

    def is_uploaded(self, topic: str, day: int, fmt: str) -> bool:
        Q = Query()
        return bool(
            self.jobs.get(
                (Q.topic == topic)
                & (Q.day == day)
                & (Q.format == fmt)
                & (Q.status == JobStatus.UPLOADED)
            )
        )

    def is_assembled(self, topic: str, day: int, fmt: str) -> bool:
        Q = Query()
        return bool(
            self.jobs.get(
                (Q.topic == topic)
                & (Q.day == day)
                & (Q.format == fmt)
                & (Q.status == JobStatus.ASSEMBLED)
            )
        )

    def pending_uploads(self, topic: str) -> list[dict]:
        Q = Query()
        return self.jobs.search(
            (Q.topic == topic) & (Q.status == JobStatus.ASSEMBLED)
        )

    def all_jobs(self, topic: str) -> list[dict]:
        Q = Query()
        return self.jobs.search(Q.topic == topic)

    def summary(self, topic: str) -> dict:
        jobs = self.all_jobs(topic)
        counts: dict[str, int] = {}
        for j in jobs:
            s = j.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return {"topic": topic, "total": len(jobs), "by_status": counts}

    def print_summary(self, topic: str) -> None:
        s = self.summary(topic)
        logger.info("=" * 52)
        logger.info(f"Pipeline summary — {topic}")
        logger.info(f"Total jobs : {s['total']}")
        for status, count in s["by_status"].items():
            logger.info(f"  {status:<14}: {count}")
        logger.info("=" * 52)


def _now() -> str:
    return datetime.utcnow().isoformat()
