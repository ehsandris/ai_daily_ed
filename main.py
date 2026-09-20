"""
AI News Bot — Serverless Telegram Bot & AI Editor.

Aggregates AI news from multiple RSS sources, filters and deduplicates them,
delegates editorial selection + rewriting to an LLM (Ollama Cloud by default),
then publishes to a Telegram channel. Designed to run on GitHub Actions.

Refactor notes (vs. previous version):
  * Real syntax/import errors in HistoryStore and fetch_feed fixed
  * Cross-platform file locking via portalocker (with fcntl fallback)
  * Length limits enforced in the AI prompt to stay under Telegram's 4096 cap
  * Defensive parsing of the AI response
  * Configurable Ollama host (env AI_HOST)
  * Optional AI_TIMEOUT honored in the Ollama client call
  * Hardened Telegram retry + plain-text fallback
  * Proper tz handling throughout
  * history_store.mark_posted now takes the canonical (normalized) URL
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import feedparser
import requests
from ollama import Client

# ──────────────────────────────────────────────────────────────────────────
# Cross-platform file locking
# ──────────────────────────────────────────────────────────────────────────
try:
    import fcntl  # type: ignore[import-not-found]  # POSIX only

    def _lock_exclusive(fd) -> None:  # noqa: ANN001
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _lock_release(fd) -> None:  # noqa: ANN001
        fcntl.flock(fd, fcntl.LOCK_UN)

    _LOCK_BACKEND = "fcntl"
except ImportError:  # pragma: no cover - Windows fallback
    try:
        import portalocker  # type: ignore[import-not-found]
        from portalocker import LockFlags  # type: ignore[import-not-found]

        # portalocker 3.x takes a filename (or path-like), opens it internally,
        # and exposes acquire/release on the Lock object itself. We keep a
        # registry of Lock objects keyed by lock path so _lock_release can find
        # the right one to release without exposing the fd lifetime.
        _PORTALOCKER_LOCKS: dict = {}

        def _lock_exclusive(fd) -> None:  # noqa: ANN001
            # The fd is bound to <path>.lock; recover the path so portalocker
            # can open it itself in binary mode (which it requires).
            path = getattr(fd, "name", None)
            if path is None:
                return
            lock = portalocker.Lock(
                path,
                mode="a",
                flags=LockFlags.EXCLUSIVE,
            )
            lock.acquire()
            _PORTALOCKER_LOCKS[path] = lock
            # The fd we received from open(..., 'a+') is now superseded by
            # portalocker's own handle. Close it so we don't leak.
            try:
                fd.close()
            except Exception:  # noqa: BLE001
                pass

        def _lock_release(fd) -> None:  # noqa: ANN001
            path = getattr(fd, "name", None)
            if path is None:
                return
            lock = _PORTALOCKER_LOCKS.pop(path, None)
            if lock is not None:
                lock.release()

        _LOCK_BACKEND = "portalocker"
    except ImportError:  # last-resort no-op (single-process runners only)
        def _lock_exclusive(fd) -> None:  # noqa: ANN001
            return None

        def _lock_release(fd) -> None:  # noqa: ANN001
            return None

        _LOCK_BACKEND = "none"

# ──────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ai-news-bot")
log.info(f"File-lock backend: {_LOCK_BACKEND}")

# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")
AI_HOST = os.environ.get("AI_HOST", "https://ollama.com")
MODE = os.environ.get("MODE", "DAILY").upper()

HISTORY_FILE = os.environ.get("HISTORY_FILE", "posted_history.json")
PROMPT_FILE_DAILY = "prompt.txt"
PROMPT_FILE_WEEKLY = "weekly_prompt.txt"

MAX_HISTORY_AGE_DAYS = int(os.environ.get("MAX_HISTORY_AGE_DAYS", "30"))
TELEGRAM_MAX_LENGTH = 4096
SUMMARY_MAX_CHARS = int(os.environ.get("SUMMARY_MAX_CHARS", "600"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", "300"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = int(os.environ.get("RETRY_BACKOFF_BASE", "5"))

NEWS_SOURCES: dict[str, str] = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss",
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Zoomit": "https://www.zoomit.ir/rss",
    "Digiato": "https://www.digiato.com/feed/",
}

JUNK_KEYWORDS: tuple[str, ...] = (
    "podcast", "newsletter", "sponsored", "giveaway", "best of", "deals",
    "پادکست", "خبرنامه", "اسپانسر", "آموزش", "راهنمای خرید",
    "معرفی گوشی", "تخفیف",
)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; AINewsBot/2.0)"

# Maximum length the LLM should generate for the Persian post body. We keep
# this comfortably below TELEGRAM_MAX_LENGTH so the formatted wrapper, the
# "منبع" link and any escaping stay inside Telegram's limit.
AI_POST_MAX_CHARS = 3500


# ──────────────────────────────────────────────────────────────────────────
# Environment validation
# ──────────────────────────────────────────────────────────────────────────
def validate_environment() -> bool:
    missing: list[str] = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not CHANNEL_ID:
        missing.append("CHANNEL_ID")
    if not AI_API_KEY:
        missing.append("AI_API_KEY")
    if not AI_MODEL:
        missing.append("AI_MODEL")

    if missing:
        log.error(f"❌ Environment variables not set: {', '.join(missing)}")
        return False

    if MODE not in ("DAILY", "WEEKLY"):
        log.warning(f"⚠️ Invalid MODE '{MODE}' → falling back to DAILY")
    return True


# ──────────────────────────────────────────────────────────────────────────
# Admin notifications
# ──────────────────────────────────────────────────────────────────────────
def notify_admin(error_text: str) -> None:
    """Send a critical error to the admin's Telegram DM."""
    if not ADMIN_CHAT_ID or not BOT_TOKEN:
        log.warning("⚠️ Admin/Token not configured; skipping admin alert.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": (
            "🚨 <b>خطا در ربات اخبار هوش مصنوعی</b>\n\n"
            f"<code>{html.escape(error_text[:3500])}</code>"
        ),
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            log.warning(f"⚠️ Admin notify failed: {resp.text[:200]}")
    except requests.RequestException as exc:  # noqa: BLE001
        log.warning(f"⚠️ Network error while notifying admin: {exc}")


# ──────────────────────────────────────────────────────────────────────────
# HTTP helper with exponential backoff
# ──────────────────────────────────────────────────────────────────────────
def request_with_retry(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            return resp
        except requests.RequestException as exc:  # noqa: BLE001
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning(
                f"⚠️ {method} {url} attempt {attempt}/{MAX_RETRIES} failed: {exc} — sleeping {wait}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    return None


# ──────────────────────────────────────────────────────────────────────────
# History store (thread-safe, crash-safe, cross-platform)
# ──────────────────────────────────────────────────────────────────────────
class HistoryStore:
    """Persistent set of normalized URLs with ISO timestamps.

    Format on disk: ``{"https://example.com/x": "2026-08-26T09:16:24+00:00", ...}``.
    Old format (flat list of URLs) is auto-migrated on read.
    """

    def __init__(self, path: str, max_age_days: int = MAX_HISTORY_AGE_DAYS) -> None:
        self.path = path
        self.max_age_days = max_age_days
        self._lock_path = path + ".lock"
        self._lock_handle = None  # type: ignore[var-annotated]

    # -- locking ---------------------------------------------------------
    def _acquire_lock(self) -> None:
        # Open in append mode so we never truncate an existing lock file.
        self._lock_handle = open(self._lock_path, "a+")
        _lock_exclusive(self._lock_handle)

    def _release_lock(self) -> None:
        if self._lock_handle is None:
            return
        try:
            _lock_release(self._lock_handle)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"⚠️ Could not release lock: {exc}")
        finally:
            try:
                self._lock_handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._lock_handle = None

    def close(self) -> None:
        """Explicit cleanup — releases the lock if still held."""
        self._release_lock()
    # -- persistence -----------------------------------------------------
    def _load_raw(self) -> tuple[dict[str, str], bool]:
        """Load the on-disk history. Returns (data, was_migrated).

        `was_migrated` is True when the legacy list format was upgraded to
        the new dict format in-memory — callers should persist the change.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except FileNotFoundError:
            return {}, False
        except json.JSONDecodeError:
            log.warning("⚠️ History file is corrupt; resetting.")
            return {}, False

        if isinstance(data, list):
            now_iso = datetime.now(timezone.utc).isoformat()
            return (
                {u: now_iso for u in data if isinstance(u, str)},
                True,
            )
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(k, str)}, False
        return {}, False

    def _save_raw(self, data: dict[str, str]) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)  # atomic on POSIX & Windows

    def _prune(self, data: dict[str, str]) -> dict[str, str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)
        pruned: dict[str, str] = {}
        for url, ts in data.items():
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    pruned[url] = ts
            except (TypeError, ValueError):
                # Drop un-parseable entries silently.
                continue
        return pruned

    def _persist(self, data: dict[str, str]) -> None:
        """Write atomically with the lock held."""
        self._save_raw(data)

    # -- public API ------------------------------------------------------
    def contains(self, urls: Iterable[str]) -> set[str]:
        self._acquire_lock()
        try:
            data, migrated = self._load_raw()
            if migrated:
                # Persist the migration so future reads don't re-do the work.
                self._persist(data)
            return {u for u in urls if u in data}
        finally:
            self._release_lock()

    def mark_posted(self, url: str) -> None:
        self._acquire_lock()
        try:
            data, _migrated = self._load_raw()
            data = self._prune(data)
            data[url] = datetime.now(timezone.utc).isoformat()
            self._save_raw(data)
        finally:
            self._release_lock()


history_store = HistoryStore(HISTORY_FILE)


# ──────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────
def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    """Canonical URL: lowercase host and path, https, no trailing slash,
    no common tracker query params.
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    # Hostnames are case-insensitive; we lowercase the path too because the
    # RSS sources we aggregate from are case-insensitive in practice, and a
    # mismatched case would cause false-negative deduplication.
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/").lower() or parts.path.lower()

    # Filter out common trackers from query string.
    TRACKERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                "utm_content", "fbclid", "ref", "source"}
    if parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        kept = [(k, v) for (k, v) in pairs if k.lower() not in TRACKERS]
        query = urlencode(kept, doseq=True)
    else:
        query = ""

    return urlunsplit((scheme, netloc, path, query, "")).rstrip("/")


def is_valid_news(title: str) -> bool:
    title_lower = title.lower()
    return not any(kw in title_lower for kw in JUNK_KEYWORDS)


def parse_entry_date(entry) -> Optional[datetime]:
    """Return timezone-aware UTC datetime from a feedparser entry, or None."""
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    try:
        import calendar
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


# ──────────────────────────────────────────────────────────────────────────
# Feed ingestion
# ──────────────────────────────────────────────────────────────────────────
def fetch_feed(source_name: str, url: str) -> list:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    try:
        resp = request_with_retry("GET", url, headers=headers)
        if resp is None or resp.status_code != 200:
            log.warning(f"⚠️ Failed to fetch feed: {source_name} (status={resp.status_code if resp else 'None'})")
            return []
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            log.warning(f"⚠️ Malformed feed: {source_name} ({feed.bozo_exception})")
            return []
        return list(feed.entries)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"⚠️ Error fetching '{source_name}': {exc}")
        return []


