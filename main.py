from flask import Flask, request
import os, requests, time, threading, random, string, datetime
from datetime import datetime as dt

app = Flask(__name__)

# ========== ENV ==========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")
LOG_URL = os.getenv("LOG_URL")  # Google Apps Script webhook
MAX_UPDATE_AGE = 90  # giây

# ========== MEMORY ==========
daily_exports = {}  # {chat_id: {"date": "YYYY-MM-DD", "count": 3}}

# ============================================================
# 1) CONTENT TẠM
# ============================================================
def get_today_content():
    return {
        "day_name": "Ngày Bánh Crepe Toàn Cầu",
        "fun_fact": "Crepe mỏng nhưng ăn nhiều vẫn mập.",
        "category": "food",
        "quirky_score": 0.9,
        "official_score": 0.3,
    }

# ============================================================
# 2) NONCE
# ============================================================
def generate_nonce(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# ============================================================
# 3) CAPTION BUILDER (TEXT ONLY)
# ============================================================
def build_caption(preset, day_name, fun_fact, nonce):
    shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        return (
            f"🎉 Hôm nay là {day_name}!\n"
            f"Nấu bột, đổ mỏng, lật cho cháy mép — đó là phong cách.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )
    elif preset == "trung_tinh":
        return (
            f"📅 Hôm nay: {day_name}\n"
            f"Có thêm một cái cớ để loài người làm điều vô lý.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )
    else:  # mia_nhe
        return (
            f"🎂 Hôm nay là {day_name}\n"
            f"Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )

# ============================================================
# 4) LIMIT 10 EXPORT / DAY
# ============================================================
def check_daily_limit(chat_id):
    today = dt.now().strftime("%Y-%m-%d")
    rec = daily_exports.get(chat_id, {"date": today, "count": 0})
    if rec["date"] != today:
        rec = {"date": today, "count": 0}
    if rec["count"] >= 10:
        return False
    rec["count"] += 1
    daily_exports[chat_id] = rec
    return True

# ============================================================
# 5) FLASK ROUTES
# ============================================================
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)

    if not update:
        return {"ok": True}

    # callback từ nút inline
    if "callback_query" in update:
        handle_callback(update)
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
        send_msg(
            chat_id,
            "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😉\n"
            "Gõ /today để xem hôm nay nhân loại lại bịa ra ngày gì."
        )
        log_event(make_log(update, "start", text))

    elif text == "/today":
        if not check_daily_limit(chat_id):
            send_msg(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào /start nhé.")
            return {"ok": True}

        content = get_today_content()
        nonce = generate_nonce()
        caption = build_caption("mia_nhe", content["day_name"], content["fun_fact"], nonce)

        # 3 nút inline
        buttons = {
            "inline_keyboard": [[
                {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                {"text": "💡 Suggest Day", "callback_data": "suggest"}
            ]]
        }

        send_msg(chat_id, caption, reply_markup=buttons)
        log_event(make_log(update, "today", text, nonce=nonce, action="today"))

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            send_msg(chat_id, "Gửi kiểu này nè: /suggest Ngày thế giới ăn bún riêu")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea, action="suggest"))

    else:
        send_msg(chat_id, f"Tôi nghe không rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))

    return {"ok": True}

# ============================================================
# 6) HANDLE CALLBACK
# ============================================================
def handle_callback(update):
    query = update["callback_query"]
    data = query.get("data")
    chat_id = query["message"]["chat"]["id"]

    # ack luôn để Telegram khỏi chờ
    requests.post(f"{API_URL}/answerCallbackQuery", json={
        "callback_query_id": query["id"]
    })

    if data.startswith("share:"):
        nonce = data.split(":", 1)[1]
        link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
        send_msg(chat_id, f"Ông share card này nhé 👉 {link}\n#viaDzDay")
        log_event(make_log(update, "share", data, nonce=nonce, action="share"))

    elif data.startswith("copy:"):
        nonce = data.split(":", 1)[1]
        content = get_today_content()
        caption = build_caption("mia_nhe", content["day_name"], content["fun_fact"], nonce)
        send_msg(chat_id, caption)
        log_event(make_log(update, "copy", data, nonce=nonce, action="copy"))

    elif data == "suggest":
        send_msg(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày")
        log_event(make_log(update, "suggest_prompt", data, action="suggest_prompt"))

# ============================================================
# 7) SEND / LOG
# ============================================================
def send_msg(chat_id, text, reply_markup=None):
    if not BOT_TOKEN:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
        # in rõ để debug khi Telegram báo lỗi
        try:
            print("SEND >>>", r.json(), flush=True)
        except Exception:
            print("SEND RAW >>>", r.text, flush=True)
    except Exception as e:
        print("SEND ERR >>>", e, flush=True)

def make_log(update, command, text, nonce=None, caption_preset="mia_nhe", action=None):
    # lấy từ message hoặc từ callback
    msg = update.get("message") or update.get("callback_query", {}).get("message", {}) or {}
    user = (msg.get("from") or update.get("callback_query", {}).get("from") or {})
    return {
        "chat_id": msg.get("chat", {}).get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "caption_preset": caption_preset,
        "action": action,
        "nonce": nonce,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "source": "telegram",
        "raw": update,
    }

def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

# ============================================================
# 8) KEEP WARM
# ============================================================
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
