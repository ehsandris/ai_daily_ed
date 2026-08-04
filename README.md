
# 🤖 AI News Bot (Serverless Telegram Bot & AI Editor)

An automated, serverless bot that acts as a senior tech news editor. It aggregates the latest AI news from top global and local sources, filters out the noise, and uses a Large Language Model (LLM) to rewrite the most important news in a natural, engaging, and analytical tone before posting it to a Telegram channel.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/Automated-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot_API-26A5E4?logo=telegram&logoColor=white)
![Ollama](https://img.shields.io/badge/AI-Ollama_Cloud-000000?logo=ollama&logoColor=white)

---

## ✨ Key Features

- **⚙️ 100% Serverless Architecture:** No dedicated servers, VPS, or hosting costs required. All processes run on GitHub Actions' free tier, completely bypassing regional network restrictions (like Telegram filtering in Iran).
- **🧠 AI Quality Gate:** The bot doesn't just copy-paste! The AI evaluates the importance of the news. If an article is trivial or low-value, it vetoes the post (`SKIP`) to maintain the channel's high quality.
- **🎭 Dynamic Style Injection:** To prevent robotic and repetitive formatting, the AI dynamically determines the best writing angle for each news item (e.g., analytical, provocative question, short punchy, direct journalistic) based on the news context.
- **🛡️ Stateful Memory (Deduplication):** Using GitHub Cache and automated commits, the bot remembers previously posted URLs and ensures no news is ever posted twice.
- **🌐 Multi-Source Aggregation:** Simultaneously monitors 8 top-tier global and local RSS feeds (TechCrunch, The Verge, Wired, MIT Tech Review, Hugging Face, Zoomit, Digiato).
- **📰 Automated Weekly Bulletin:** In addition to real-time news, it generates a magazine-style weekly summary, ranking the top 5-7 news stories of the week by importance, complete with deep analysis.
- **🚨 Admin Alert System:** If a critical error occurs (e.g., API downtime or Telegram errors), the bot instantly sends a detailed error log to the admin's Telegram account.

---

## 🧠 Architecture & Workflow

This bot follows an Event-Driven architecture:

1. **Cron Job:** A scheduled trigger in GitHub Actions (every 30 minutes or weekly) wakes up the Python script.
2. **Aggregation:** RSS feeds are parsed. News older than 24 hours and titles containing "junk" keywords are filtered out.
3. **Deduplication:** Previously posted URLs (stored in `posted_history.json`) are removed from the list.
4. **AI Processing (Ollama):** The curated list is sent to the LLM. The model selects the single most important news, decides on the best writing style, and generates the post inside `<decision>` and `<post>` tags.
5. **Post-Processing (Python):** The Python script parses the AI's decision, formats the text to HTML, bolds the title, and injects a clickable source link at the bottom.
6. **Delivery & Memory:** The final post is sent via the Telegram Bot API, and the new URL is committed back to the repository's memory file.

---

## 🚀 Setup & Installation

To deploy this system for yourself, follow these steps:

### 1. Prerequisites
- A GitHub account.
- A Telegram Bot created via `@BotFather` (with its API Token).
- A Telegram Channel where the bot is an Administrator.
- An API Key from an AI provider (e.g., Ollama Cloud, OpenRouter, or Groq).

### 2. Environment Variables (GitHub Secrets)
In your GitHub repository, navigate to `Settings > Secrets and variables > Actions` and add the following:
- `BOT_TOKEN`: Your Telegram Bot token.
- `CHANNEL_ID`: Your Telegram Channel ID (e.g., `@my_ai_channel`).
- `ADMIN_CHAT_ID`: Your personal numeric Telegram ID for error alerts.
- `AI_API_KEY`: Your AI provider API key.
- `AI_MODEL`: The model name to use (e.g., `llama3.2` or `gemma2`).

### 3. Project Files
Upload the Python script (`main.py`), the prompt files (`prompt.txt` and `weekly_prompt.txt`), and the workflow YAML files (inside the `.github/workflows/` directory) to your repository.

---

## 📁 Project Structure

```text
.
├── main.py                  # Core logic and processing engine
├── prompt.txt               # Advanced XML prompt for daily news
├── weekly_prompt.txt        # Prompt for generating the weekly magazine bulletin
├── posted_history.json      # JSON database for posted URLs (Auto-generated)
└── .github/
    └── workflows/
        ├── bot.yml          # Workflow: Runs the daily bot every 30 minutes
        └── weekly.yml       # Workflow: Runs the weekly bulletin every Friday
```

---

## 🛠️ Tech Stack

- **Backend & Scheduling:** GitHub Actions, Python 3.11
- **AI Engine:** Ollama Cloud API / OpenAI-standard APIs
- **News Parsing:** Feedparser
- **Messaging:** Telegram Bot API
- **Prompt Engineering:** Advanced XML structuring, Dynamic Routing, Few-Shot Decision Making.

---

## 📝 License
This project is open-source and available under the MIT License. Feel free to use, modify, and distribute it.

---

> **Maintenance Note:** To keep GitHub Actions automated schedules active, make a minor commit (e.g., add a comment) to the repository every 50-60 days, so GitHub doesn't pause the scheduled workflows due to inactivity.
```
