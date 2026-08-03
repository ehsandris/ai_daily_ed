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
        # گرفتن ۲ خبر آخر هر سایت
        for entry in feed.entries[:2]:
            summary = clean_html(entry.summary)[:500] # محدود کردن حجم خلاصه
            all_news.append({
                "source": source,
                "title": entry.title,
                "link": entry.link,
                "summary": summary
            })
            
    return all_news[:5] # برگرداندن ۵ خبر اول برای بررسی

def generate_engaging_post(news_list):
    print(f"در حال تحلیل {len(news_list)} خبر توسط هوش مصنوعی...")
    
    # ساخت لیست خام اخبار برای ارائه به هوش مصنوعی
    news_data = ""
    for i, news in enumerate(news_list, 1):
        news_data += f"خبر {i}:\nعنوان: {news['title']}\nخلاصه: {news['summary']}\nلینک: {news['link']}\n---\n"
    
    prompt = f"""
    شما یک ویراستار ارشد، تحلیل‌گر و نویسنده خلاق در یک کانال تلگرامی پرطرفدار اخبار فناوری هستید. 
    هدف شما تولید محتوایی است که مخاطب را میخکوب کند و اصلاً شبیه ربات نباشد.

    لیست جدیدترین اخبار را در زیر دارید:
    {news_data}

    وظایف شما به ترتیب:
    1. **انتخاب:** از بین این اخبار، فقط یک خبر را انتخاب کنید که مهم‌ترین، تاثیرگذارترین یا جنجالی‌ترین باشد. (اخبار تکراری، تامین مالی‌های کوچک یا آپدیت‌های ناچیز را رد کنید).
    2. **روایت‌گری (بدون قالب ثابت):** خبر انتخاب شده را با لحنی کاملاً انسانی، روان و جذاب بازنویسی کنید. 
       - لحن متن باید با ماهیت خبر همراستا باشد (اگر خبر پیشرفت بزرگی است هیجان‌انگیز، اگر خبر محدودیتی است جدی و هشداردهنده).
       - اصلاً الکی جو ندهید و غلو نکنید. حقایق را بگویید اما با زیبایی.
       - از ساختارهای ماشینی (مثل "تیتر: ... خلاصه: ...") استفاده نکنید. متن باید مثل یک پست لاین تلگرامی از یک آدم دنبال‌دار باشد.
       - حجم متن بین ۳ تا ۵ خط باشد.
    3. **هشتگ‌گذاری:** در انتهای متن، ۲ الی ۳ هشتگ مرتبط و استاندارد (بدون فاصله) اضافه کنید.
    4. **منبع:** در خط آخر، لینک خبر انتخاب شده را قرار دهید.

    فقط متن نهایی پست تلگرام را خروجی بدهید، بدون هیچ متن یا توضیح اضافه‌ای قبل و بعد از آن.
    """
    
    try:
        client = Client(
            host='https://ollama.com',
            headers={'Authorization': f'Bearer {AI_API_KEY}'}
        )
        
        response = client.chat(
            model=AI_MODEL,
            messages=[{'role': 'user', 'content': prompt}]
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
        if post_text:
            send_to_telegram(post_text)
        else:
            print("هوش مصنوعی نتوانست پستی تولید کند.")
    else:
        print("هیچ خبری یافت نشد.")
