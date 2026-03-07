# 🎬 YouTube AI Agent

> Automatically plans, scripts, voices, and edits a 30-day YouTube video series — from a single command.

Powered by **Groq AI (LLaMA 3.3 70B)** · **Pexels** · **Google TTS** · **MoviePy**

**Zero heavy dependencies. No torch. No crewai. No compiled extensions.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python)
![Packages](https://img.shields.io/badge/pip_packages-6-orange?style=flat-square)
![Cost](https://img.shields.io/badge/API_Cost-$0-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## What It Does

Give it a topic and it runs a full pipeline:

| Step | What happens | Tool |
|---|---|---|
| 1 | Generates a 30-day content calendar | Groq AI |
| 2 | Writes a script for each video | Groq AI |
| 3 | Downloads matching stock footage | Pexels API |
| 4 | Creates a voiceover | Google TTS |
| 5 | Assembles the final video | MoviePy + ffmpeg |
| 6 | Saves SEO metadata (title, description, tags) | Groq AI |

Everything saves to `output/` ready for you to upload.

---

## Table of Contents

- [Before You Start](#before-you-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [How to Run](#how-to-run)
- [Output Files](#output-files)
- [Troubleshooting](#troubleshooting)

---

## Before You Start

You need three things installed on your machine before running the script.

### 1. Python 3.11 (64-bit)

Download: **[python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/)**

Scroll to the bottom of that page and click **Windows installer (64-bit)**.

During installation:
- ✅ Tick **"Add Python to PATH"** — this is unchecked by default, do not skip it
- ✅ Select **"Install for all users"**

After installing, open a **brand new** Command Prompt and verify:

```cmd
python --version
```

Must show `Python 3.11.x`. If it shows 3.12, 3.13, or 3.14 — see [Troubleshooting](#troubleshooting).

---

### 2. ffmpeg

Required for audio conversion and video rendering.

**Windows — install steps:**

1. Go to [ffmpeg.org/download.html](https://ffmpeg.org/download.html)
2. Under **Windows**, click **Windows builds by BtbN** or **gyan.dev**
3. Download the latest `ffmpeg-release-essentials.zip`
4. Extract it — rename the folder to `ffmpeg` and move it to `C:\ffmpeg`
5. Add ffmpeg to your PATH:
   - Press `Win + S` → search **"Edit the system environment variables"**
   - Click **Environment Variables**
   - Under **System variables**, find **Path** → click **Edit**
   - Click **New** → type `C:\ffmpeg\bin` → click OK on all dialogs
6. Open a **new** Command Prompt and verify:

```cmd
ffmpeg -version
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt-get install -y ffmpeg
```

---

### 3. Free API Keys

| Key | Sign up at | Free limit |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | 14,400 requests/day |
| `PEXELS_API_KEY` | [pexels.com/api](https://www.pexels.com/api/) | 200 requests/hour |

No credit card needed for either.

---

## Installation

### Step 1 — Open Command Prompt in the project folder

```cmd
cd E:\Projects\AI\youtube-ai-agent\yt-agent
```

> Use **Command Prompt** (cmd), not PowerShell.
> If you must use PowerShell, first run: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

### Step 2 — Remove any old broken venv

If you have a `venv` folder from previous attempts, delete it:

```cmd
rmdir /s /q venv
```

If there is no `venv` folder, skip this step.

---

### Step 3 — Create a fresh virtual environment

```cmd
python -m venv venv
```

---

### Step 4 — Activate the virtual environment

```cmd
venv\Scripts\activate
```

You will see `(venv)` at the start of your prompt line.

> You must run this activation command every time you open a new terminal window.

---

### Step 5 — Install dependencies

```cmd
pip install groq requests python-dotenv rich gtts moviepy==1.0.3 tinydb
```

That is all. 7 small packages. No torch, no crewai, no compiled C extensions.
The entire install takes under 60 seconds.

> The script also auto-installs any missing packages when it starts, so if you
> missed something it will fix itself on first run.

---

### Step 6 — Verify

```cmd
python run_pipeline.py --help
```

You should see the help menu printed. Installation is done.

---

## Configuration

### Step 1 — Create your .env file

```cmd
copy .env.example .env
```

### Step 2 — Open .env in Notepad and add your keys

```
GROQ_API_KEY=paste_your_groq_key_here
PEXELS_API_KEY=paste_your_pexels_key_here
```

Save and close. That is all that is required.

**Optional settings** (the defaults work fine, only change if needed):

```
GROQ_MODEL=llama-3.3-70b-versatile
OUTPUT_DIR=output
```

---

## How to Run

> Every session — activate your venv first:
> ```cmd
> cd E:\Projects\AI\youtube-ai-agent\yt-agent
> venv\Scripts\activate
> ```

---

### Test 1 — Preview the content plan

This is the safest first command. It calls Groq AI and prints your 30-day content
calendar as a table. No video, no footage, nothing downloaded. Just confirms your
Groq API key works.

```cmd
python run_pipeline.py plan --topic "Personal Finance for Beginners"
```

---

### Test 2 — Generate scripts only (no video)

Writes scripts and SEO metadata to `output/scripts/`. Skips footage download,
voiceover, and video assembly. Fastest way to see the full AI output.

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 1 --no-assembly
```

---

### Full run — 1 Short video

Downloads footage, generates voiceover, assembles a complete video.
Do this once as your first full test before running 30 days.

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 1 --format short
```

---

### Full run — 1 long-form video

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 1 --format long
```

---

### Full run — both Short and long-form for 1 day

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 1 --format both
```

---

### Full 30-day series

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 30 --format short
```

---

### Resume a stopped run

If the pipeline stopped at day 12, resume from there — completed days are skipped:

```cmd
python run_pipeline.py run --topic "Personal Finance for Beginners" --days 19 --start-day 12 --format short
```

---

### All available options

```
plan subcommand:
  --topic "..."        Content topic (required)
  --force              Regenerate plan even if one is cached

run subcommand:
  --topic "..."        Content topic (required)
  --format             short | long | both  (default: short)
  --days N             How many days to produce (default: 1)
  --start-day N        Which day to start from (default: 1)
  --no-assembly        Skip footage + voiceover + video. Output scripts only.
```

---

## Output Files

```
output/
├── pipeline_state.json          ← Tracks completed jobs (enables resume)
│
├── scripts/
│   ├── day01_short_script.json      ← Script: hook, full text, scene breaks
│   ├── day01_short_metadata.json    ← SEO: title, description, tags
│   ├── day02_short_script.json
│   ├── day02_short_metadata.json
│   └── ...
│
├── videos/
│   └── day01_short_<id>/
│       ├── clips/               ← Downloaded Pexels footage
│       └── day01_short_final.mp4    ← Final rendered video
│
└── audio/
    └── day01_short_<id>/
        └── voiceover_short.mp3      ← Generated voiceover
```

**script.json example:**
```json
{
  "hook": "Most people never learn this about money...",
  "full_script": "Most people never learn this about money...",
  "word_count": 128,
  "estimated_duration_seconds": 57,
  "scene_breaks": ["0s: hook", "15s: main point", "45s: CTA"]
}
```

**metadata.json example:**
```json
{
  "title": "The #1 Money Habit Nobody Talks About",
  "description": "In this video we cover...",
  "tags": ["personal finance", "money tips", "budgeting"],
  "category_id": "27",
  "thumbnail_prompt": "Person looking shocked at phone showing bank balance"
}
```

To upload: go to [studio.youtube.com](https://studio.youtube.com), upload the `.mp4`,
and copy-paste the title, description, and tags from the matching `_metadata.json`.

---

## Troubleshooting

### ❌ `Fatal error in launcher` or `The system cannot find the file specified`

Your venv was built with a Python version that has since been deleted (usually 3.14).

```cmd
cd E:\Projects\AI\youtube-ai-agent\yt-agent
rmdir /s /q venv
python --version
```

If `python --version` fails or still shows 3.14, install Python 3.11 from
[python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/),
tick "Add Python to PATH", then open a **brand new** Command Prompt and repeat
the Installation steps from the top.

---

### ❌ `python is not recognized as an internal or external command`

Python is not on your PATH. Reinstall Python 3.11 and tick **"Add Python to PATH"**
during the installer. Then close all terminals and open a new one.

---

### ❌ `python --version` shows 3.12, 3.13, or 3.14

You have multiple Python versions. Force 3.11 explicitly:

```cmd
rmdir /s /q venv
py -3.11 -m venv venv
venv\Scripts\activate
pip install groq requests python-dotenv rich gtts moviepy==1.0.3 tinydb
```

---

### ❌ `GROQ_API_KEY not set`

Your `.env` file is missing or the key is blank.

```cmd
copy .env.example .env
```

Open `.env` in Notepad and set:
```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

---

### ❌ `ffmpeg not found` or video assembly fails

Install ffmpeg and add `C:\ffmpeg\bin` to your Windows PATH (see [Before You Start](#before-you-start)).

Verify it works: `ffmpeg -version`

While fixing ffmpeg, run with `--no-assembly` to still get scripts and metadata:

```cmd
python run_pipeline.py run --topic "Personal Finance" --days 1 --no-assembly
```

---

### ❌ moviepy error

```cmd
pip uninstall moviepy -y
pip install moviepy==1.0.3
```

If it still fails, use `--no-assembly` — you get all scripts and metadata without video rendering.

---

### ❌ Groq 429 rate limit error

The free Groq tier allows 30 requests/minute. For a 30-day run the pipeline may
briefly hit this. It automatically waits and retries. If you want to run faster,
split across sessions — the pipeline resumes from where it stopped.

---

### Quick error reference

| Error | Fix |
|---|---|
| `Fatal error in launcher` | Delete venv, reinstall Python 3.11, create new venv |
| `python is not recognized` | Reinstall Python 3.11, tick "Add Python to PATH" |
| Wrong Python version | `py -3.11 -m venv venv` |
| `GROQ_API_KEY not set` | Add key to `.env` file |
| `ffmpeg not found` | Install ffmpeg, add `C:\ffmpeg\bin` to PATH |
| moviepy errors | `pip install moviepy==1.0.3` or use `--no-assembly` |
| Groq 429 rate limit | Wait — pipeline auto-retries. Split long runs across sessions. |

---

## Roadmap

- [ ] Automated YouTube upload
- [ ] Auto-generate thumbnails
- [ ] Higher quality local TTS voice
- [ ] Background music mixer
- [ ] Web dashboard

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built for creators who want to automate content without sacrificing quality.<br><br>
⭐ Star this repo if it helped
</div>
