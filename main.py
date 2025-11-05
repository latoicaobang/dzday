# main.py
import os
import json
import time
import logging
from datetime import datetime, timezone

from flask import Flask, request, abort
import telebot  # pyTelegramBotAPI
import requests

# ============== Logging ==============
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("dzday")

# ============== Env ==============
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("WEBHOOK_URL", "").strip()  # ví dụ: https://<app>.up.railway.app
PORT = int(os.getenv("PORT", "8080"))

# Google Sheet (tùy chọn)
SHEET_ID = os.getenv("SHEET_ID", "").strip()  # khuyến nghị dùng ID, gọn hơn
SHEET_NAME = os.getenv("SHEET_NAME", "Logs").strip()
GOOGLE_SA_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

if not BOT_TOKEN:
    log.error("Missing BOT_TOKEN env")
    # Không raise để Railway vẫn khởi động, nhưng sẽ không set webhook

# ============== Telegram Bot ==============
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, num_threads=1)

# ============== Flask App ==============
app = Flask(__name__)

# ============== Google Sheets helper (optional) ==============
_gs_client = None
_worksheet = None

def _init_gs():
    """Khởi tạo Google Sheets client nếu có cấu hình."""
    global _gs_client, _worksheet
    if not (SHEET_ID and GOOGLE_SA_JSON):
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Cho phép dạng base64 hoặc raw JSON
        try:
            sa_dict = json.loads(GOOGLE_SA_JSON)
        except json.JSONDecodeError:
            import base64
            sa_dict = json.loads(base64.b64decode(GOOGLE_SA_JSON).decode("utf-8"))

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(sa_dict, scopes=scopes)
        _gs_client = gspread.authorize(creds)
        sh = _gs_client.open_by_key(SHEET_ID)
        try:
            _worksheet = sh.worksheet(SHEET_NAME)
        except Exception:
            _worksheet = sh.add_worksheet(title=SHEET_NAME, rows="1000", cols="20")
            _worksheet.append_row(["time_utc", "user_id", "username", "text", "update_id"])
        log.info("Sheets >>> connected ok")
    except Exception as e:
        log.error(f"Sheets >>> init failed: {e}")

def sheet_log(update):
    """Ghi 1 dòng log vào Google Sheet (nếu đã init)."""
    global _worksheet
    if _worksheet is None:
        return
    try:
        msg = update.message or update.callback_query.message if update.callback_query else None
        text = msg.text if msg and msg.text else ""
        user_id = msg.from_user.id if msg and msg.from_user else ""
        username = msg.from_user.username if msg and msg.from_user else ""
        update_id = update.update_id
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        _worksheet.append_row([now, str(user_id), str(username or ""), text, str(update_id)])
    except Exception as e:
        log.error(f"Sheets >>> append failed: {e}")

# ============== Bot Handlers ==============
@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    bot.reply_to(message, "Xin chào 👋 Bot đã online. Gõ gì đó để mình echo lại!")
    log.info(f"TG >>> /start from {message.from_user.id} | @{message.from_user.username}")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_echo(message):
    txt = message.text.strip()
    bot.reply_to(message, f"Bạn nói: {txt}")
    log.info(f"TG >>> text from {message.from_user.id}: {txt}")

# ============== Webhook Routes ==============
@app.get("/")
def health():
    return "ok", 200

@app.post(f"/webhook/{BOT_TOKEN}")
def tg_webhook():
    # Telegram sẽ gửi JSON vào đây
    if request.headers.get("content-type") != "application/json":
        abort(400)
    json_str = request.get_data().decode("utf-8")
    try:
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        # ghi sheet (best-effort)
        sheet_log(update)
    except Exception as e:
        log.error(f"Webhook >>> process failed: {e}")
    return "OK", 200

# ============== Webhook Setup Helper ==============
def set_webhook():
    """Đặt webhook trỏ về /webhook/<TOKEN> và log kết quả."""
    if not (BOT_TOKEN and PUBLIC_BASE_URL):
        log.warning("Skip set_webhook: missing BOT_TOKEN or WEBHOOK_URL")
        return

    url = f"{PUBLIC_BASE_URL}/webhook/{BOT_TOKEN}"
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    try:
        resp = requests.post(api, data={"url": url}, timeout=10)
        log.info(f"WEBHOOK SET >>> {resp.text}")
    except Exception as e:
        log.error(f"WEBHOOK SET >>> failed: {e}")

def delete_webhook():
    """Tiện gọi khi cần xoá webhook cũ."""
    if not BOT_TOKEN:
        return
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    try:
        resp = requests.post(api, timeout=10)
        log.info(f"WEBHOOK DEL >>> {resp.text}")
    except Exception as e:
        log.error(f"WEBHOOK DEL >>> failed: {e}")

# ============== App Startup ==============
@app.before_first_request
def on_startup():
    log.info("APP >>> startup")
    _init_gs()
    # (không bắt buộc) Xoá webhook cũ để tránh dính URL cũ
    delete_webhook()
    # Đặt webhook mới
    set_webhook()

# ============== Local/Dev runner (Railway dùng gunicorn) ==============
if __name__ == "__main__":
    log.info(f"RUN >>> 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
