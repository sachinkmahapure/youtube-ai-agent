"""
youtube_ai_agent/tools/pexels_tool.py
---------------------------------------
Downloads royalty-free stock videos and images from the Pexels API
(free tier: 200 requests/hour).
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
from crewai.tools import BaseTool
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from youtube_ai_agent.config.settings import settings

_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
_PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"


def _headers() -> dict:
    return {"Authorization": settings.pexels_api_key}


class PexelsVideoTool(BaseTool):
    name: str = "Pexels Video Search Tool"
    description: str = (
        "Search and download a royalty-free stock video clip from Pexels. "
        'Input: JSON string with keys "query" (str), "job_id" (str), "clip_index" (int). '
        "Output: local file path to downloaded .mp4 clip, or an error string."
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
            query: str = p["query"]
            job_id: str = p["job_id"]
            idx: int = int(p.get("clip_index", 0))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return f'ERROR: input must be JSON with "query", "job_id", "clip_index". Got: {exc}'

        try:
            url = self._find_video_url(query)
            if not url:
                return f"No video found for: {query}"
            return self._download(url, job_id, idx, query)
        except Exception as exc:
            logger.error(f"PexelsVideoTool failed: {exc}")
            return f"ERROR: {exc}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _find_video_url(self, query: str) -> str | None:
        resp = requests.get(
            _PEXELS_VIDEO_URL,
            headers=_headers(),
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
        if not videos:
            return None
        for video in videos:
            for f in sorted(video["video_files"], key=lambda x: x.get("height", 0), reverse=True):
                if f.get("height", 0) <= 1080 and f.get("file_type") == "video/mp4":
                    return f["link"]
        return videos[0]["video_files"][0]["link"]

    def _download(self, url: str, job_id: str, idx: int, query: str) -> str:
        dest_dir = Path(settings.output_dir) / "videos" / job_id / "clips"
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = query.replace(" ", "_")[:30]
        dest = dest_dir / f"clip_{idx:02d}_{safe}.mp4"
        if dest.exists():
            return str(dest)
        logger.info(f"Downloading clip: {query}")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(8192):
                    fh.write(chunk)
        return str(dest)


class PexelsImageTool(BaseTool):
    name: str = "Pexels Image Search Tool"
    description: str = (
        "Search and download a royalty-free image from Pexels. "
        'Input: JSON string with keys "query" (str), "job_id" (str), "image_index" (int). '
        "Output: local file path to downloaded .jpg image, or an error string."
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
            query: str = p["query"]
            job_id: str = p["job_id"]
            idx: int = int(p.get("image_index", 0))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return f'ERROR: input must be JSON with "query", "job_id", "image_index". Got: {exc}'

        try:
            url = self._find_image_url(query)
            if not url:
                return f"No image found for: {query}"
            return self._download(url, job_id, idx, query)
        except Exception as exc:
            logger.error(f"PexelsImageTool failed: {exc}")
            return f"ERROR: {exc}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _find_image_url(self, query: str) -> str | None:
        resp = requests.get(
            _PEXELS_PHOTO_URL,
            headers=_headers(),
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        return photos[0]["src"]["large2x"] if photos else None

    def _download(self, url: str, job_id: str, idx: int, query: str) -> str:
        dest_dir = Path(settings.output_dir) / "images" / job_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = query.replace(" ", "_")[:30]
        dest = dest_dir / f"img_{idx:02d}_{safe}.jpg"
        if dest.exists():
            return str(dest)
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(8192):
                    fh.write(chunk)
        return str(dest)
