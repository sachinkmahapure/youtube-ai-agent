"""
youtube_ai_agent/tools/youtube_tool.py
----------------------------------------
Uploads finished videos to YouTube using the Data API v3.
Handles OAuth2 authentication, resumable uploads, and optional scheduling.

Quota cost: ~1,600 units per upload (free quota = 10,000 units/day → ~6 uploads/day).
"""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

from crewai.tools import BaseTool
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from youtube_ai_agent.config.settings import settings

_CATEGORY_EDUCATION = "27"


class YouTubeUploadTool(BaseTool):
    name: str = "YouTube Upload Tool"
    description: str = (
        "Upload a video to YouTube with full metadata. "
        "Input: JSON string with keys: "
        '"video_path" (str), "title" (str), "description" (str), '
        '"tags" (list[str]), "format" ("short"|"long"), '
        '"schedule_datetime" (ISO-8601 str, optional). '
        'Output: JSON string with "video_id", "url", "status".'
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
            video_path: str = p["video_path"]
            title: str = p["title"]
            description: str = p["description"]
            tags: list[str] = p.get("tags", [])
            fmt: str = p.get("format", "short")
            schedule_dt: str | None = p.get("schedule_datetime") or None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return f"ERROR: invalid input JSON — {exc}"

        if not os.path.exists(video_path):
            return f"ERROR: video file not found: {video_path}"

        try:
            youtube = self._auth()
            vid_id = self._upload(youtube, video_path, title, description, tags, fmt, schedule_dt)
            url = f"https://youtube.com/watch?v={vid_id}"
            logger.info(f"✅ Uploaded: {url}")
            return json.dumps({"video_id": vid_id, "url": url, "status": "success"})
        except Exception as exc:
            logger.error(f"YouTube upload failed: {exc}")
            return f"ERROR: upload failed — {exc}"

    # ── OAuth2 ────────────────────────────────────────────────────────────────
    def _auth(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube",
        ]
        creds_file = Path(settings.youtube_credentials_file)
        creds = None

        if creds_file.exists():
            with open(creds_file, "rb") as fh:
                creds = pickle.load(fh)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.youtube_client_secrets_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            creds_file.parent.mkdir(parents=True, exist_ok=True)
            with open(creds_file, "wb") as fh:
                pickle.dump(creds, fh)

        return build("youtube", "v3", credentials=creds)

    # ── Upload ────────────────────────────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
    def _upload(
        self,
        youtube,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        fmt: str,
        schedule_dt: str | None,
    ) -> str:
        from googleapiclient.http import MediaFileUpload

        # Shorts must have #Shorts in both title and description
        if fmt == "short":
            if "#Shorts" not in title:
                title = f"{title} #Shorts"
            if "#Shorts" not in description:
                description = f"{description}\n\n#Shorts"

        if schedule_dt:
            status = {
                "privacyStatus": "private",
                "publishAt": schedule_dt,
                "selfDeclaredMadeForKids": False,
            }
        else:
            status = {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            }

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": _CATEGORY_EDUCATION,
                "defaultLanguage": "en",
            },
            "status": status,
        }

        media = MediaFileUpload(
            video_path,
            chunksize=256 * 1024,
            resumable=True,
            mimetype="video/mp4",
        )

        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        logger.info(f"Uploading: {title}")
        response = None
        while response is None:
            status_obj, response = request.next_chunk()
            if status_obj:
                logger.info(f"Upload progress: {int(status_obj.progress() * 100)}%")

        return response["id"]
