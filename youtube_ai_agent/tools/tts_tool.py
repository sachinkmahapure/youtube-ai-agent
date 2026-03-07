"""
youtube_ai_agent/tools/tts_tool.py
------------------------------------
Text-to-speech tool.
Primary  : Kokoro TTS  — local, free, high-quality English voices.
Fallback : gTTS        — Google TTS, requires internet, always free.

Install Kokoro: pip install kokoro soundfile
Install gTTS  : pip install gtts  (already in requirements.txt)
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from crewai.tools import BaseTool
from loguru import logger

from youtube_ai_agent.config.settings import settings


class TTSTool(BaseTool):
    name: str = "Text To Speech Tool"
    description: str = (
        "Convert a script to a voiceover .wav audio file. "
        'Input: JSON string with keys "script" (str), "job_id" (str), "format" ("short"|"long"). '
        "Output: local file path to the generated .wav file, or an error string."
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
            script: str = p["script"]
            job_id: str = p["job_id"]
            fmt: str = p.get("format", "short")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return f'ERROR: input must be JSON with "script", "job_id". Got: {exc}'

        audio_dir = Path(settings.output_dir) / "audio" / job_id
        audio_dir.mkdir(parents=True, exist_ok=True)
        out = audio_dir / f"voiceover_{fmt}.wav"

        if out.exists():
            logger.info(f"TTS cache hit: {out}")
            return str(out)

        # Try Kokoro first, then gTTS
        result = self._try_kokoro(script, out)
        if result.startswith("ERROR"):
            logger.warning(f"Kokoro failed ({result}), falling back to gTTS")
            result = self._try_gtts(script, out)

        return result

    # ── Kokoro TTS ────────────────────────────────────────────────────────────
    def _try_kokoro(self, script: str, out: Path) -> str:
        try:
            import numpy as np
            import soundfile as sf
            from kokoro import KPipeline

            logger.info(f"Generating Kokoro TTS ({len(script)} chars)…")
            pipeline = KPipeline(lang_code="a")
            chunks = []
            for audio, _, _ in pipeline(
                script,
                voice=settings.kokoro_voice,
                speed=settings.kokoro_speed,
                split_pattern=r"\n+",
            ):
                chunks.append(audio)

            if not chunks:
                return "ERROR: Kokoro returned no audio"

            sf.write(str(out), np.concatenate(chunks), samplerate=24000)
            logger.info(f"Kokoro voiceover saved: {out}")
            return str(out)

        except ImportError:
            return "ERROR: kokoro not installed"
        except Exception as exc:
            return f"ERROR: Kokoro failed — {exc}"

    # ── gTTS fallback ─────────────────────────────────────────────────────────
    def _try_gtts(self, script: str, out: Path) -> str:
        try:
            from gtts import gTTS

            mp3 = out.with_suffix(".mp3")
            gTTS(text=script, lang="en", slow=False).save(str(mp3))
            # Convert mp3 → wav via ffmpeg
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3), str(out)],
                check=True,
                capture_output=True,
            )
            mp3.unlink(missing_ok=True)
            logger.info(f"gTTS voiceover saved: {out}")
            return str(out)

        except FileNotFoundError:
            return "ERROR: ffmpeg not found — install ffmpeg and add to PATH"
        except Exception as exc:
            return f"ERROR: gTTS failed — {exc}"
