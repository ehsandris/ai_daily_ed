import os
import requests

# خواندن اطلاعات از متغیرهای محیطی گیت‌هاب (امن)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

def send_test_message():
    print("در حال تلاش برای ارسال پیام از طریق سرور گیت‌هاب...")
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": CHANNEL_ID,
        "text": "🚀 سلام! این پیام به صورت خودکار از طریق GitHub Actions و بدون هیچ سرور اختصاصی ارسال شده است. مشکل فیلترینگ حل شد!"
    }
    
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("✅ پیام با موفقیت در کانال تلگرام ارسال شد!")
        else:
            print(f"❌ خطا در ارسال پیام: {response.text}")
    except Exception as e:
        print(f"❌ خطای شبکه: {e}")

if __name__ == "__main__":
    send_test_message()
