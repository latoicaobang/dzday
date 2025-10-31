from flask import Flask, request
import os, requests

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)

    if update and "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text == "/start":
            send_msg(chat_id, "Xin chào, tôi là DzDay – đang chạy trên Railway 😏")
        elif text == "/today":
            send_msg(chat_id, "Hôm nay là Ngày Bánh Crepe Toàn Cầu 🍰 – lý do tuyệt vời để nấu ngu.")
        else:
            send_msg(chat_id, f"Tôi nghe không rõ lắm: {text}")

    return {"ok": True}

def send_msg(chat_id, text):
    resp = requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })
    print("SEND >>>", resp.text, flush=True)

# KHÔNG cần app.run() vì đã có gunicorn chạy từ Procfile