def get_latest_ai_news(mode: str) -> list[dict]:
    hours_limit = 168 if mode == "WEEKLY" else 24
    limit = 25 if mode == "WEEKLY" else 15

    log.info(f"Fetching news (mode={mode}, hours_limit={hours_limit}, limit={limit})…")

    candidates: list[dict] = []
    seen_links: set[str] = set()

    for source, url in NEWS_SOURCES.items():
        entries = fetch_feed(source, url)
        log.info(f"📡 {source}: {len(entries)} entries")

        for entry in entries:
            try:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue

                norm_link = normalize_url(link)
                if norm_link in seen_links:
                    continue
                seen_links.add(norm_link)

                pub_date = parse_entry_date(entry)
                if pub_date and (datetime.now(timezone.utc) - pub_date) > timedelta(hours=hours_limit):
                    continue

                if not is_valid_news(title):
                    continue

                summary_raw = (
                    entry.get("summary")
                    or entry.get("description")
                    or "خلاصه موجود نیست"
                )
                summary = clean_html(summary_raw)[:SUMMARY_MAX_CHARS]

                candidates.append({
                    "source": source,
                    "title": title,
                    "link": link,
                    "norm_link": norm_link,
                    "summary": summary,
                })
            except Exception as exc:  # noqa: BLE001
                log.debug(f"Error processing entry from {source}: {exc}")
                continue

    # Filter against history in one shot (not inside the loop).
    if candidates:
        already_posted = history_store.contains([c["norm_link"] for c in candidates])
        candidates = [c for c in candidates if c["norm_link"] not in already_posted]

    log.info(f"✅ {len(candidates)} fresh, valid candidates.")
    return candidates[:limit]


