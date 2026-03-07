"""
tests/test_pipeline.py
-----------------------
Unit and integration tests for the YouTube AI Agent pipeline.

Run:
    pytest tests/ -v
    pytest tests/ -v --tb=short   # shorter tracebacks
"""
from __future__ import annotations

import json
import os
import sys

# Ensure project root is on path when running tests directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch


# ── State management ──────────────────────────────────────────────────────────

class TestPipelineState:
    def test_create_and_retrieve_job(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState, JobStatus
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        job = state.create_job("job_001", "Finance", 1, "short", "Test Video")
        assert job["job_id"] == "job_001"
        assert job["status"] == JobStatus.PLANNED
        assert state.get_job("job_001")["day"] == 1

    def test_status_transitions(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState, JobStatus
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        state.create_job("job_002", "Finance", 2, "long", "Long Video")
        state.update("job_002", JobStatus.ASSEMBLED, artifacts={"video_path": "/tmp/v.mp4"})
        job = state.get_job("job_002")
        assert job["status"] == JobStatus.ASSEMBLED
        assert job["artifacts"]["video_path"] == "/tmp/v.mp4"

    def test_is_uploaded(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState, JobStatus
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        state.create_job("job_003", "Finance", 3, "short", "Test")
        assert not state.is_uploaded("Finance", 3, "short")
        state.update("job_003", JobStatus.UPLOADED, youtube_url="https://yt.be/abc")
        assert state.is_uploaded("Finance", 3, "short")

    def test_save_and_load_plan(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        plan = [
            {"day": i, "title": f"Day {i}", "hook": "h", "angle": "a",
             "keywords": [], "format": "short", "thumbnail_concept": "t"}
            for i in range(1, 31)
        ]
        state.save_plan("TestTopic", plan)
        loaded = state.get_plan("TestTopic")
        assert len(loaded) == 30
        assert loaded[0]["day"] == 1
        assert loaded[29]["day"] == 30

    def test_pending_uploads(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState, JobStatus
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        state.create_job("job_a", "Topic", 1, "short", "A")
        state.create_job("job_b", "Topic", 2, "short", "B")
        state.update("job_a", JobStatus.ASSEMBLED, artifacts={"video_path": "/p"})
        pending = state.pending_uploads("Topic")
        assert len(pending) == 1
        assert pending[0]["job_id"] == "job_a"

    def test_summary(self, tmp_path):
        from youtube_ai_agent.pipeline.state import PipelineState, JobStatus
        state = PipelineState(db_path=str(tmp_path / "state.json"))
        state.create_job("j1", "Topic", 1, "short", "T1")
        state.create_job("j2", "Topic", 2, "short", "T2")
        state.update("j1", JobStatus.UPLOADED)
        s = state.summary("Topic")
        assert s["total"] == 2
        assert s["by_status"].get("uploaded") == 1


# ── JSON parsing ──────────────────────────────────────────────────────────────

class TestJSONParsing:
    def _parser(self):
        from youtube_ai_agent.pipeline.crew import _parse_json
        return _parse_json

    def test_clean_array(self):
        parse = self._parser()
        assert parse('[{"day": 1}]')[0]["day"] == 1

    def test_clean_object(self):
        parse = self._parser()
        assert parse('{"key": "value"}')["key"] == "value"

    def test_markdown_fences(self):
        parse = self._parser()
        raw = '```json\n[{"day": 2}]\n```'
        assert parse(raw)[0]["day"] == 2

    def test_invalid_returns_none(self):
        parse = self._parser()
        assert parse("not json at all") is None

    def test_empty_returns_none(self):
        parse = self._parser()
        assert parse("") is None

    def test_json_embedded_in_text(self):
        parse = self._parser()
        raw = 'Here is the result:\n[{"day": 3}]\nEnd.'
        result = parse(raw)
        assert result[0]["day"] == 3


# ── Settings ──────────────────────────────────────────────────────────────────

class TestSettings:
    def test_resolution_helpers(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("PEXELS_API_KEY", "test")
        monkeypatch.setenv("VIDEO_RESOLUTION_SHORTS", "1080x1920")
        monkeypatch.setenv("VIDEO_RESOLUTION_LONG", "1920x1080")
        # Re-import to pick up monkeypatched env
        import importlib
        import youtube_ai_agent.config.settings as s_mod
        importlib.reload(s_mod)
        from youtube_ai_agent.config.settings import Settings
        s = Settings()
        assert s.shorts_width == 1080
        assert s.shorts_height == 1920
        assert s.long_width == 1920
        assert s.long_height == 1080


# ── Prompt templates ──────────────────────────────────────────────────────────

class TestPrompts:
    def test_content_plan_prompt(self):
        from youtube_ai_agent.config.prompts import CONTENT_PLAN_PROMPT
        out = CONTENT_PLAN_PROMPT.format(topic="Finance")
        assert "Finance" in out
        assert "30" in out

    def test_shorts_script_prompt(self):
        from youtube_ai_agent.config.prompts import SHORTS_SCRIPT_PROMPT
        out = SHORTS_SCRIPT_PROMPT.format(
            title="T", hook="H", angle="A",
            day_number=1, next_day=2, next_topic="tips"
        )
        assert "55-58 seconds" in out
        assert "H" in out

    def test_long_script_prompt(self):
        from youtube_ai_agent.config.prompts import LONG_VIDEO_SCRIPT_PROMPT
        out = LONG_VIDEO_SCRIPT_PROMPT.format(title="T", hook="H", angle="A")
        assert "7-8 minutes" in out

    def test_metadata_prompt(self):
        from youtube_ai_agent.config.prompts import METADATA_PROMPT
        out = METADATA_PROMPT.format(title="T", topic="Finance", day=1, format="short")
        assert "Finance" in out


# ── Tool instantiation (smoke tests) ─────────────────────────────────────────

class TestToolInstantiation:
    def test_tavily_tool(self):
        from youtube_ai_agent.tools.tavily_tool import TavilyResearchTool
        t = TavilyResearchTool()
        assert "Research" in t.name

    def test_pexels_video_tool(self):
        from youtube_ai_agent.tools.pexels_tool import PexelsVideoTool
        t = PexelsVideoTool()
        assert "Video" in t.name

    def test_pexels_image_tool(self):
        from youtube_ai_agent.tools.pexels_tool import PexelsImageTool
        t = PexelsImageTool()
        assert "Image" in t.name

    def test_tts_tool(self):
        from youtube_ai_agent.tools.tts_tool import TTSTool
        t = TTSTool()
        assert "Speech" in t.name

    def test_editor_tool(self):
        from youtube_ai_agent.tools.editor_tool import VideoEditorTool
        t = VideoEditorTool()
        assert "Editor" in t.name

    def test_youtube_tool(self):
        from youtube_ai_agent.tools.youtube_tool import YouTubeUploadTool
        t = YouTubeUploadTool()
        assert "Upload" in t.name


# ── Tool input validation ─────────────────────────────────────────────────────

class TestToolInputValidation:
    def test_pexels_bad_input(self):
        from youtube_ai_agent.tools.pexels_tool import PexelsVideoTool
        result = PexelsVideoTool()._run("not json")
        assert result.startswith("ERROR")

    def test_tts_bad_input(self):
        from youtube_ai_agent.tools.tts_tool import TTSTool
        result = TTSTool()._run("not json")
        assert result.startswith("ERROR")

    def test_editor_bad_input(self):
        from youtube_ai_agent.tools.editor_tool import VideoEditorTool
        result = VideoEditorTool()._run("not json")
        assert result.startswith("ERROR")

    def test_youtube_bad_input(self):
        from youtube_ai_agent.tools.youtube_tool import YouTubeUploadTool
        result = YouTubeUploadTool()._run("not json")
        assert result.startswith("ERROR")

    def test_youtube_missing_file(self):
        from youtube_ai_agent.tools.youtube_tool import YouTubeUploadTool
        payload = json.dumps({
            "video_path": "/nonexistent/file.mp4",
            "title": "Test",
            "description": "Test",
        })
        result = YouTubeUploadTool()._run(payload)
        assert result.startswith("ERROR")
