from flask import Flask, request
import os, requests, threading, time

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
SELF_URL = os.getenv("SELF_URL")  # https://dzday.up.railway.app/

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
    if not BOT_TOKEN:
        print("NO TOKEN!!", flush=True)
        return
    resp = requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })
    print("SEND >>>", resp.text, flush=True)

def keep_warm():
    if not SELF_URL:
        return
    while True:
        try:
            # gọi vào / để container thấy có traffic
            requests.get(SELF_URL, timeout=5)
            print("WARM >>> ping", flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)   # 25s/lần là đủ giữ sống

# chạy thread giữ ấm
threading.Thread(target=keep_warm, daemon=True).start()