# ──────────────────────────────────────────────────────────────────────────
# Prompt loading
# ──────────────────────────────────────────────────────────────────────────
def load_prompt(mode: str) -> Optional[str]:
    prompt_file = PROMPT_FILE_WEEKLY if mode == "WEEKLY" else PROMPT_FILE_DAILY
    for candidate in (prompt_file, PROMPT_FILE_DAILY):  # daily as fallback
        try:
            with open(candidate, "r", encoding="utf-8") as fp:
                content = fp.read()
        except FileNotFoundError:
            continue
        if "{NEWS_DATA}" not in content:
            log.warning(f"⚠️ '{candidate}' does not contain {{NEWS_DATA}}; skipping.")
            continue
        return content
    log.error(f"❌ No usable prompt file found (tried '{prompt_file}').")
    notify_admin(f"Prompt file not found: {prompt_file}")
    return None


# ──────────────────────────────────────────────────────────────────────────
# AI post generation
# ──────────────────────────────────────────────────────────────────────────
SKIP_MARKER = "[[SKIP]]"


def _format_news_for_prompt(news_list: list[dict]) -> str:
    parts: list[str] = []
    for i, news in enumerate(news_list, 1):
        parts.append(
            f"خبر {i}:\n"
            f"عنوان: {news['title']}\n"
            f"خلاصه: {news['summary']}\n"
            f"لینک: {news['link']}\n"
            f"---"
        )
    return "\n".join(parts)


