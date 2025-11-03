from flask import Flask, request
import os
import requests
import time
import threading
import random
import string
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# ====== ENV ======
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")  # https://dzday-production.up.railway.app/
LOG_URL = os.getenv("LOG_URL")    # Google Apps Script
MAX_UPDATE_AGE = 90               # giây

# ====== LIMIT IN-MEMORY ======
# { "2025-11-03": { chat_id: count } }
DAILY_EXPORT = {}
MAX_EXPORT_PER_DAY = 10

# ====== TELEGRAM HELPER ======
def tg_send_message(chat_id, text, parse_mode=None, reply_markup=None):
    if not API_URL:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    print("SEND >>>", r.text[:300], flush=True)


# ====== NONCE ======
def generate_nonce(length=8):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


# ====== CAPTION BUILDER ======
def build_caption(preset, day_name, fun_fact, nonce):
    shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        return (
            f"🎂 {day_name}\n"
            f"Hôm nay nhân loại lại rảnh.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )
    elif preset == "trung_tinh":
        return (
            f"🎂 {day_name}\n"
            f"{fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )
    # default: mỉa nhẹ
    return (
        f"🎂 {day_name}\n"
        f"Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
        f"Fun fact: {fun_fact}\n"
        f"#viaDzDay {shortlink}"
    )


# ====== DAILY LIMIT ======
def check_daily_limit(chat_id):
    # dùng giờ VN
    today_vn = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    if today_vn not in DAILY_EXPORT:
        DAILY_EXPORT[today_vn] = {}
    user_map = DAILY_EXPORT[today_vn]
    current = user_map.get(chat_id, 0)
    if current >= MAX_EXPORT_PER_DAY:
        return False
    user_map[chat_id] = current + 1
    return True


# ====== LOGGING ======
def make_log(update, command, text, extra=None):
    """extra: dict bổ sung như nonce/action/caption_preset"""
    msg = update.get("message") or update.get("callback_query", {}).get("message") or {}
    user = (update.get("message") or update.get("callback_query", {}).get("from") or {}).get("from") or update.get("from", {}) or {}
    chat_obj = msg.get("chat") or update.get("callback_query", {}).get("message", {}).get("chat") or {}

    base = {
        "chat_id": chat_obj.get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "raw": update,
        "source": "telegram",
        # thêm timestamp ISO từ server
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }
    if extra:
        base.update(extra)
    return base


def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)


# ====== ROUTES ======
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)
    if not update:
        return {"ok": True}

    # 1) callback button
    if "callback_query" in update:
        return handle_callback(update)

    # 2) normal message
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
        tg_send_message(
            chat_id,
            "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😉\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì."
        )
        log_event(make_log(update, "start", text))

    elif text == "/today":
        # check limit
        if not check_daily_limit(chat_id):
            tg_send_message(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào gõ /start nhé.")
            log_event(make_log(update, "limit", text, extra={
                "action": "limit_reached",
            }))
            return {"ok": True}

        # ở Phase 2 ta vẫn hardcode ngày
        day_name = "Hôm nay là Ngày Bánh Crepe Toàn Cầu"
        fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."

        nonce = generate_nonce()
        shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

        body = (
            f"🎂 *{day_name}*\n"
            f"Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
            f"_Fun fact_: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )

        # inline buttons
        reply_markup = {
            "inline_keyboard": [[
                {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                {"text": "💡 Suggest Day", "callback_data": f"suggest"},
            ]]
        }

        tg_send_message(chat_id, body, parse_mode="Markdown", reply_markup=reply_markup)

        log_event(make_log(update, "today", text, extra={
            "nonce": nonce,
            "action": "today",
            "caption_preset": "mia_nhe",
        }))

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            tg_send_message(chat_id, "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
            log_event(make_log(update, "suggest_prompt", text))
        else:
            tg_send_message(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea, extra={
                "action": "suggest",
            }))

    else:
        tg_send_message(chat_id, f"Tôi nghe không rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))

    return {"ok": True}


def handle_callback(update):
    """xử lý 3 nút inline"""
    cb = update.get("callback_query") or {}
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")

    # để log đầy đủ
    extra = {
        "nonce": "",
        "action": "",
        "caption_preset": "",
    }

    if data.startswith("share:"):
        nonce = data.split(":", 1)[1]
        extra["nonce"] = nonce
        extra["action"] = "share"
        link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
        tg_send_message(chat_id, f"Ông share card này nhé 👉 {link}\n#viaDzDay")
        log_event(make_log(update, "share", data, extra=extra))

    elif data.startswith("copy:"):
        nonce = data.split(":", 1)[1]
        extra["nonce"] = nonce
        extra["action"] = "copy"
        # vẫn dùng preset mỉa nhẹ
        caption = build_caption(
            "mia_nhe",
            "Hôm nay là Ngày Bánh Crepe Toàn Cầu",
            "Crepe mỏng nhưng ăn nhiều vẫn mập.",
            nonce
        )
        tg_send_message(chat_id, caption)
        extra["caption_preset"] = "mia_nhe"
        log_event(make_log(update, "copy", data, extra=extra))

    elif data == "suggest":
        extra["action"] = "suggest_prompt"
        tg_send_message(chat_id, "Gửi gợi ý bằng lệnh: `/suggest Tên ngày` nhé.", parse_mode="Markdown")
        log_event(make_log(update, "suggest_prompt", data, extra=extra))

    else:
        # unknown callback
        log_event(make_log(update, "callback_unknown", data, extra={"action": "callback_unknown"}))

    # trả lời callback để Telegram khỏi quay cái đồng hồ
    if API_URL and cb.get("id"):
        requests.post(f"{API_URL}/answerCallbackQuery", json={
            "callback_query_id": cb["id"]
        }, timeout=5)

    return {"ok": True}


# ====== KEEP WARM ======
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
