import os
import requests
import feedparser
import re
import json
from ollama import Client

# خواندن متغیرها
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")
HISTORY_FILE = 'posted_history.json'

NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss"
}

def get_posted_history():
    """خواندن لیست ۱۰ خبر آخر پست شده"""
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_posted_url(url, history_set):
    """ذخیره لینک جدید در حافظه دائمی"""
    history_set.add(url)
    history_list = list(history_set) # نگه داشتن تمام اخبار تاریخچه
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_list, f)
    print(f"💾 لینک در حافظه ذخیره شد. تعداد کل اخبار ذخیره شده: {len(history_list)}")

def extract_url_from_text(text):
    urls = re.findall(r'(https?://[^\s]+)', text)
    return urls[-1] if urls else None

def clean_html(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()

def is_valid_news(title):
    junk_keywords = ['podcast', 'newsletter', 'sponsored', 'giveaway', 'best of', 'deals']
    title_lower = title.lower()
    return not any(keyword in title_lower for keyword in junk_keywords)

def get_latest_ai_news():
    print("در حال دریافت اخبار...")
    posted_urls = get_posted_history()
    if posted_urls:
        print(f"🧠 حافظه ربات: {len(posted_urls)} خبر قبلی به خاطر سپرده شده است.")
        
    all_news = []
    
    for source, url in NEWS_SOURCES.items():
        feed = feedparser.parse(url)
        valid_count = 0
        
        for entry in feed.entries:
            if valid_count >= 3:
                break
                
            title = entry.title
            link = entry.link
            
            # فیلتر کردن اخبار تکراری (بررسی در لیست ۱۰ تایی)
            if link in posted_urls:
                print(f"⏩ خبر تکراری رد شد: {title}")
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
            valid_count += 1
            
    return all_news[:10]

def load_prompt():
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        print("❌ فایل prompt.txt پیدا نشد!")
        return None

def generate_engaging_post(news_list):
    print(f"در حال تحلیل {len(news_list)} خبر معتبر توسط هوش مصنوعی...")
    
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
        return None

def send_to_telegram(text):
    print("در حال ارسال به تلگرام...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            print("✅ پست حرفه‌ای با موفقیت ارسال شد!")
            return True
        else:
            print(f"❌ خطا در ارسال تلگرام: {response.text}")
            return False
    except Exception as e:
        print(f"❌ خطای شبکه تلگرام: {e}")
        return False

if __name__ == "__main__":
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
        print("🔴 هیچ خبر جدیدی یافت نشد (همه تکراری هستند). ربات کانال رو آپدیت نمی‌کنه.")