def generate_engaging_post(news_list: list[dict], mode: str) -> tuple[Optional[str], Optional[int]]:
    log.info(f"Asking AI to analyze {len(news_list)} items…")

    news_data = _format_news_for_prompt(news_list)
    prompt_template = load_prompt(mode)
    if not prompt_template:
        return None, None

    final_prompt = prompt_template.replace("{NEWS_DATA}", news_data)

    client = Client(
        host=AI_HOST,
        headers={"Authorization": f"Bearer {AI_API_KEY}"},
        timeout=AI_TIMEOUT,
    )

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat(
                model=AI_MODEL,
                messages=[{"role": "user", "content": final_prompt}],
                options={"num_ctx": 16384},
            )
            raw_output = (response.get("message", {}) or {}).get("content", "") or ""
            if not raw_output.strip():
                raise ValueError("Empty model response")

            chosen_news_id = extract_news_id(raw_output)
            final_text = extract_post_text(raw_output)

            if final_text is None:
                log.warning("⚠️ No <post> tag from AI → SKIP.")
                return None, None
            if SKIP_MARKER.lower() in final_text.lower():
                return None, None

            # Belt-and-suspenders: cap the post length so we never trip
            # Telegram's 4096 char limit even after escaping.
            if len(final_text) > AI_POST_MAX_CHARS:
                log.warning(f"⚠️ AI post too long ({len(final_text)} chars), truncating.")
                final_text = final_text[:AI_POST_MAX_CHARS].rsplit(" ", 1)[0] + "…"

            return final_text, chosen_news_id

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning(f"⚠️ AI attempt {attempt}/{MAX_RETRIES} failed: {exc} — sleeping {wait}s")
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    log.error(f"❌ All AI attempts failed: {last_error}")
    notify_admin(f"AI error:\n{last_error}")
    return None, None


def extract_news_id(raw_output: str) -> Optional[int]:
    match = re.search(r"<decision>(.*?)</decision>", raw_output, re.DOTALL)
    if not match:
        return None
    decision_text = match.group(1).strip()
    log.info(f"🧠 AI decision: {decision_text}")
    id_match = re.search(r"NEWS_ID:\s*(\d+)", decision_text)
    return int(id_match.group(1)) if id_match else None


def extract_post_text(raw_output: str) -> Optional[str]:
    match = re.search(r"<post>(.*?)</post>", raw_output, re.DOTALL)
    return match.group(1).strip() if match else None


