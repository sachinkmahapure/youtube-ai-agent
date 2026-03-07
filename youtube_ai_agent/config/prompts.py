"""
youtube_ai_agent/config/prompts.py
------------------------------------
All LLM prompt templates in one place.
Edit these to tune tone, style, and content structure without touching agent code.
"""

# ── Research / Planning ───────────────────────────────────────────────────────

CONTENT_PLAN_PROMPT = """
You are a YouTube content strategist specialising in faceless educational channels.
Create a 30-day content calendar for the topic: "{topic}".

For EACH of the 30 days produce exactly this JSON object:
  - day            : integer 1-30
  - title          : YouTube-optimised title, curiosity-driven, under 70 characters
  - hook           : opening 3-second sentence — must create urgency or curiosity
  - angle          : unique sub-topic or perspective for this specific video
  - keywords       : list of 5 SEO keywords
  - format         : one of "short" | "long" | "both"
  - thumbnail_concept : one sentence describing the thumbnail visual

Rules:
  - No two videos should feel repetitive — vary angles, difficulty, and style
  - Mix beginner, intermediate, and advanced content across the 30 days
  - Day 1 = broad overview; Day 30 = compelling challenge or transformation story
  - Include trending angles and common viewer questions where possible

Return ONLY a valid JSON array. No preamble, no markdown fences, no explanation.
"""

# ── Shorts Script ─────────────────────────────────────────────────────────────

SHORTS_SCRIPT_PROMPT = """
You are a viral YouTube Shorts scriptwriter. Write a script for:

  Title  : {title}
  Hook   : {hook}
  Angle  : {angle}
  Day    : {day_number} of 30
  Duration target: 55-58 seconds when read at a natural pace (~130 wpm)

Structure (follow strictly):
  1. HOOK (0-3s)      : Start with exactly: {hook}
  2. SETUP (3-15s)    : 2-3 punchy sentences explaining why this matters
  3. VALUE (15-45s)   : Core insight in 5-7 short sentences. Max 12 words each.
  4. CTA (45-58s)     : "Follow for Day {next_day} where I cover {next_topic}. Save this."

Style rules:
  - No filler words (basically, actually, literally, honestly)
  - Short sentences — conversational, talk directly TO the viewer
  - Never mention background music or visuals — voiceover only

Return ONLY valid JSON with these exact keys:
{{
  "hook": "...",
  "full_script": "...",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "scene_breaks": ["0s: description", "15s: description", "45s: description"]
}}
"""

# ── Long-form Script ──────────────────────────────────────────────────────────

LONG_VIDEO_SCRIPT_PROMPT = """
You are a scriptwriter for faceless YouTube educational videos (7-8 minutes).

  Title  : {title}
  Hook   : {hook}
  Angle  : {angle}
  Target : 7-8 minutes (~1,050-1,200 words at 150 wpm)

Structure:
  1. HOOK (0-15s)         : Open with exactly: {hook}
  2. PROMISE (15-45s)     : Tell the viewer precisely what they will learn
  3. SECTION 1 (45s-2:30) : First key point with a concrete real-world example
  4. SECTION 2 (2:30-4:30): Second key point with a concrete real-world example
  5. SECTION 3 (4:30-6:30): Third point — the most surprising or valuable insight
  6. RECAP (6:30-7:30)    : Summarise all 3 points in one sentence each
  7. CTA (7:30-8:00)      : Ask viewers to like, subscribe, and answer a question in comments

Return ONLY valid JSON with these exact keys:
{{
  "hook": "...",
  "full_script": "...",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "sections": [
    {{"title": "...", "start_seconds": 0, "end_seconds": 0, "visual_direction": "..."}}
  ],
  "search_queries_for_visuals": ["query1", "query2", "query3", "query4", "query5"]
}}
"""

# ── Visual Direction ──────────────────────────────────────────────────────────

VISUAL_DIRECTION_PROMPT = """
Given this video script section:
"{section_text}"

Generate 3 Pexels search queries (2-4 words each) that find the best stock footage
to visually represent this content.

Prefer  : people in action, clear visual metaphors, professional environments
Avoid   : abstract concepts, cluttered scenes, text-heavy images

Return ONLY a JSON array of strings.
Example : ["entrepreneur working laptop", "money growth chart", "morning routine focus"]
"""

# ── SEO Metadata ──────────────────────────────────────────────────────────────

METADATA_PROMPT = """
Generate YouTube SEO metadata for:
  Title  : {title}
  Topic  : {topic}
  Day    : {day} of 30
  Format : {format}

Return ONLY valid JSON with these exact keys:
{{
  "title"            : "optimised YouTube title under 70 characters",
  "description"      : "200-word engaging description. Include: what the video covers, 3 main points, CTA to subscribe for the 30-day series, and relevant keywords naturally woven in.",
  "tags"             : ["tag1", "tag2", ... up to 15 tags],
  "category_id"      : "27",
  "thumbnail_prompt" : "detailed visual description for thumbnail creation"
}}
"""
