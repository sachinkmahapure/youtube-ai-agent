"""
youtube_ai_agent/tools/editor_tool.py
---------------------------------------
Assembles the final video from stock clips, voiceover audio, background music,
and text overlays using MoviePy.

Shorts  : 1080 × 1920  (vertical)
Long    : 1920 × 1080  (horizontal)
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

from crewai.tools import BaseTool
from loguru import logger

from youtube_ai_agent.config.settings import settings


class VideoEditorTool(BaseTool):
    name: str = "Video Editor Tool"
    description: str = (
        "Assemble a final .mp4 video from clips, voiceover, music, and text. "
        "Input: JSON string with keys: "
        '"job_id" (str), "format" ("short"|"long"), "voiceover_path" (str), '
        '"clip_paths" (list[str]), "title" (str), "day" (int). '
        "Output: local file path to the rendered .mp4, or an error string."
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
            job_id: str = p["job_id"]
            fmt: str = p["format"]
            voiceover: str = p["voiceover_path"]
            clips: list[str] = p["clip_paths"]
            title: str = p.get("title", "Video")
            day: int = int(p.get("day", 1))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return (
                f"ERROR: input must be JSON with job_id, format, voiceover_path, "
                f"clip_paths, title, day. Got: {exc}"
            )

        try:
            return self._assemble(job_id, fmt, voiceover, clips, title, day)
        except Exception as exc:
            logger.error(f"VideoEditorTool failed: {exc}")
            return f"ERROR: video assembly failed — {exc}"

    # ── Main assembly ──────────────────────────────────────────────────────────
    def _assemble(
        self,
        job_id: str,
        fmt: str,
        voiceover_path: str,
        clip_paths: list[str],
        title: str,
        day: int,
    ) -> str:
        from moviepy.editor import (
            AudioFileClip,
            ColorClip,
            CompositeAudioClip,
            CompositeVideoClip,
            TextClip,
            VideoFileClip,
            concatenate_videoclips,
        )
        from moviepy.video.fx.all import crop, resize

        out_dir = Path(settings.output_dir) / "videos" / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"day{day:02d}_{fmt}_final.mp4"

        if out_path.exists():
            logger.info(f"Video already rendered: {out_path}")
            return str(out_path)

        # Resolution & duration
        if fmt == "short":
            w, h = settings.shorts_width, settings.shorts_height
            target_dur = float(settings.shorts_duration)
        else:
            w, h = settings.long_width, settings.long_height
            target_dur = float(settings.long_video_duration)

        logger.info(f"Assembling {fmt} video at {w}×{h} for {target_dur}s")

        # ── Voiceover ──────────────────────────────────────────────────────
        vo = AudioFileClip(voiceover_path)
        actual_dur = min(vo.duration, target_dur)

        # ── Background clips ───────────────────────────────────────────────
        valid_clips = [p for p in clip_paths if p and os.path.exists(p)]
        bg_clips: list = []

        if valid_clips:
            per_dur = actual_dur / len(valid_clips)
            for cp in valid_clips:
                try:
                    c = VideoFileClip(cp)
                    c = self._fit(c, w, h, crop, resize)
                    if c.duration < per_dur:
                        loops = int(per_dur / c.duration) + 1
                        c = c.loop(n=loops)
                    bg_clips.append(c.subclip(0, per_dur))
                except Exception as e:
                    logger.warning(f"Skipping clip {cp}: {e}")

        if not bg_clips:
            logger.warning("No valid clips — using solid colour background")
            bg_clips = [ColorClip(size=(w, h), color=(15, 15, 30), duration=actual_dur)]

        background = concatenate_videoclips(bg_clips, method="compose").subclip(0, actual_dur)

        # ── Day counter watermark ──────────────────────────────────────────
        try:
            watermark = (
                TextClip(
                    f"Day {day}/30",
                    fontsize=36,
                    color="white",
                    font="Arial-Bold",
                )
                .set_position(("right", "top"))
                .set_opacity(0.7)
                .set_duration(actual_dur)
                .margin(right=20, top=20, opacity=0)
            )
            layers = [background, watermark]
        except Exception:
            layers = [background]

        final_video = CompositeVideoClip(layers, size=(w, h)).subclip(0, actual_dur)

        # ── Audio mix ──────────────────────────────────────────────────────
        music_path = self._random_music()
        if music_path:
            try:
                bg_music = (
                    AudioFileClip(music_path)
                    .subclip(0, actual_dur)
                    .volumex(settings.music_volume)
                )
                final_audio = CompositeAudioClip([vo, bg_music])
            except Exception as e:
                logger.warning(f"Music mix failed: {e} — using voiceover only")
                final_audio = vo
        else:
            final_audio = vo

        final_video = final_video.set_audio(final_audio)

        # ── Render ─────────────────────────────────────────────────────────
        logger.info(f"Rendering → {out_path}")
        final_video.write_videofile(
            str(out_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(out_dir / "temp_audio.m4a"),
            remove_temp=True,
            preset="fast",
            ffmpeg_params=["-crf", "23"],
            logger=None,
        )

        # Cleanup
        for c in bg_clips:
            try:
                c.close()
            except Exception:
                pass
        try:
            vo.close()
            final_video.close()
        except Exception:
            pass

        logger.info(f"✅ Video rendered: {out_path}")
        return str(out_path)

    # ── Helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _fit(clip, w: int, h: int, crop_fx, resize_fx):
        """Resize and centre-crop clip to fill target dimensions."""
        clip_ratio = clip.w / clip.h
        target_ratio = w / h
        if clip_ratio > target_ratio:
            scaled = clip.fx(resize_fx, height=h)
            return scaled.fx(crop_fx, width=w, x_center=scaled.w / 2)
        else:
            scaled = clip.fx(resize_fx, width=w)
            return scaled.fx(crop_fx, height=h, y_center=scaled.h / 2)

    @staticmethod
    def _random_music() -> str | None:
        music_dir = Path(settings.output_dir) / "music"
        if not music_dir.exists():
            return None
        tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
        return str(random.choice(tracks)) if tracks else None
