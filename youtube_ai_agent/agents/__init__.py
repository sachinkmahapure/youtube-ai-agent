"""
youtube_ai_agent/agents/__init__.py
-------------------------------------
All six CrewAI agent factory functions.
Each agent has a focused role, backstory, and minimal set of tools.
"""
from __future__ import annotations

from crewai import Agent
from langchain_groq import ChatGroq

from youtube_ai_agent.config.settings import settings
from youtube_ai_agent.tools import (
    PexelsImageTool,
    PexelsVideoTool,
    TTSTool,
    TavilyResearchTool,
    VideoEditorTool,
    YouTubeUploadTool,
)


def _llm() -> ChatGroq:
    """Shared Groq LLM — free tier, fastest available inference."""
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.7,
        max_tokens=4096,
    )


def create_research_agent() -> Agent:
    return Agent(
        role="YouTube Content Strategist & Researcher",
        goal=(
            "Research trending subtopics and audience questions for a given niche, "
            "then produce a complete 30-day content calendar of unique, "
            "SEO-optimised video ideas."
        ),
        backstory=(
            "You are a senior YouTube content strategist with a decade of experience "
            "scaling faceless educational channels from zero to 100K subscribers. "
            "You have a gift for finding underserved angles within competitive niches "
            "and structuring series that maximise subscriber growth and retention."
        ),
        tools=[TavilyResearchTool()],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_script_agent() -> Agent:
    return Agent(
        role="YouTube Scriptwriter",
        goal=(
            "Write compelling, viewer-retaining scripts for YouTube Shorts (55-58 s) "
            "and long-form faceless videos (7-8 min) that hook viewers in the first "
            "three seconds and end with a strong call to action."
        ),
        backstory=(
            "You have written scripts for dozens of faceless YouTube channels across "
            "finance, productivity, and self-improvement niches. You know that the first "
            "three seconds determine everything — your hooks are irresistible. "
            "You write conversationally, cut all filler, and always deliver real value."
        ),
        tools=[],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )


def create_media_agent() -> Agent:
    return Agent(
        role="Visual Media Director",
        goal=(
            "Find and download royalty-free stock footage and images from Pexels "
            "that visually reinforce each section of the video script."
        ),
        backstory=(
            "You are a visual storyteller who curates stock footage with a director's eye. "
            "Every clip you choose must earn its place — no generic b-roll, "
            "no clichéd stock imagery. You match footage to the emotional tone "
            "and information content of the voiceover."
        ),
        tools=[PexelsVideoTool(), PexelsImageTool()],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )


def create_voice_agent() -> Agent:
    return Agent(
        role="Voice Production Specialist",
        goal=(
            "Convert the finalised script into a clean, natural-sounding voiceover "
            "audio file with correct pacing for the target video duration."
        ),
        backstory=(
            "You are an audio production specialist who understands that voice quality "
            "is the most important element in a faceless YouTube channel. "
            "You use the best available local TTS to produce professional voiceovers "
            "that keep viewers engaged to the end."
        ),
        tools=[TTSTool()],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )


def create_editor_agent() -> Agent:
    return Agent(
        role="Video Editor",
        goal=(
            "Assemble the final video by combining stock footage, voiceover audio, "
            "background music, and text overlays into a polished publish-ready .mp4 "
            "in the correct format and resolution."
        ),
        backstory=(
            "You have edited hundreds of faceless YouTube videos. You know how to time "
            "cuts to the voiceover, balance music under speech, and format videos "
            "correctly so the algorithm favours them — vertical 1080×1920 for Shorts, "
            "horizontal 1920×1080 for long-form."
        ),
        tools=[VideoEditorTool()],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )


def create_publisher_agent() -> Agent:
    return Agent(
        role="YouTube SEO & Publishing Specialist",
        goal=(
            "Generate SEO-optimised metadata and upload the finished video to YouTube "
            "at the optimal scheduled time with the correct privacy status."
        ),
        backstory=(
            "You are a YouTube growth specialist who understands the platform's search "
            "and recommendation algorithm deeply. You craft titles that get clicks, "
            "descriptions that rank, and you know exactly when to publish for maximum "
            "initial velocity. You maintain brand consistency across a 30-day series."
        ),
        tools=[YouTubeUploadTool()],
        llm=_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )
