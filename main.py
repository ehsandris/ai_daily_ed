import os
import requests
import feedparser
import re
import json
import time
import traceback
from datetime import datetime, timedelta
from ollama import Client

# خواندن متغیرها
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")
HISTORY_FILE = 'posted_history.json'

NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss"
}

def notify_admin(error_text):
    """ارسال پیام خطا به ادمین"""
    if not ADMIN_CHAT_ID:
        return
    print("📧 در حال ارسال پیام خطا به ادمین...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": f"🚨 <b>خطا در ربات اخبار هوش مصنوعی</b>\n\n<code>{error_text}</code>",
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def get_posted_history():
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_posted_url(url, history_set):
    history_set.add(url)
    history_list = list(history_set)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_list, f)

def extract_url_from_text(text):
    urls = re.findall(r'(https?://[^\s]+)', text)
    return urls[-1] if urls else None

def beautify_links(text):
    """تبدیل لینک خام به لینک کلیک‌خور زیبا"""
    urls = re.findall(r'(https?://[^\s]+)', text)
    if urls:
        # آخرین لینک (لینک منبع) را به یک دکمه متنی تبدیل می‌کنیم
        last_url = urls[-1].replace(")", "")
        text = text.replace(last_url, f"[📚 منبع خبر]({last_url})")
    return text

def clean_html(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()

def is_valid_news(title):
    junk_keywords = ['podcast', 'newsletter', 'sponsored', 'giveaway', 'best of', 'deals']
    title_lower = title.lower()
    return not any(keyword in title_lower for keyword in junk_keywords)

def is_fresh_news(entry):
    pub_date_struct = entry.get('published_parsed')
    if pub_date_struct:
        pub_date = datetime.fromtimestamp(time.mktime(pub_date_struct))
        if datetime.now() - pub_date > timedelta(hours=24):
            return False
    return True

def get_latest_ai_news():
    print("در حال دریافت اخبار جدید (فقط آخرین ۲۴ ساعت)...")
    posted_urls = get_posted_history()
        
    all_news = []
    
    for source, url in NEWS_SOURCES.items():
        feed = feedparser.parse(url)
        
        for entry in feed.entries:
            if not is_fresh_news(entry):
                continue
                
            title = entry.title
            link = entry.link
            
            if link in posted_urls:
                continue
                
            if not is_valid_news(title):
                continue
                
            summary = clean_html(entry.summary)[:600] if hasattr(entry, 'summary') else "خلاصه موجود نیست"
            
            all_news.append({
                "source": source,
                "title": title,
                "link": link,
                "summary": summary
            })
            
    return all_news[:15]

def load_prompt():
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return None

def generate_engaging_post(news_list):
    print(f"در حال تحلیل {len(news_list)} خبر تازه و معتبر توسط هوش مصنوعی...")
    
    news_data = ""
    for i, news in enumerate(news_list, 1):
        news_data += f"خبر {i}:\nعنوان: {news['title']}\nخلاصه: {news['summary']}\nلینک: {news['link']}\n---\n"
    
    prompt_template = load_prompt()
    if not prompt_template:
        return None
        
    final_prompt = prompt_template.replace("{NEWS_DATA}", news_data)
    
    try:
        client = Client(
            host='https://ollama.com',
            headers={'Authorization': f'Bearer {AI_API_KEY}'}
        )
        response = client.chat(
            model=AI_MODEL,
            messages=[{'role': 'user', 'content': final_prompt}]
        )
        return response['message']['content']
        
    except Exception as e:
        print(f"❌ خطا در هوش مصنوعی: {e}")
        notify_admin(f"خطا در اتصال به هوش مصنوعی:\n{e}")
        return None

def send_to_telegram(text):
    print("در حال ارسال به تلگرام...")
    # beautify the links before sending
    beautiful_text = beautify_links(text)
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": beautiful_text,
        "parse_mode": "Markdown", # تغییر به مارک‌داون برای پشتیبانی از لینک مخفی
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            print("✅ پست حرفه‌ای با موفقیت ارسال شد!")
            return True
        else:
            print(f"❌ خطا در ارسال تلگرام: {response.text}")
            notify_admin(f"خطا در ارسال به کانال:\n{response.text}")
            return False
    except Exception as e:
        print(f"❌ خطای شبکه تلگرام: {e}")
        notify_admin(f"خطای شبکه تلگرام:\n{e}")
        return False

if __name__ == "__main__":
    try:
        news_list = get_latest_ai_news()
        if news_list:
            post_text = generate_engaging_post(news_list)
            if post_text and "SKIP" not in post_text.upper():
                if send_to_telegram(post_text):
                    posted_url = extract_url_from_text(post_text)
                    if posted_url:
                        save_posted_url(posted_url, get_posted_history())
            else:
                print("🟡 خبر مهمی یافت نشد. ربات چیزی پست نکرد.")
        else:
            print("🔴 هیچ خبر تازه‌ای در ۲۴ ساعت گذشته یافت نشد. ربات کانال را آپدیت نمی‌کند.")
            
    except Exception as e:
        # اگر هر خطای پیش‌بینی نشده‌ای در کل کد رخ داد
        error_msg = traceback.format_exc()
        print(f"❌ خطای بحرانی:\n{error_msg}")
        notify_admin(f"خطای بحرانی در اجرای ربات:\n{error_msg}")
