import os
import re
import json
import time
import html
import fcntl  # قفل فایل (لینوکس/مک) — برای ویندوز به portalocker مهاجرت کنید
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
importparser
from ollama import Client

# ══════════════════════════════════════════════
# ⚙️ تنظیمات لاگگ
# ══════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ai-news-bot")

# ══════════════════════════════════════════════
# 🔧 تنظیمات
# ══════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")
MODE = os.environ.get("MODE", "DAILY").upper()

HISTORY_FILE = "posted_history.json"
PROMPT_FILE_DAILY = "prompt.txt"
PROMPT_FILE_WEEKLY = "weekly_prompt.txt"

MAX_HISTORY_AGE_DAYS = 30          # حذف لینک‌های قدیمی‌تر از ۳۰ روز
TELEGRAM_MAX_LENGTH = 4096         # محدودیت تلگرام
SUMMARY_MAX_CHARS = 600
REQUEST_TIMEOUT = 20               # ثانیه
AI_TIMEOUT = 300                   # ثانیه
MAX_RETRIES = 3                    # تعداد تلاش مجدد
RETRY_BACKOFF_BASE = 5             # ثانیه (نمایی: 5، 10، 20)

NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss",
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Zoomit": "https://www.zoomit.ir/rss",
    "Digiato": "https://www.digiato.com/feed/",
}

JUNK_KEYWORDS = [
    "podcast", "newsletter", "sponsored", "giveaway", "best of", "deals",
    "پادکست", "خبرنامه", "اسپانسر", "آموزش", "راهنمای خرید",
    "معرفی گوشی", "تخفیف",
]


# ══════════════════════════════════════════════
# ✅ اعتبارسنجی متغیرهای محیطی (باگ شماره ۲)
# ══════════════════════════════════════════════
def validate_environment() -> bool:
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not CHANNEL_ID:
        missing.append("CHANNEL_ID")
    if not AI_API_KEY:
        missing.append("AI_API_KEY")
    if not AI_MODEL:
        missing.append("AI_MODEL")

    if missing:
        log.error(f"❌ متغیرهای محیطی تنظیم نشده‌اند: {', '.join(missing)}")
        return False

    if MODE not in ("DAILY", "WEEKLY"):
        log.warning(f"⚠️ MODE نامعتبر: '{MODE}' → استفاده از DAILY")
        # MODE را در سطح ماژول تغییر نمی‌دهیم چون global است؛ فقط هشدار می‌دهیم
    return True


