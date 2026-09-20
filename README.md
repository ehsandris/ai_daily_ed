# 🤖 AI News Bot (Serverless Telegram Bot & AI Editor)

An automated, serverless bot that acts as a senior tech news editor. It aggregates the latest AI news from top global and local sources, filters out the noise, and uses a Large Language Model (LLM) to rewrite the most important news in a natural, engaging, and analytical tone before posting it to a Telegram channel.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/Automated-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot_API-26A5E4?logo=telegram&logoColor=white)
![Ollama](https://img.shields.io/badge/AI-Ollama_Cloud-000000?logo=ollama&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Key Features

- **⚙️ 100% Serverless Architecture:** No dedicated servers, VPS, or hosting costs required. All processes run on GitHub Actions' free tier, completely bypassing regional network restrictions (like Telegram filtering in Iran).
- **🧠 AI Quality Gate:** The bot doesn't just copy-paste! The AI evaluates the importance of the news. If an article is trivial or low-value, it vetoes the post (`[[SKIP]]`) to maintain the channel's high quality.
- **🎭 Dynamic Style Injection:** To prevent robotic and repetitive formatting, the AI dynamically determines the best writing angle for each news item (e.g., analytical, provocative question, short punchy, direct journalistic) based on the news context.
- **🛡️ Stateful Memory (Deduplication):** Using `posted_history.json` and automated commits, the bot remembers previously posted URLs and ensures no news is ever posted twice. The legacy flat-list format is auto-migrated to the new `{url: ISO timestamp}` format.
- **🌐 Multi-Source Aggregation:** Simultaneously monitors 8 top-tier global and local RSS feeds (TechCrunch, The Verge, VentureBeat, Wired, MIT Tech Review, Hugging Face, Zoomit, Digiato).
- **📰 Automated Weekly Bulletin:** In addition to real-time news, it generates a magazine-style weekly summary, ranking the top 5–7 news stories of the week by importance, complete with deep analysis.
- **🚨 Admin Alert System:** If a critical error occurs (e.g., API downtime or Telegram errors), the bot instantly sends a detailed error log to the admin's Telegram account.
- **🔒 Cross-Platform Safe:** File locking uses `fcntl` on Linux/macOS and falls back to `portalocker` (with a safe no-op as the last resort). Verified to run on GitHub Actions runners.

---

## 🧠 Architecture & Workflow

This bot follows an Event-Driven architecture. There are **two scheduled workflows** that share a single `posted_history.json` file via a `concurrency` group, so they never overwrite each other.

```
┌──────────────────┐     every hour      ┌─────────────────┐
│  GitHub Actions  │────────────────────▶│   main.py       │
│  workflow bot.yml│                     │                 │
└──────────────────┘                     │ 1. fetch RSS    │
                                         │ 2. filter junk  │
┌──────────────────┐  every Friday 15:30 │ 3. dedupe       │
│  workflow weekly │────────────────────▶│ 4. ask LLM      │
│  .yml (MODE=     │                     │ 5. format HTML  │
│  WEEKLY)         │                     │ 6. send Telegram│
└──────────────────┘                     └─────────────────┘
                                                  │
                                                  ▼
                                        posted_history.json
                                                  │
                                                  ▼
                                       auto-commit & push back
```

1. **Cron Job:** A scheduled trigger in GitHub Actions wakes up the Python script (hourly for daily, Friday 15:30 UTC for weekly).
2. **Aggregation:** RSS feeds are parsed. News older than 24 h (or 168 h for weekly) and titles containing "junk" keywords are filtered out.
3. **Deduplication:** Previously posted URLs (stored in `posted_history.json`) are removed from the list.
4. **AI Processing (Ollama):** The curated list is sent to the LLM. The model selects the single most important news, decides on the best writing style, and generates the post inside `<decision>` and `<post>` tags.
5. **Post-Processing (Python):** The Python script parses the AI's decision, formats the text to HTML, bolds the title, and injects a clickable source link at the bottom.
6. **Delivery & Memory:** The final post is sent via the Telegram Bot API, and the new URL is committed back to the repository's memory file.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- A GitHub account.
- A Telegram Bot created via `@BotFather` (with its API Token).
- A Telegram Channel where the bot is an Administrator.
- An API Key from an AI provider (e.g., Ollama Cloud, OpenRouter, or Groq).

### 2. Environment Variables (GitHub Secrets)
In your GitHub repository, navigate to **Settings → Secrets and variables → Actions** and add:

| Secret          | Required | Description                                              |
|-----------------|----------|----------------------------------------------------------|
| `BOT_TOKEN`     | ✅       | Your Telegram bot token.                                 |
| `CHANNEL_ID`    | ✅       | Telegram channel ID (e.g. `@my_ai_channel`).             |
| `AI_API_KEY`    | ✅       | Your AI provider API key.                                |
| `AI_MODEL`      | ✅       | Model name to use (e.g. `llama3.2`, `gemma2`).          |
| `ADMIN_CHAT_ID` | optional | Your personal numeric Telegram ID for error alerts.      |

Optional repository **variables** (Settings → Variables):

| Variable            | Default               | Description                                  |
|---------------------|-----------------------|----------------------------------------------|
| `AI_HOST`           | `https://ollama.com`  | Ollama-compatible endpoint.                  |
| `SUMMARY_MAX_CHARS` | `600`                 | Max characters per news summary sent to LLM. |
| `AI_TIMEOUT`        | `300`                 | Per-request AI timeout in seconds.           |

### 3. Project Files
```
.
├── main.py                       # Core logic and processing engine
├── prompt.txt                    # Advanced XML prompt for daily news
├── weekly_prompt.txt             # Prompt for generating the weekly magazine bulletin
├── requirements.txt              # Pinned Python dependencies
├── LICENSE                       # MIT License
├── test_main.py                  # Unit tests (no network)
├── posted_history.json           # JSON database for posted URLs (auto-managed)
└── .github/
    └── workflows/
        ├── bot.yml               # Hourly daily bot
        ├── weekly.yml            # Friday 15:30 UTC weekly bulletin
        └── keepalive.yml         # Monthly no-op commit to keep schedules alive
```

---

## 🛠️ Tech Stack

- **Backend & Scheduling:** GitHub Actions, Python 3.11
- **AI Engine:** Ollama Cloud API / OpenAI-compatible APIs
- **News Parsing:** Feedparser
- **Messaging:** Telegram Bot API
- **File Locking:** `fcntl` (POSIX) / `portalocker` (Windows fallback)
- **Prompt Engineering:** XML structuring, dynamic routing, length-bounded output.

---

## 🧪 Local Development

```bash
git clone https://github.com/ehsandris/ai_daily_ed.git
cd ai_daily_ed
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run the test suite (no API keys needed).
python -m unittest test_main.py -v
```

To smoke-test a single run locally:

```bash
export BOT_TOKEN="…"
export CHANNEL_ID="@your_test_channel"
export AI_API_KEY="…"
export AI_MODEL="llama3.2"
python main.py
```

---

## 🛠 Troubleshooting

| Symptom                                            | Likely cause                                          | Fix                                                                  |
|----------------------------------------------------|-------------------------------------------------------|----------------------------------------------------------------------|
| `ModuleNotFoundError: No module named 'feedparser'`| Dependencies not installed.                           | `pip install -r requirements.txt`                                    |
| Bot posts nothing for hours                        | `posted_history.json` blocked every URL, or RSS down. | Check workflow logs; manually clear or rotate `posted_history.json`. |
| `Telegram: Bad Request: can't parse entities`      | AI emitted unescaped HTML.                            | The bot auto-retries as plain text. Check `prompt.txt` for stray `<` characters. |
| Scheduled runs paused after ~60 days               | GitHub auto-disables inactive cron jobs.              | The included `keepalive.yml` workflow pings the repo monthly.       |
| `AI timeout after 300s`                            | Model is slow or network is flaky.                    | Bump `AI_TIMEOUT`; reduce `SUMMARY_MAX_CHARS` to shorten the prompt.|

---

## 📝 License
MIT — see [`LICENSE`](./LICENSE).
