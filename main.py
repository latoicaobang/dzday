from flask import Flask, request
import os, requests, time, threading, random, string, datetime
from datetime import datetime as dt

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")
LOG_URL = os.getenv("LOG_URL")  # Google Apps Script webhook
MAX_UPDATE_AGE = 90  # giây

# ---- MEMORY STORE ----
daily_exports = {}  # {chat_id: {"date":"YYYY-MM-DD","count":int}}

# ============================================================
# 1️⃣ CONTENT: TẠM HARD-CODE HÔM NAY
# ============================================================
def get_today_content():
    # TODO: Phase 1 sẽ đọc từ Google Sheet / DB / AI
    return {
        "day_name": "Ngày Bánh Crepe Toàn Cầu",
        "fun_fact": "Crepe mỏng nhưng ăn nhiều vẫn mập.",
        "category": "food",
        "official_score": 0.3,
        "quirky_score": 0.9
    }

# ============================================================
# 2️⃣ HELPER: GENERATE NONCE
# ============================================================
def generate_nonce(length=8):
    """Sinh chuỗi ngẫu nhiên 8 ký tự a-z0-9"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# ============================================================
# 3️⃣ HELPER: BUILD CAPTION
# ============================================================
def build_caption(preset, day_name, fun_fact, nonce):
    """Sinh caption theo 3 preset: mia_nhe, tau_hai, trung_tinh"""
    shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        body = f"🎉 Hôm nay là *{day_name}!* \nNấu bột, đổ mỏng, lật cho cháy mép — đó là triết lý sống.\nFun fact: {fun_fact}\n#viaDzDay {shortlink}"
    elif preset == "trung_tinh":
        body = f"📅 Hôm nay: *{day_name}*\nMột dịp nhỏ để con người giả vờ có lý do làm điều vô lý.\nFun fact: {fun_fact}\n#viaDzDay {shortlink}"
    else:  # mia_nhe (default)
        body = f"🎂 Hôm nay là *{day_name}*\nKhông ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\nFun fact: {fun_fact}\n#viaDzDay {shortlink}"
    return body

# ============================================================
# 4️⃣ HELPER: CHECK DAILY LIMIT
# ============================================================
def check_daily_limit(chat_id):
    """Giới hạn 10 export/ngày cho mỗi user"""
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
# 5️⃣ MAIN ROUTES
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

    # xử lý callback button
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
        send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😏\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(make_log(update, "start", text))

    elif text == "/today":
        if not check_daily_limit(chat_id):
            send_msg(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào /start nhé.")
            return {"ok": True}

        content = get_today_content()
        nonce = generate_nonce()
        caption = build_caption("mia_nhe", content["day_name"], content["fun_fact"], nonce)

        buttons = {
            "inline_keyboard": [[
                {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                {"text": "💡 Suggest Day", "callback_data": "suggest"}
            ]]
        }
        send_msg(chat_id, caption, parse_mode="Markdown", reply_markup=buttons)
        log_event(make_log(update, "today", text, nonce=nonce, action="today"))

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            send_msg(chat_id, "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea, action="suggest"))

    else:
        send_msg(chat_id, f"Tôi nghe không rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))

    return {"ok": True}

# ============================================================
# 6️⃣ CALLBACK HANDLER
# ============================================================
def handle_callback(update):
    query = update["callback_query"]
    data = query.get("data")
    chat_id = query["message"]["chat"]["id"]

    if data.startswith("share:"):
        nonce = data.split(":")[1]
        share_link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
        send_msg(chat_id, f"Ông share card này nhé 👉 {share_link}\n#viaDzDay")
        log_event(make_log(update, "share", data, nonce=nonce, action="share"))

    elif data.startswith("copy:"):
        nonce = data.split(":")[1]
        content = get_today_content()
        caption = build_caption("mia_nhe", content["day_name"], content["fun_fact"], nonce)
        # chỉ ping chứ không spam caption dài
        requests.post(f"{API_URL}/answerCallbackQuery", json={
            "callback_query_id": query["id"],
            "text": "Caption ở trên, ông copy đi nhé.",
            "show_alert": False
        })
        log_event(make_log(update, "copy", data, nonce=nonce, action="copy"))

    elif data == "suggest":
        send_msg(chat_id, "Gửi gợi ý bằng lệnh `/suggest Tên ngày` nhé.", parse_mode="Markdown")
        log_event(make_log(update, "suggest_prompt", data, action="suggest_prompt"))

    # acknowledge callback
    requests.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]})

# ============================================================
# 7️⃣ SEND / LOG FUNCTIONS
# ============================================================
def send_msg(chat_id, text, parse_mode=None, reply_markup=None):
    if not BOT_TOKEN:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    print("SEND >>>", r.text, flush=True)

def make_log(update, command, text, nonce=None, caption_preset="mia_nhe", action=None):
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
# 8️⃣ KEEP WARM
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
