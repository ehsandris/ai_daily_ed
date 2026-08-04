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
MODE = os.environ.get("MODE", "DAILY") # حالت پیش‌فرض روزانه است

# منابع خبری (افزودن MIT و Hugging Face)
NEWS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss",
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Zoomit": "https://www.zoomit.ir/rss",
    "Digiato": "https://www.digiato.com/feed/"
}

def notify_admin(error_text):
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

def clean_html(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()

def is_valid_news(title):
    junk_keywords = [
        'podcast', 'newsletter', 'sponsored', 'giveaway', 'best of', 'deals',
        'پادکست', 'خبرنامه', 'اسپانسر', 'آموزش', 'راهنمای خرید', 'معرفی گوشی', 'تخفیف'
    ]
    title_lower = title.lower()
    return not any(keyword in title_lower for keyword in junk_keywords)

def is_fresh_news(entry):
    pub_date_struct = entry.get('published_parsed')
    if pub_date_struct:
        pub_date = datetime.fromtimestamp(time.mktime(pub_date_struct))
        # اگر هفتگی بود ۷ روز (168 ساعت)، اگر روزانه بود ۲۴ ساعت
        hours = 168 if MODE == "WEEKLY" else 24
        if datetime.now() - pub_date > timedelta(hours=hours):
            return False
    return True

def get_latest_ai_news():
    print(f"در حال دریافت اخبار جدید (حالت: {MODE})...")
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
            
    limit = 25 if MODE == "WEEKLY" else 15
    return all_news[:limit]

def load_prompt():
    try:
        prompt_file = 'weekly_prompt.txt' if MODE == "WEEKLY" else 'prompt.txt'
        with open(prompt_file, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        print(f"❌ فایل {prompt_file} پیدا نشد!")
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
        raw_output = response['message']['content']
        
        # 🎯 استخراج تصمیم هوش مصنوعی و ثبت در لاگ
        decision_match = re.search(r'<decision>(.*?)</decision>', raw_output, re.DOTALL)
        if decision_match:
            decision_text = decision_match.group(1).strip()
            print(f"🧠 تصمیم هوش مصنوعی: {decision_text}")
            
            # پاک کردن تگ تصمیم از متن نهایی
            final_text = raw_output.replace(decision_match.group(0), '').strip()
            return final_text
        else:
            # اگر هوش مصنوعی تگ را نزد، همان متن خام را برمی‌گردانیم
            print("⚠️ هشدار: هوش مصنوعی تگ <decision> را ارسال نکرد!")
            return raw_output
        
    except Exception as e:
        print(f"❌ خطا در هوش مصنوعی: {e}")
        notify_admin(f"خطا در اتصال به هوش مصنوعی:\n{e}")
        return None

def format_post_for_telegram(text, available_links):
    """پاک‌سازی متن، بولد کردن خط اول و اضافه کردن دقیق لینک HTML"""
    
    chosen_link = None
    text = text.strip()
    
    # پیدا کردن شماره خبری که هوش مصنوعی انتخاب کرده (مثلا NEWS_ID: 3)
    id_match = re.search(r'NEWS_ID:\s*(\d+)', text)
    if id_match:
        news_id = int(id_match.group(1))
        if 0 < news_id <= len(available_links):
            chosen_link = available_links[news_id - 1]
            
    # حذف خط NEWS_ID از متن
    text = re.sub(r'NEWS_ID:\s*\d+', '', text).strip()
    
    # پاکسازی هرگونه لینک خامی که هوش مصنوعی ممکن است اشتباها نوشته باشد
    for link in available_links:
        text = re.sub(r'\[.*?\]\(' + re.escape(link) + r'\)', '', text)
        text = text.replace(link, '')
    
    # پاکسازی پرانتزها و کروشه‌های خالی
    text = text.replace('[]', '').replace('()', '').strip()
    
    # جدا کردن خط اول (تیتر) برای بولد کردن
    lines = text.split('\n')
    if len(lines) > 1:
        title = lines[0].strip()
        rest_of_text = '\n'.join(lines[1:]).strip()
        text = f"<b>{title}</b>\n\n{rest_of_text}"
    
    # اضافه کردن لینک استاندارد HTML به انتهای متن
    if chosen_link:
        text += f'\n\n<a href="{chosen_link}">📚 منبع خبر</a>'
    else:
        print("⚠️ هشدار: هوش مصنوعی NEWS_ID ارسال نکرد!")
        
    return text, chosen_link

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
        response = requests.post(url, data=payload, timeout=30)
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
                if MODE == "WEEKLY":
                    # در حالت هفتگی، متن توسط خود هوش مصنوعی فرمت شده است
                    send_to_telegram(post_text)
                else:
                    # در حالت روزانه، لینک و تیتر توسط کد فرمت می‌شود
                    available_links = [news['link'] for news in news_list]
                    final_text, chosen_link = format_post_for_telegram(post_text, available_links)
                    if send_to_telegram(final_text):
                        if chosen_link:
                            save_posted_url(chosen_link, get_posted_history())
            else:
                print("🟡 خبر مهمی یافت نشد. ربات چیزی پست نکرد.")
        else:
            print("🔴 هیچ خبر تازه‌ای یافت نشد. ربات کانال را آپدیت نمی‌کند.")
            
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"❌ خطای بحرانی:\n{error_msg}")
        notify_admin(f"خطای بحرانی در اجرای ربات:\n{error_msg}")
