import os
import requests
import feedparser

# خواندن اطلاعات ربات از متغیرهای امن گیت‌هاب
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

def get_latest_ai_news():
    print("در حال دریافت آخرین اخبار از TechCrunch...")
    url = "https://techcrunch.com/category/artificial-intelligence/feed/"
    feed = feedparser.parse(url)
    
    if not feed.entries:
        print("❌ هیچ خبری یافت نشد!")
        return None
    
    latest_news = feed.entries[0]
    return {
        "title": latest_news.title,
        "link": latest_news.link
    }

def send_to_telegram(text):
    print("در حال ارسال به تلگرام...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("✅ خبر با موفقیت در کانال تلگرام ارسال شد!")
        else:
            print(f"❌ خطا در ارسال: {response.text}")
    except Exception as e:
        print(f"❌ خطای شبکه: {e}")

if __name__ == "__main__":
    news = get_latest_ai_news()
    if news:
        print(f"خبر پیدا شد: {news['title']}")
        message = f"🆕 <b>خبر جدید هوش مصنوعی</b>\n\n{news['title']}\n\n🔗 لینک: {news['link']}"
        send_to_telegram(message)
