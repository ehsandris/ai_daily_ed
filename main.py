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
CACHE_FILE = 'last_post.txt'

# لیست منابع خبری
NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss"
}

def get_last_posted_url():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            url = f.read().strip()
            print(f"🔍 لینک خوانده شده از حافظه: {url}")
            return url
    except FileNotFoundError:
        print("🔍 حافظه‌ای یافت نشد (اولین اجرا).")
        return None

def save_last_posted_url(url):
    print(f"💾 در حال ذخیره لینک در حافظه: {url}")
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        f.write(url)

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
    print("در حال دریافت اخبار و بررسی حافظه برای جلوگیری از تکرار...")
    last_url = get_last_posted_url()
        
    all_news = []
    
    for source, url in NEWS_SOURCES.items():
        feed = feedparser.parse(url)
        valid_count = 0
        
        for entry in feed.entries:
            if valid_count >= 3:
                break
                
            title = entry.title
            link = entry.link
            
            # فیلتر کردن خبر تکراری
            if link == last_url:
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
                    save_last_posted_url(posted_url)
        else:
            print("🟡 خبر مهمی یافت نشد. ربات چیزی پست نکرد.")
    else:
        print("هیچ خبر جدیدی یافت نشد (احتمالا همه تکراری هستند).")
