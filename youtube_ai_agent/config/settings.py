"""
youtube_ai_agent/config/settings.py
------------------------------------
Central configuration. All values come from environment variables or .env file.
Missing required keys raise a clear error on startup — no silent failures.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Required API keys ─────────────────────────────────────────────────────
    groq_api_key: str = Field(..., env="GROQ_API_KEY")
    tavily_api_key: str = Field(..., env="TAVILY_API_KEY")
    pexels_api_key: str = Field(..., env="PEXELS_API_KEY")

    # ── LLM ───────────────────────────────────────────────────────────────────
    groq_model: str = Field("llama-3.3-70b-versatile", env="GROQ_MODEL")

    # ── YouTube ───────────────────────────────────────────────────────────────
    youtube_client_secrets_file: str = Field(
        "config/client_secrets.json", env="YOUTUBE_CLIENT_SECRETS_FILE"
    )
    youtube_credentials_file: str = Field(
        "config/youtube_credentials.json", env="YOUTUBE_CREDENTIALS_FILE"
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    output_dir: str = Field("output", env="OUTPUT_DIR")
    log_file: str = Field("logs/pipeline.log", env="LOG_FILE")
    log_level: str = Field("INFO", env="LOG_LEVEL")

    # ── Video ─────────────────────────────────────────────────────────────────
    shorts_duration: int = Field(58, env="SHORTS_DURATION_SECONDS")
    long_video_duration: int = Field(480, env="LONG_VIDEO_DURATION_SECONDS")
    shorts_resolution: str = Field("1080x1920", env="VIDEO_RESOLUTION_SHORTS")
    long_resolution: str = Field("1920x1080", env="VIDEO_RESOLUTION_LONG")

    # ── TTS ───────────────────────────────────────────────────────────────────
    kokoro_voice: str = Field("af_heart", env="KOKORO_VOICE")
    kokoro_speed: float = Field(1.1, env="KOKORO_SPEED")

    # ── Audio ─────────────────────────────────────────────────────────────────
    music_volume: float = Field(0.15, env="MUSIC_VOLUME")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def shorts_width(self) -> int:
        return int(self.shorts_resolution.split("x")[0])

    @property
    def shorts_height(self) -> int:
        return int(self.shorts_resolution.split("x")[1])

    @property
    def long_width(self) -> int:
        return int(self.long_resolution.split("x")[0])

    @property
    def long_height(self) -> int:
        return int(self.long_resolution.split("x")[1])

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)


# Single shared instance used across the package
settings = Settings()
