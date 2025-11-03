from flask import Flask, request
import os
import requests
import time
import threading
import random
import string
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

# ====== ENV ======
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")  # ví dụ: https://dzday-production.up.railway.app/
LOG_URL = os.getenv("LOG_URL")    # Apps Script deploy URL
MAX_UPDATE_AGE = 90               # giây

# ====== LIMIT IN-MEM ======
# cấu trúc: { "2025-11-03": { 70184xxxx: 3 } }
DAILY_EXPORT = {}
MAX_EXPORT_PER_DAY = 10


# -------------------------------------------------
# helpers chung
# -------------------------------------------------
def vn_today_str():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")


def generate_nonce(length=8):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def extract_user(update: dict):
    if "message" in update:
        return update["message"].get("from", {})
    if "callback_query" in update:
        return update["callback_query"].get("from", {})
    return {}


def extract_chat(update: dict):
    if "message" in update:
        return update["message"].get("chat", {})
    if "callback_query" in update:
        return update["callback_query"].get("message", {}).get("chat", {})
    return {}


def build_caption(preset, day_name, fun_fact, nonce):
    shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        return (
            f"🎂 {day_name}\n"
            f"Hôm nay nhân loại lại rảnh.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )
    if preset == "trung_tinh":
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


def check_daily_limit(chat_id: int):
    today = vn_today_str()
    if today not in DAILY_EXPORT:
        DAILY_EXPORT[today] = {}
    user_map = DAILY_EXPORT[today]
    cur = user_map.get(chat_id, 0)
    if cur >= MAX_EXPORT_PER_DAY:
        return False
    user_map[chat_id] = cur + 1
    return True


def log_event(payload: dict):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)


def make_log(update: dict, command: str, text: str, extra: dict = None):
    user = extract_user(update)
    chat = extract_chat(update)
    base = {
        "chat_id": chat.get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "raw": update,
        "source": "telegram",
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        # 3 cột mới – để script ghi luôn
        "nonce": "",
        "action": "",
        "caption_preset": "",
    }
    if extra:
        base.update(extra)
    return base


def tg_send(chat_id, text, reply_markup=None):
    if not API_URL:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    print("SEND >>>", r.text[:200], flush=True)


# -------------------------------------------------
# Flask routes
# -------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)
    if not update:
        return {"ok": True}

    # 1) callback trước
    if "callback_query" in update:
        return handle_callback(update)

    # 2) message thường
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    # bỏ update cũ
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP >>> old update", flush=True)
        return {"ok": True}

    if text == "/start":
        tg_send(
            chat_id,
            "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😉\n"
            "Gõ /today để xem hôm nay nhân loại lại bịa ra ngày gì."
        )
        log_event(make_log(update, "start", text))
        return {"ok": True}

    if text == "/today":
        # check limit
        if not check_daily_limit(chat_id):
            tg_send(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào gõ /start nhé.")
            log_event(make_log(update, "limit", text, extra={"action": "limit_reached"}))
            return {"ok": True}

        # hardcode 1 ngày – Phase 2 sẽ thay bằng AI
        day_name = "Hôm nay là Ngày Bánh Crepe Toàn Cầu"
        fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."
        nonce = generate_nonce()
        shortlink = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

        body = (
            f"🎂 {day_name}\n"
            f"Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
            f"Fun fact: {fun_fact}\n"
            f"#viaDzDay {shortlink}"
        )

        reply_markup = {
            "inline_keyboard": [[
                {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                {"text": "💡 Suggest Day", "callback_data": "suggest"},
            ]]
        }

        tg_send(chat_id, body, reply_markup=reply_markup)

        log_event(make_log(update, "today", text, extra={
            "nonce": nonce,
            "action": "today",
            "caption_preset": "mia_nhe",
        }))

        return {"ok": True}

    if text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            tg_send(chat_id, "Gửi kiểu này nè: /suggest Ngày thế giới ăn bún riêu")
            log_event(make_log(update, "suggest_prompt", text, extra={"action": "suggest_prompt"}))
        else:
            tg_send(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea, extra={"action": "suggest"}))
        return {"ok": True}

    # fallback
    tg_send(chat_id, "Tôi nghe không rõ lắm. Gõ /today hoặc /suggest cho tử tế.")
    log_event(make_log(update, "unknown", text))
    return {"ok": True}


# -------------------------------------------------
# callback
# -------------------------------------------------
def handle_callback(update):
    cb = update.get("callback_query") or {}
    data = cb.get("data") or ""
    chat = cb.get("message", {}).get("chat", {}) or {}
    chat_id = chat.get("id")

    # bắt buộc trả lời callback để Telegram khỏi quay
    if API_URL and cb.get("id"):
        try:
            requests.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=5)
        except Exception as e:
            print("ANSWER CB ERR >>>", e, flush=True)

    if data.startswith("share:"):
        nonce = data.split(":", 1)[1]
        link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
        tg_send(chat_id, f"Ông share card này nhé 👉 {link}\n#viaDzDay")
        log_event(make_log(update, "share", data, extra={
            "nonce": nonce,
            "action": "share",
        }))
        return {"ok": True}

    if data.startswith("copy:"):
        nonce = data.split(":", 1)[1]
        caption = build_caption(
            "mia_nhe",
            "Hôm nay là Ngày Bánh Crepe Toàn Cầu",
            "Crepe mỏng nhưng ăn nhiều vẫn mập.",
            nonce
        )
        tg_send(chat_id, caption)
        log_event(make_log(update, "copy", data, extra={
            "nonce": nonce,
            "action": "copy",
            "caption_preset": "mia_nhe",
        }))
        return {"ok": True}

    if data == "suggest":
        tg_send(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày nhé.")
        log_event(make_log(update, "suggest_prompt", data, extra={
            "action": "suggest_prompt",
        }))
        return {"ok": True}

    # nếu callback lạ
    log_event(make_log(update, "callback_unknown", data, extra={"action": "callback_unknown"}))
    return {"ok": True}


# -------------------------------------------------
# keep warm
# -------------------------------------------------
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
