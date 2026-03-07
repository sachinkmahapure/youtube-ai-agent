"""
youtube_ai_agent/tasks/video_tasks.py
---------------------------------------
CrewAI Task definitions — one per pipeline stage.
Tasks carry the detailed instructions each agent needs, the expected output
format, and context dependencies that wire sequential data flow.
"""
from __future__ import annotations

from crewai import Agent, Task

from youtube_ai_agent.config.prompts import (
    CONTENT_PLAN_PROMPT,
    LONG_VIDEO_SCRIPT_PROMPT,
    METADATA_PROMPT,
    SHORTS_SCRIPT_PROMPT,
)


# ── Phase 1 — Planning ────────────────────────────────────────────────────────

def content_plan_task(agent: Agent, topic: str) -> Task:
    return Task(
        description=(
            f"Research the topic '{topic}' and create a 30-day YouTube content calendar.\n\n"
            f"Steps:\n"
            f"1. Search: 'trending {topic} YouTube 2024'\n"
            f"2. Search: 'top questions about {topic}'\n"
            f"3. Search: 'best {topic} YouTube channels'\n"
            f"4. Use your findings to generate the calendar with this spec:\n\n"
            + CONTENT_PLAN_PROMPT.format(topic=topic)
        ),
        expected_output=(
            "A valid JSON array of exactly 30 objects. Each object must have: "
            "day (int), title (str), hook (str), angle (str), "
            "keywords (list[str]), format (str), thumbnail_concept (str). "
            "Return raw JSON only — no markdown fences, no preamble."
        ),
        agent=agent,
        output_file="output/content_plan.json",
    )


# ── Phase 2 — Production ──────────────────────────────────────────────────────

def shorts_script_task(
    agent: Agent,
    title: str,
    hook: str,
    angle: str,
    day: int,
    next_topic: str = "the next tip in this series",
    context: list[Task] | None = None,
) -> Task:
    return Task(
        description=(
            f"Write a YouTube Shorts script for Day {day}.\n\n"
            + SHORTS_SCRIPT_PROMPT.format(
                title=title,
                hook=hook,
                angle=angle,
                day_number=day,
                next_day=day + 1,
                next_topic=next_topic,
            )
        ),
        expected_output=(
            "Valid JSON with keys: hook (str), full_script (str), "
            "word_count (int), estimated_duration_seconds (int), "
            "scene_breaks (list[str])."
        ),
        agent=agent,
        context=context or [],
    )


def long_script_task(
    agent: Agent,
    title: str,
    hook: str,
    angle: str,
    day: int,
    context: list[Task] | None = None,
) -> Task:
    return Task(
        description=(
            f"Write a long-form faceless YouTube script for Day {day}.\n\n"
            + LONG_VIDEO_SCRIPT_PROMPT.format(title=title, hook=hook, angle=angle)
        ),
        expected_output=(
            "Valid JSON with keys: hook (str), full_script (str), word_count (int), "
            "estimated_duration_seconds (int), sections (list), "
            "search_queries_for_visuals (list[str])."
        ),
        agent=agent,
        context=context or [],
    )


def media_collection_task(
    agent: Agent,
    job_id: str,
    visual_queries: list[str],
    fmt: str,
    context: list[Task] | None = None,
) -> Task:
    n_clips = 6 if fmt == "long" else 4
    queries_str = "\n".join(f"  - {q}" for q in visual_queries[:n_clips])
    return Task(
        description=(
            f"Download {n_clips} stock video clips from Pexels for job '{job_id}'.\n\n"
            f"Search queries (use in order):\n{queries_str}\n\n"
            f"For each query call the Pexels Video Search Tool with:\n"
            f'  {{"query": "<query>", "job_id": "{job_id}", "clip_index": <0 to {n_clips-1}>}}\n\n'
            f"Return a JSON array of the {n_clips} downloaded file paths."
        ),
        expected_output=(
            f'A JSON array of {n_clips} local file paths. '
            'Example: ["/path/clip_00.mp4", "/path/clip_01.mp4"]'
        ),
        agent=agent,
        context=context or [],
    )


def voiceover_task(
    agent: Agent,
    job_id: str,
    fmt: str,
    context: list[Task] | None = None,
) -> Task:
    return Task(
        description=(
            f"Generate the voiceover audio for job '{job_id}' (format: {fmt}).\n\n"
            f"1. Extract the 'full_script' from the script task output.\n"
            f"2. Call the Text To Speech Tool with:\n"
            f'   {{"script": "<full_script>", "job_id": "{job_id}", "format": "{fmt}"}}\n'
            f"3. Return the path to the generated .wav file."
        ),
        expected_output=(
            "Local file path to the generated voiceover .wav file. "
            "Example: output/audio/job_abc/voiceover_short.wav"
        ),
        agent=agent,
        context=context or [],
    )


def assembly_task(
    agent: Agent,
    job_id: str,
    title: str,
    day: int,
    fmt: str,
    context: list[Task] | None = None,
) -> Task:
    return Task(
        description=(
            f"Assemble the final {fmt} video for Day {day}: '{title}'.\n\n"
            f"1. Get the voiceover path from the voiceover task output.\n"
            f"2. Get the clip paths list from the media task output.\n"
            f"3. Call the Video Editor Tool with:\n"
            f"   {{\n"
            f'     "job_id": "{job_id}",\n'
            f'     "format": "{fmt}",\n'
            f'     "voiceover_path": "<voiceover path>",\n'
            f'     "clip_paths": [<clip paths>],\n'
            f'     "title": "{title}",\n'
            f'     "day": {day}\n'
            f"   }}\n"
            f"4. Return the path to the rendered .mp4."
        ),
        expected_output=(
            "Local file path to the final rendered .mp4. "
            "Example: output/videos/job_abc/day01_short_final.mp4"
        ),
        agent=agent,
        context=context or [],
    )


# ── Phase 3 — Publishing ──────────────────────────────────────────────────────

def publish_task(
    agent: Agent,
    job_id: str,
    title: str,
    topic: str,
    day: int,
    fmt: str,
    schedule_datetime: str | None,
    context: list[Task] | None = None,
) -> Task:
    return Task(
        description=(
            f"Generate SEO metadata and upload the Day {day} video to YouTube.\n\n"
            f"Metadata spec:\n"
            + METADATA_PROMPT.format(title=title, topic=topic, day=day, format=fmt)
            + f"\n\nThen call the YouTube Upload Tool with:\n"
            f"  {{\n"
            f'    "video_path": "<path from assembly task>",\n'
            f'    "title": "<optimised title>",\n'
            f'    "description": "<generated description>",\n'
            f'    "tags": [<generated tags>],\n'
            f'    "format": "{fmt}",\n'
            f'    "schedule_datetime": "{schedule_datetime or ""}"\n'
            f"  }}"
        ),
        expected_output=(
            'JSON with video_id, url, status. '
            'Example: {"video_id": "abc123", "url": "https://youtube.com/watch?v=abc123", "status": "success"}'
        ),
        agent=agent,
        context=context or [],
    )
