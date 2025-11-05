# main.py
import os
from flask import Flask, request, abort
import telebot  # pyTelegramBotAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV ERROR: BOT_TOKEN is missing. Set variable BOT_TOKEN for this service and redeploy.")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "hook")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")  # ví dụ https://your-app.up.railway.app
PORT = int(os.getenv("PORT", "8000"))

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# basic handlers
@bot.message_handler(commands=['start'])
def handle_start(m):
    bot.reply_to(m, "Hello! Bot đã sẵn sàng 👋")

@bot.message_handler(func=lambda m: True)
def echo(m):
    bot.reply_to(m, f"Bạn gửi: {m.text}")

# webhook endpoint
@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') != 'application/json':
        abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    bot.process_new_updates([update])
    return "OK", 200

# health check
@app.get("/health")
def health():
    return "ok", 200

def setup_webhook():
    if not PUBLIC_BASE_URL:
        return
    url = f"{PUBLIC_BASE_URL}/webhook/{WEBHOOK_SECRET}"
    bot.remove_webhook()
    bot.set_webhook(url=url, max_connections=20, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=PORT)
