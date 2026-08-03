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
    
def format_post_for_telegram(text, available_links):
    """پاک‌سازی متن، بولد کردن خط اول و اضافه کردن دقیق لینک HTML"""
    
    chosen_link = None
    text = text.strip()
    
    # پیدا کردن لینکی که هوش مصنوعی ممکن است در متن گذاشته باشد
    for link in available_links:
        if link in text:
            chosen_link = link # یادمان باشد کدام لینک را انتخاب کرده
            # حذف لینک از متن
            text = re.sub(r'\[.*?\]\(' + re.escape(link) + r'\)', '', text)
            text = text.replace(link, '')
    
    # پاکسازی پرانتزها و کروشه‌های خالی
    text = text.replace('[]', '').replace('()', '').strip()
    
    # جدا کردن خط اول (تیتر) برای بولد کردن
    lines = text.split('\n')
    if len(lines) > 1:
        title = lines[0].strip()
        rest_of_text = '\n'.join(lines[1:]).strip()
        # بولد کردن تیتر با HTML
        text = f"<b>{title}</b>\n\n{rest_of_text}"
    
    # اگر هوش مصنوعی هیچ لینکی در متن نگذاشته بود، اولین لینک لیست را به عنوان منبع می‌گذاریم
    if not chosen_link and available_links:
        chosen_link = available_links[0]
        
    # اضافه کردن لینک استاندارد HTML به انتهای متن
    if chosen_link:
        text += f'\n\n<a href="{chosen_link}">📚 منبع خبر</a>'
        
    return text, chosen_link

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
    # متن از قبل در تابع format_post_for_telegram فرمت شده است
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text, # <--- مستقیم خود text را می‌فرستیم
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
                available_links = [news['link'] for news in news_list]
                
                # تابع جدید حالا دو خروجی دارد: متن نهایی و لینک انتخاب شده
                final_text, chosen_link = format_post_for_telegram(post_text, available_links)
                
                if send_to_telegram(final_text):
                    # ذخیره لینک دقیقی که هوش مصنوعی انتخاب کرده بود
                    if chosen_link:
                        save_posted_url(chosen_link, get_posted_history())
            else:
                print("🟡 خبر مهمی یافت نشد. ربات چیزی پست نکرد.")
        else:
            print("🔴 هیچ خبر تازه‌ای در ۲۴ ساعت گذشته یافت نشد. ربات کانال را آپدیت نمی‌کند.")
            
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"❌ خطای بحرانی:\n{error_msg}")
        notify_admin(f"خطای بحرانی در اجرای ربات:\n{error_msg}")
