import os
import requests
import feedparser
import google.generativeai as genai

# خواندن متغیرها از گیت‌هاب
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# تنظیم هوش مصنوعی
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

def get_latest_ai_news():
    print("در حال دریافت اخبار از TechCrunch...")
    url = "https://techcrunch.com/category/artificial-intelligence/feed/"
    feed = feedparser.parse(url)
    
    if not feed.entries:
        return None
    return feed.entries[0]

def translate_to_persian(title, link):
    print("در حال ترجمه و خلاصه‌سازی توسط Gemini...")
    prompt = f"""
    شما یک ویراستار اخبار فناوری هستید. خبر زیر را به فارسی روان، جذاب و خلاصه (حداکثر در ۳ خط) ترجمه و بازنویسی کنید.
    عنوان خبر را در خط اول بنویسید.
    لینک منبع را در انتهای متن قرار دهید.
    
    عنوان انگلیسی: {title}
    لینک: {link}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
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
            print(f"❌ خطا: {response.text}")
    except Exception as e:
        print(f"❌ خطای شبکه: {e}")

if __name__ == "__main__":
    news = get_latest_ai_news()
    if news:
        print(f"خبر پیدا شد: {news.title}")
        persian_text = translate_to_persian(news.title, news.link)
        send_to_telegram(persian_text)
