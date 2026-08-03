import os
import requests
import feedparser
from ollama import Client

# خواندن متغیرها از گیت‌هاب
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL")

def get_latest_ai_news():
    print("در حال دریافت اخبار از TechCrunch...")
    url = "https://techcrunch.com/category/artificial-intelligence/feed/"
    feed = feedparser.parse(url)
    
    if not feed.entries:
        return None
    return feed.entries[0]

def translate_to_persian(title, link):
    print(f"در حال ترجمه توسط مدل {AI_MODEL}...")
    
    prompt = f"""
    شما یک ویراستار اخبار فناوری هستید. خبر زیر را به فارسی روان، جذاب و خلاصه (حداکثر در ۳ خط) ترجمه و بازنویسی کنید.
    عنوان خبر را در خط اول بنویسید.
    لینک منبع را در انتهای متن قرار دهید.
    
    عنوان انگلیسی: {title}
    لینک: {link}
    """
    
    try:
        # تنظیم کلاینت اولاما برای اتصال به کلاد
        client = Client(
            host='https://ollama.com',
            headers={'Authorization': f'Bearer {AI_API_KEY}'}
        )
        
        # ارسال درخواست به مدل
        response = client.chat(
            model=AI_MODEL,
            messages=[{'role': 'user', 'content': prompt}]
        )
        
        # گرفتن متن خروجی
        return response['message']['content']
        
    except Exception as e:
        print(f"❌ خطا در هوش مصنوعی: {e}")
        return f"🆕 {title}\n\n🔗 {link}"

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
            print("✅ پیام با موفقیت ارسال شد!")
        else:
            print(f"❌ خطا در ارسال تلگرام: {response.text}")
    except Exception as e:
        print(f"❌ خطای شبکه تلگرام: {e}")

if __name__ == "__main__":
    news = get_latest_ai_news()
    if news:
        print(f"خبر پیدا شد: {news.title}")
        persian_text = translate_to_persian(news.title, news.link)
        send_to_telegram(persian_text)
