import os
import requests
import feedparser
import re
from ollama import Client

# خواندن متغیرها از گیت‌هاب
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")

# لیست منابع خبری معتبر
NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/"
}

def clean_html(text):
    """حذف تگ‌های HTML از خلاصه خبر"""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()

def get_latest_ai_news():
    print("در حال دریافت اخبار از منابع مختلف...")
    all_news = []
    
    for source, url in NEWS_SOURCES.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:2]: # ۲ خبر آخر هر سایت
            summary = clean_html(entry.summary)[:500]
            all_news.append({
                "source": source,
                "title": entry.title,
                "link": entry.link,
                "summary": summary
            })
            
    return all_news[:5] # ۵ خبر اول برای بررسی

def load_prompt():
    """خواندن فایل پرامپت از خارج کد"""
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        print("❌ فایل prompt.txt پیدا نشد!")
        return None

def generate_engaging_post(news_list):
    print(f"در حال تحلیل {len(news_list)} خبر توسط هوش مصنوعی...")
    
    # ساخت لیست خام اخبار
    news_data = ""
    for i, news in enumerate(news_list, 1):
        news_data += f"خبر {i}:\nعنوان: {news['title']}\nخلاصه: {news['summary']}\nلینک: {news['link']}\n---\n"
    
    # خواندن پرامپت و جایگذاری اخبار
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
        else:
            print(f"❌ خطا در ارسال تلگرام: {response.text}")
    except Exception as e:
        print(f"❌ خطای شبکه تلگرام: {e}")

if __name__ == "__main__":
    news_list = get_latest_ai_news()
    if news_list:
        post_text = generate_engaging_post(news_list)
        if post_text and "SKIP" not in post_text.upper():
            send_to_telegram(post_text)
        else:
            print("🟡 خبر مهمی یافت نشد. ربات چیزی پست نکرد تا کیفیت کانال حفظ شود.")
    else:
        print("هیچ خبری یافت نشد.")
