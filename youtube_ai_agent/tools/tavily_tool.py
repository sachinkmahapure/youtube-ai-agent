"""
youtube_ai_agent/tools/tavily_tool.py
---------------------------------------
Web research tool using the Tavily Search API (free tier: 1,000 searches/month).
Used by the Research Agent to find trending angles and subtopics.
"""
from __future__ import annotations

from crewai.tools import BaseTool
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from youtube_ai_agent.config.settings import settings


class TavilyResearchTool(BaseTool):
    name: str = "Web Research Tool"
    description: str = (
        "Search the web for trending content, statistics, and angles on a topic. "
        "Input: a plain-text search query string. "
        "Output: summarised research findings as text."
    )

    def _run(self, query: str) -> str:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=settings.tavily_api_key)
            results = self._search(client, query)
            return self._format(results)
        except ImportError:
            return "tavily-python not installed. Run: pip install tavily-python"
        except Exception as exc:
            logger.error(f"Tavily search failed for '{query}': {exc}")
            return f"Search unavailable — proceeding with LLM knowledge only. Error: {exc}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _search(self, client, query: str) -> dict:
        return client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

    def _format(self, results: dict) -> str:
        lines: list[str] = []
        if results.get("answer"):
            lines.append(f"SUMMARY:\n{results['answer']}\n")
        for i, r in enumerate(results.get("results", [])[:5], 1):
            lines.append(
                f"[{i}] {r.get('title', 'N/A')}\n"
                f"    {r.get('url', '')}\n"
                f"    {r.get('content', '')[:300]}...\n"
            )
        return "\n".join(lines) if lines else "No results found."