# ──────────────────────────────────────────────────────────────────────────
# Telegram formatting
# ──────────────────────────────────────────────────────────────────────────
def _strip_links_from_text(text: str, raw_links: Iterable[str]) -> str:
    """Remove any leftover URL or markdown/HTML link forms from the AI text."""
    for raw_link in raw_links:
        if not raw_link:
            continue
        escaped = re.escape(raw_link)
        # Markdown link [text](url)
        text = re.sub(rf"\[[^\]\n]*\]\(\s*{escaped}\s*\)", "", text)
        # HTML anchor <a href="url"…>x</a>
        text = re.sub(
            rf'<a\s+href="{escaped}"[^>]*>.*?</a>',
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Bare URL (with optional trailing punctuation)
        text = re.sub(rf"{escaped}/?(\b|[)\]]*)?", "", text)
    return text


def format_post_for_telegram(
    text: str,
    news_list: list[dict],
    chosen_news_id: Optional[int],
) -> tuple[Optional[str], Optional[str]]:
    text = text.strip()
    available_links = [n["link"] for n in news_list]
    normalized_links = [n["norm_link"] for n in news_list]

    chosen_link: Optional[str] = None
    if chosen_news_id is not None and 0 < chosen_news_id <= len(news_list):
        chosen_link = news_list[chosen_news_id - 1]["link"]

    text = _strip_links_from_text(text, available_links)
    # Strip normalized variants too (model may have echoed the lowercase form).
    text = _strip_links_from_text(text, normalized_links)
    # Clean up empty brackets/parens left behind.
    text = re.sub(r"[\[\(]\s*[\]\)]", "", text).strip()

    if not text:
        log.error("❌ Text became empty after link cleanup.")
        return None, None

    # Bold the first line as the title.
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    title = lines[0]
    rest = "\n".join(lines[1:])
    body_html = html.escape(rest)
    title_html = html.escape(title)
    text = f"<b>{title_html}</b>\n\n{body_html}"

    # Fallback: if no NEWS_ID arrived, attach the first available link.
    if not chosen_link:
        log.warning("⚠️ No NEWS_ID from AI → using first candidate as fallback.")
        chosen_link = news_list[0]["link"]

    source_name = next(
        (n["source"] for n in news_list if n["link"] == chosen_link),
        "",
    )
    label = f"📚 منبع خبر{' — ' + source_name if source_name else ''}"
    text += f'\n\n<a href="{html.escape(chosen_link, quote=True)}">{label}</a>'

    # Defensive truncation under Telegram's 4096 char cap.
    if len(text) > TELEGRAM_MAX_LENGTH:
        overflow = len(text) - TELEGRAM_MAX_LENGTH + 1  # +1 for the ellipsis
        body_html = body_html[: max(len(body_html) - overflow, 100)].rsplit(" ", 1)[0] + "…"
        text = f"<b>{title_html}</b>\n\n{body_html}"
        text += f'\n\n<a href="{html.escape(chosen_link, quote=True)}">{label}</a>'
        # Last-resort hard truncate.
        if len(text) > TELEGRAM_MAX_LENGTH:
            text = text[: TELEGRAM_MAX_LENGTH - 1] + "…"

    return text, chosen_link


# ──────────────────────────────────────────────────────────────────────────
# Telegram delivery
# ──────────────────────────────────────────────────────────────────────────
def send_to_telegram(text: str) -> bool:
    log.info("Sending to Telegram…")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    resp = request_with_retry("POST", url, data=payload)
    if resp and resp.status_code == 200:
        log.info("✅ Posted successfully.")
        return True

    error_detail = resp.text if resp else "timeout after retries"
    log.error(f"❌ Telegram send failed: {error_detail}")

    # HTML parse failure → retry as plain text.
    if resp and "can't parse entities" in resp.text.lower():
        log.warning("⚠️ HTML parse error → retrying as plain text…")
        payload.pop("parse_mode", None)
        payload["text"] = re.sub(
            r"</?(?:b|i|u|s|code|pre|a)[^>]*>",
            "",
            html.unescape(payload["text"]),
        )
        resp2 = request_with_retry("POST", url, data=payload)
        if resp2 and resp2.status_code == 200:
            log.info("✅ Posted successfully (plain-text fallback).")
            return True

    notify_admin(f"Telegram send failed:\n{error_detail}")
    return False


# ──────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────
def main() -> int:
    if not validate_environment():
        return 1

    mode = MODE if MODE in ("DAILY", "WEEKLY") else "DAILY"

    news_list = get_latest_ai_news(mode)
    if not news_list:
        log.info("🔴 No fresh news — channel will not be updated.")
        return 0

    post_text, chosen_news_id = generate_engaging_post(news_list, mode)
    if not post_text:
        log.info("🟡 No important news (or AI returned no valid post). Skipping.")
        return 0

    final_text, chosen_link = format_post_for_telegram(post_text, news_list, chosen_news_id)
    if not final_text:
        notify_admin("Post text became empty after formatting; skipped.")
        return 1

    if send_to_telegram(final_text) and chosen_link:
        norm = normalize_url(chosen_link)
        history_store.mark_posted(norm)
        # In WEEKLY mode, mark all candidates as posted to avoid wasting tokens
        # on the same news items next cycle.
        if mode == "WEEKLY":
            for n in news_list:
                if n["norm_link"] != norm:
                    history_store.mark_posted(n["norm_link"])
        log.info(f"💾 History updated for: {chosen_link}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("⏹ Interrupted by user.")
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        error_msg = traceback.format_exc()
        log.critical(f"❌ Critical error:\n{error_msg}")
        notify_admin(f"Critical error in bot run:\n{error_msg}")
        sys.exit(2)
