from flask import Flask, request
import requests
import os

app = Flask(__name__)
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route('/')
def home():
    return "DzDayBot alive"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        if text == "/start":
            send(chat_id, "Xin chào, tôi là DzDay – trợ lý Dandattone của ông đây 😏")
        elif text == "/today":
            send(chat_id, "Hôm nay là Ngày Bánh Crepe Toàn Cầu 🍰 – lý do tuyệt vời để nấu ngu.")
        else:
            send(chat_id, f"Tôi nghe không rõ lắm: {text}")
    return {"ok": True}

def send(chat_id, text):
    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

if __name__ == '__main__':
    app.run(debug=True)
