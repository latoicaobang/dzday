from flask import Flask, request
import os
import requests
import time
import threading

app = Flask(__name__)

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

# để giữ ấm Railway: SELF_URL=https://dzday-production.up.railway.app/
SELF_URL = os.getenv("SELF_URL")

# bỏ qua các update quá cũ để tránh Telegram replay cả đống message cũ
MAX_UPDATE_AGE = 90  # giây

# ========= ROUTES =========
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

    # 1) chặn update cũ
    msg_ts = msg.get("date")
    if msg_ts:
        age = time.time() - msg_ts
        if age > MAX_UPDATE_AGE:
            print(f"SKIP >>> old update ({age:.1f}s)", flush=True)
            return {"ok": True}

    # 2) xử lý command
    if text == "/start":
        return send_msg(
            chat_id,
            "Lại là bạn đấy à 😏\n"
            "Muốn xem hôm nay người ta bịa ra ngày gì thì gõ: /today"
        )

    elif text == "/today":
        # demo Dandattone
        body = (
            "🎂 *Hôm nay là Ngày bánh Crepe Toàn cầu*\n\n"
            "Nghe hơi giống bánh xèo miền Tây, nhưng đúng là người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang. "
            "Thông minh như bạn thì sẽ chém *tôi ăn vì văn hoá*, nghe uy tín hơn là ăn vì đói.\n\n"
            "Xin chúc mừng: bạn đã biết thêm 1 loại bánh tuy mỏng nhưng ăn nhiều vẫn mập thù lù.\n\n"
            "#viaDzDay https://dz.day/today"
        )
        return send_msg(chat_id, body, parse_mode="Markdown")

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            return send_msg(
                chat_id,
                "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.\n"
                "Tôi sẽ xem xét, chê trước rồi mới duyệt.",
                parse_mode="Markdown",
            )
        # TODO: ở đây sẽ lưu vào Supabase / Sheet
        return send_msg(
            chat_id,
            f"Đã ghi nhận gợi ý của bạn *biết tuốt*: “{idea}”. Nếu đủ dị, nó sẽ được public và được Tổ quốc ghi công.",
        )

    else:
        # fallback
        return send_msg(
            chat_id,
            f"Gõ gì mà lộn xào thế: {text}\nGõ /today hoặc /suggest cho tử tế.",
        )

    # luôn trả ok cho Telegram
    # (thực ra return ở trên đủ rồi, nhưng để chắn)
    return {"ok": True}

# ========= HELPERS =========
def send_msg(chat_id, text, parse_mode=None):
    if not BOT_TOKEN:
        print("ERROR >>> TELEGRAM_TOKEN không có, tôi không gửi được gì hết.", flush=True)
        return {"ok": False}

    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    resp = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    print("SEND >>>", resp.text, flush=True)
    return {"ok": True}

# ========= KEEP WARM =========
def keep_warm():
    if not SELF_URL:
        print("WARM >>> SELF_URL không có, bỏ qua keep-alive", flush=True)
        return
    while True:
        try:
            r = requests.get(SELF_URL, timeout=5)
            print("WARM >>> ping", r.status_code, flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)

# chạy thread giữ ấm (daemon)
threading.Thread(target=keep_warm, daemon=True).start()
