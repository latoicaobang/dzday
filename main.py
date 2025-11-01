from flask import Flask, request
import os, requests, time, threading

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")
LOG_URL = os.getenv("LOG_URL")  # Google Apps Script webhook
MAX_UPDATE_AGE = 90  # giây

@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)

    if not update:
        return {"ok": True}

    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    # chặn update cũ
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP >>> old update", flush=True)
        return {"ok": True}

    if text == "/start":
        send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😏\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(make_log(update, "start", text))

    elif text == "/today":
        body = (
            "🎂 *Hôm nay là Ngày Bánh Crepe Toàn Cầu*\n"
            "Không ai bắt ông tin đâu, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
            "Fun fact: crepe mỏng nhưng ăn nhiều vẫn mập.\n"
            "#viaDzDay https://dz.day/today"
        )
        send_msg(chat_id, body, parse_mode="Markdown")
        log_event(make_log(update, "today", text))

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            send_msg(chat_id, "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea))

    else:
        send_msg(chat_id, f"Tôi nghe không rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))

    return {"ok": True}

def send_msg(chat_id, text, parse_mode=None):
    if not BOT_TOKEN:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    print("SEND >>>", r.text, flush=True)

def make_log(update, command, text):
    msg = update.get("message") or {}
    user = msg.get("from") or {}
    return {
        "chat_id": msg.get("chat", {}).get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "raw": update,
    }

def log_event(payload):
    if not LOG_URL:
        return
    try:
        requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>> ok", flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

# giữ ấm
def keep_warm():
    if not SELF_URL:
        return
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
            print("WARM >>> ping", flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)

threading.Thread(target=keep_warm, daemon=True).start()