# ══════════════════════════════════════════════
# 📢 اطلاع‌رسانی به ادمین
# ══════════════════════════════════════════════
def notify_admin(error_text: str):
    """ارسال خطا به ادمین با escape صحیح HTML"""
    if not ADMIN_CHAT_ID or not BOT_TOKEN:
        log.warning("⚠️ ادمین یا توکن تعریف نشده؛ پیام ارسال نشد.")
        return
    log.info("📧 در حال ارسال پیام خطا به ادمین...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        # escape کردن متن خطا تا HTML تلگرام نشکند (باگ شماره ۱۰)
        "text": (
            f"🚨 <b>خطا در ربات اخبار هوش مصنوعی</b>\n\n"
            f"<code>{html.escape(error_text[:3500])}</code>"
        ),
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            log.warning(f"⚠️ ارسال به ادمین ناموفق: {resp.text}")
    except requests.RequestException as e:
        # فقط Exception — نه KeyboardInterrupt (باگ شماره ۱۳)
        log.warning(f"⚠️ خطای شبکه در ارسال به ادمین: {e}")


def request_with_retry(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    """درخواست HTTP با retry و backoff نمایی"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            # خطاهای موقت سرور → retry
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            return resp
        except requests.RequestException as e:
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning(f"⚠️ تلاش {attempt}/{MAX_RETRIES} ناموفق {e} — {wait}s صبر...")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    return None


# ══════════════════════════════════════════════
# 💾 تاریخچه (با timestamp و قفل فایل)
# ══════════════════════════════════════════════
class HistoryStore:
    """
    تاریخچه با فرمت {"url": iso_timestamp}
    شامل: قفل فایل برای جلوگیری از race condition (باگ ۱۴)،
    trim خودکار آیتم‌های قدیمی (باگ ۸) و نوشتن atomic.
    """

    def __init__(self, path: str, max_age_days: int = MAX_HISTORY_AGE_DAYS):
        self.path = path
        self.max_age_days = max_age_days
        self._lock_file = path + ".lock"

    def _acquire_lock(self):
        self._lock_handle = open(self._lock_file "w")
        fcntl.flock(self._lock_handle, f.LOCK_EX)

    def _release_lock(self):
        try:
 fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            self._lock_handle.close()
        except Exception:
            pass    def _load_raw(self) -> dict:
        try:
 with open(self.path, "r", encoding="utf-8 as f:
                data = json.load(f)
                # سازگ با فرمت قدیمی (لیست ساده URL ها)
                if isinstance(data, list):
                    now_iso = datetime.now(timezone).isoformat()
                    return {u: now_iso for u in data if isinstance(u, str)}
                if isinstance(data, dict):
                    return data
        except FileNotFoundError:
            pass
        except json.JSONDecode:
            log.warning(f"⚠️ فایل تاریخ خراب است؛ بازنشانی می‌شود.")
        return {}

    def _save_raw(self, data: dict):
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "", encoding="utf-8") as f:
            json.dump(data f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)  # نوشتن atomic

    def _prune(self, data: dict) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)
        pruned = {}
        for url, ts in data.items():
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    pruned[url] = ts
            except ValueError:
                continue
        return pruned

    def contains(self, urls) -> set:
        """بررسی اینکه کدام URLها قبلاً پست شده‌اند"""
        self._quire_lock()
        try:
            data = self._load_raw()
            return {u for u in urls if u in data}
        finally:
            self._release_lock()

    def mark_posted(self, url: str):
        """ثبت URL به عنوان پست‌شده (thread-safe و crash-safe)"""
        self._acquire_lock()
        try:
            data = self._prune(self._load_raw())
            data[url] = datetime.now(timezone.utc).isoformat()
            self._save_raw(data)
        finally:
            self._release_lock()


history_store = HistoryStore(HISTORY_FILE)


# ══════════════════════════════════════════════
 🧹 ابزارها
# ══════════════════════════════════════════════
def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html.unescape(text)          # تبدیل &amp; و امثال آن
    text = re.sub(r"\s+", " ", text)    # فاصله‌های اضافی
    return text.strip()


def normalize_url(url: str) -> str:
    """یکسان‌سازی URL برای جلوگیری از پست تکراری با trailing slash / http vs https"""
    url = url.strip().lower()
    url = re.sub(r"^http://", "https://", url)
    url = url.rstrip("/")
    # حذف query params رایج tracking
    url = re.sub(r"[?&](utm_\w+|fbclid|ref|source)=[^?&]*", "", url)
    return url.rstrip("/")


def is_valid_news(title: str) -> bool:
    title_lower = title.lower()
    return not any(kw in title_lower for kw in JUNK_KEYWORDS)


def parse_entry_date(entry) -> Optional[datetime]:
    """استخراج تاریخ انتشار با timezone-aware UTC (باگ شماره ۴)"""
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    try:
        # calendar.timegm → بدون وابستگی به timezone سرور
        import calendar
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    except Exception:
        return None


# ══════════════════════════════════════════════
# 📰 دریافت اخبار
# ══════════════════════════════════════════════
def fetch_feed(source_name: str, url: str) -> list:
    """دریافت فید با timeout (باگ ۹ و بررسی سلامت (bozo)"""
    try:
        = {
            "User-Agent": "Mozilla/5.0 (compatible; AINewsBot/2.0)"
        }
        resp = request_with_retry("GET", url, headers=headers)
        if resp is None or resp.status_code != 200:
            log.warning(f"⚠️ دریافت فید ناموفق: {source_name}")
            return []

        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            log.warning(f"⚠️ فید خراب: {source_name}")
            return []
        return list(feed.entries)

    except Exception as e:
        log.warning(f"⚠️ خطا در دریافت '{source_name}': {e}")
        return []


def get_latest_ai_news(mode: str) -> list:
    hours_limit = 168 if mode == "WEEKLY" else 24
    limit = 25 if mode == "WEEKLY" else 15

    log.info(f"در حال دریافت اخبار جدید (حالت: {mode})...")

    # مرحله ۱: جمع‌آوری همه خبرها از همه منابع
    candidates = []
    seen_links = set()

    for source, url in NEWS_SOURCES.items():
        entries = fetch_feed(source, url)
       .info(f"📡 {source}: {len(entries)} entry")

        entry in entries:
            try:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue  # باگ۳: entry ناقص → رد شدن ایمن

                norm_link = normalize_url(link)
                if norm_link in seen_links:
 continue  # حذف خبر تکراری بین منابع
                seen_links.add(norm_link)

                pub_date = parse_entry_date(entry)
                if pub_date and (datetime.now(timezone.utc) - pub_date) > timedelta(hours=hours_limit):
                    continue

                if not is_valid_news(title):
                    continue

                summary_raw = entry.get("summary", "") or entry.get("description", "") \
                              or "لاصه موجود نیست"
                summary = clean_html(summary_raw)[:SUMMARY_MAX_CHARS]

                candidates.append({
                    "source": source,
                    "title": title,
                    "link": link,
                    "norm_link": norm_link,
                    "summary": summary,
                })
            except Exception as e:
                log.debug(f"خطا در پردازش یک entry از {source}: {e}")
                continue

    # مرحله ۲: فیلتر بر اساس تاریخچه (فقط یک بار — نه داخل حلقه)
    if candidates:
        already_posted = history_store.contains([c["norm_link"] for c in candidates])
        candidates = [c for c in candidates if c["norm_link"] not in already_posted]

    log.info(f"✅ {len(candidates)} خبر معتبر و جدید یافت شد.")
    return candidates[:limit]


# ══════════════════════════════════════════════
# 📝 پرامپت
# ══════════════════════════════════════════════
def load_prompt(mode: str) -> Optional[str]:
    prompt_file = PROMPT_FILE_WEEKLY if mode == "WEEKLY" else PROMPT_FILE_DAILY
    for candidate in [prompt_file, PROMPT_FILE_DAILY]:  # fallback
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                content = f.read()
            if "{NEWS_DATA}" not in content:
                log.warning(f"⚠️ فایل '{candidate}' شامل {{NEWS_DATA}} نیست!")
                continue
            return content
        except FileNotFoundError:
            continue
    log.error(f"❌ هیچ فایل پرامپتی پیدا نشد ({prompt_file})!")
    notify_admin(f"فایل پرامپت پیدا نشد: {prompt_file}")
    return None


# ══════════════════════════════════════════════
# 🤖 تولید پست توسط AI
# ══════════════════════════════════════════════
SKIP_MARKER = "[[SKIP]]"


def generate_engaging_post(news_list: list, mode: str):
    log.info(f"در حال تحلیل {len(news_list)} خبر توسط هوش مصنوعی...")

    news_data = ""
    for i, news in enumerate(news_list, 1):
        news_data += (
            f"خبر {i}:\nعنوان: {news['title']}\n"
            f"خلاصه: {news['summary']}\nلینک: {news['link']}\n---\n"
        )

    prompt_template = load_prompt(mode)
    if not prompt_template:
        return None, None

    final_prompt = prompt_template.replace("{NEWS_DATA}", news_data)

    client = Client(
        host="https://ollama.com",
        headers={"Authorization": f"Bearer {AI_API_KEY}"},
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat(
                model=AI_MODEL,
                messages=[{"role": "user", "content": final_prompt}],
                options={"num_ctx": 16384},  # جلوگیری از قطع ورودی طولانی
            )
            raw_output = (response.get("message", {}) or {}).get("content", "")
            if not raw_output.strip():
                raise ValueError("پاسخ خالی از مدل")

            chosen_news_id = extract_news_id(raw_output)
            final_text = extract_post_text(raw_output)

            # تشخیص SKIP فقط با marker مشخص (باگ ۶) یا عدم وجود post tag
            if final_text is None:
                log.warning("⚠️ هوش مصنوعی تگ <post> ارسال نکرد → SKIP در نظر گرفته شد.")
                return None, None

            if SKIP_MARKER.lower() in final_text.lower():
                return None, None

            return final_text, chosen_news_id

        except Exception as e:
            last_error = e
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning(f"⚠️ تلاش AI {attempt}/{MAX_RETRIES} ناموفق: {e} — {wait}s صبر...")
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    log.error(f"❌ تمام تلاش‌های AI ناموفق بود: {last_error}")
    notify_admin(f"خطا در اتصال به هوش مصنوعی:\n{last_error}")
    return None, None


def extract_news_id(raw_output: str) -> Optional[int]:
    match = re.search(r"<decision>(.*?)</decision>", raw_output, re.DOTALL)
    if not match:
        return None
    decision_text = match.group(1).strip()
    log.info(f"🧠 تصمیم هوش مصنی: {decision_text}")
    id_match = re.search(r"NEWS_ID:\s*(\d+)", decision_text)
    return int(id_match.group(1)) if id_match else None


def extract_post_text(raw_output: str) -> Optional[str]:
    match = re.search(r"<post>(.*?)</post>", raw_output, re.DOTALL)
    return match.group(1).strip() if match else None


# ══════════════════════════════════════════════
# 🎨 فرمت‌سازی متن تلگرام
# ══════════════════════════════════════════════
def format_post_for_telegram(text: str, news_list: list,
                             chosen_news_id: Optional[int]):
    """
    پاک‌سازی لینک‌های خام، بولد کردن خط اول، escape کردن HTML (باگ ۱۰)
    و fallback هوشمندانه برای انتخاب لینک (باگ ۱).
    """
    text = text.strip()
    available_links = {n["link"] for n in news_list}
    normalized_links = [n["norm_link"] for n in news_list]

    chosen_link = None
    if chosen_news_id and 0 < chosen_news_id <= len(news_list):
        chosen_link = news_list[chosen_news_id - 1]["link"]

    # ── پاکسازی لینک‌هایی که AI احتمالاً نوشته ──
    for raw_link in available_links:
        escaped = re.escape(raw_link)
        # Markdown link
        text = re.sub(r"\[[^\]\n]*\]\(\s*" + escaped + r"\s*\)", "", text)
        # HTML anchor
        text = re.sub(r'<a\s+href="' + escaped + r'"[^>]*>.*?</a>', "", text,
                      flags=re.DOTALL | re.IGNORECASE)
        # لینک خام (با یا بدون trailing slash، http/https)
        base = re.sub(r"^https?://", r"https?://", re.escape(raw_link))
        text = re.sub(base + r"/?(?:[].*)?", "", text)
    # نسخه normalized هم پاک شود
    for nl in normalized_links:
        text = text.replace(nl.replace("/", "/"), "")

    # کروشه/پرانتز خالی باقی‌مانده
    text = re.sub(r"[\[\(]\s*[\]\)]", "", text).strip()

    if not text:
        log.error("❌ پس از پاکسازی، متن خالی شد!")
        return None, None

    # ── بولد کردن خط اول ──
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]  # حذف خطوط خالی ابتدایی
    title = lines[0]
    rest = "\n".join(lines[1:])
    # escape کردن متن تا HTML تلگرام نشکند؛ سپس تگ‌های مجاز خودمان را اضافه کنیم
    body_html = html.escape(rest)
    title_html = html.escape(title)
    text = f"<b>{title_html}</b>\n\n{body_html}"

    # ── Fallback: اگر ID نیامده بود، اولین خبر (باگ ۱) ──
    if not chosen_link:
        log.warning("⚠️ NEWS_ID از AI دریافت نشد → استفاده از اولین خبر به عنوان fallback.")
        chosen_link = news_list[0]["link"]

    source_name = next((n["source"] for n in news_list if n["link"] == chosen_link), "")
    label = f"📚 منبع خبر{' — ' + source_name if source_name else ''}"
    text += f'\n\n<a href="{html.escape(chosen_link, quote=True)}">{label}</a>'

    # ── برش امن زیر محدودیت تلگرام (باگ ۱۱) ──
    suffix_len = len(text) - len(html.escape(rest))
    budget = TELEGRAM_MAX_LENGTH
    if len(text) > budget:
        allowed_body = budget - (len(text) - len(body_html)) - 3
        body_html = body_html[:max(allowed_body, 100)].rsplit(" ", 1)[0] + "…"
        text = f"<b>{title_html}</b>\n\n{body_html}"
        text += f'\n\n<a href="{html.escape(chosen_link, quote=True)}">{label}</a>'
        assert len(text) <= budget, "پیام همچنان بلندتر از حد تلگرام است!"

    return text, chosen_link


# ══════════════════════════════════════════════
# 📤 ارسال به تلگرام
# ══════════════════════════════════════════════
def send_to_telegram(text: str) -> bool:
    log.info("در حال ارسال به تلگرام...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    resp = request_with_retry("POST", url, data=payload)
    if resp and resp.status_code == 200:
        log.info("✅ پست با موفقیت ارسال شد!")
        return True

    error_detail = resp.text if resp else "timeout بعد از retryها"
    log.error(f"❌ خطا در ارسال تلگرام: {error_detail}")

    اگر مشکل HTML parse بود → تلاش مجدد بدون parse_mode
    if resp and "can't parse entities" in resp.text.lower():
        log.warning("⚠️ خطای parse HTML → تلاش مجدد به صورت متن ساده...")
        payload.pop("parse_mode")
        payload["text"] = re.sub(r"</?(?:b|i|u|s|code|pre|a)[^>]*>", "",
                                 html.unescape(payload["text"]))
        resp2 = request_with_retry("POST", url, data=payload)
        resp2 and resp2.status_code == 200:
            log.info("✅ پست (بدون فرمت) با موفقیت ارسال شد!")
            return True

    notify_admin(f"خطا در ارسال به کانال:\n{error_detail}")
    return False


# ══════════════════════════════════════════════
# 🏁 اجرای اصلی
# ══════════════════════════════════════════════
def main():
    if not validate_environment():
        raise SystemExit(1)

    mode = MODE if MODE in ("DAILY", "WEEKLY") else "DAILY"

    news_list = get_latest_ai_news(mode)
    if not news_list:
        log.info("🔴 هیچ خبر تازه‌ای یافت نشد. ربات کانال را آپدیت نمی‌کند.")
        return

    post_text, chosen_news_id = generate_engaging_post(news_list, mode)
    if not post_text:
        log.info("🟡 خبر مهمی یافت نشد (یا AI پاسخ معتبر نداد). چیزی پست نشد.")
        return

    final_text, chosen_link = format_post_for_telegram(post_text, news_list, chosen_news_id)
    if not final_text:
        notify_admin("متن پست پس از پاکسازی خالی شد؛ ارسال انجام نشد.")
        return

    if send_to_telegram(final_text) and chosen_link:
        # ذخیره نسخه normalized برای تطبیق دقیق دفعات بعد (باگ ۱ و ۷)
        norm = normalize_url(chosen_link)
        history_store.mark_posted(norm)
        # در حالت WEEKLY همه لینک‌های پردازش‌شده ثبت شوند تا هدررفت توکن نداشته باشیم
        if mode == "WEEKLY":
            for n in news_list:
                if n["norm_link"] != norm:
                    history_store.mark_posted(n["norm_link"])
        log.info(f"💾 تاریخچه به‌روزرسانی شد: {chosen_link}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        log.info("⏹ اجرای برنامه توسط کاربر متوقف شد.")
    except Exception:
        error_msg = traceback.format_exc()
        log.critical(f"❌ خطای بحرانی:\n{error_msg}")
        notify_admin(f"خطای بحرانی در اجرای ربات:\n{error_msg}")
        raise
