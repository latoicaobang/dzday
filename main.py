from flask import Flask, request
import os, requests, time, threading, io, random, string
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import qrcode

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
SELF_URL = os.getenv("SELF_URL")
LOG_URL = os.getenv("LOG_URL")

MAX_UPDATE_AGE = 90  # seconds
DAILY_LIMIT = {}  # in-memory limit

# === Helpers ===
def generate_nonce():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def check_daily_limit(chat_id):
    now = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{chat_id}_{now}"
    DAILY_LIMIT.setdefault(key, 0)
    DAILY_LIMIT[key] += 1
    return DAILY_LIMIT[key] <= 10

def build_caption(preset, day_name, fun_fact, nonce):
    link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        return f"🤣 Hôm nay là {day_name}!\nLý do? Vì nhân loại rảnh quá thôi.\nFun fact: {fun_fact}\n#viaDzDay {link}"
    elif preset == "trung_tinh":
        return f"📅 {day_name}\nFun fact: {fun_fact}\n#viaDzDay {link}"
    else:
        return f"🎂 Hôm nay là {day_name}\nKhông ai bắt ông tin, nhưng người ta bịa ra đấy.\nFun fact: {fun_fact}\n#viaDzDay {link}"

# === Card Generator ===
def generate_card(day_name, fun_fact, nonce):
    W, H = 1080, 1350
    bg = Image.new("RGB", (W, H), color=(245, 240, 230))
    draw = ImageDraw.Draw(bg)

    # Fonts
    title_font = ImageFont.truetype("arial.ttf", 64)
    body_font = ImageFont.truetype("arial.ttf", 38)
    small_font = ImageFont.truetype("arial.ttf", 30)

    # Text layout
    y = 160
    draw.text((80, y), f"🎂 {day_name}", font=title_font, fill=(30, 30, 30))
    y += 140
    draw.text((80, y), "Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.", font=body_font, fill=(60, 60, 60))
    y += 220
    draw.text((80, y), f"Fun fact: {fun_fact}", font=body_font, fill=(70, 70, 70))

    # QR section
    link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=qr"
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").resize((220, 220))
    bg.paste(qr_img, (W - 260, H - 280))

    # Watermark
    draw.text((80, H - 160), "#viaDzDay", font=small_font, fill=(100, 100, 100))
    draw.text((80, H - 100), "dz.day/today", font=small_font, fill=(120, 120, 120))

    bio = io.BytesIO()
    bg.save(bio, format="JPEG", quality=90)
    bio.seek(0)
    return bio

# === Telegram Bot ===
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)
    if not update:
        return {"ok": True}

    # handle message
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        msg_ts = msg.get("date")

        if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
            return {"ok": True}

        if text == "/start":
            send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😏\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
            log_event(make_log(update, "start", text))
        elif text == "/today":
            if not check_daily_limit(chat_id):
                send_msg(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào /start nhé.")
                return {"ok": True}

            nonce = generate_nonce()
            day_name = "Ngày Bánh Crepe Toàn Cầu"
            fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."
            caption = build_caption("mia_nhe", day_name, fun_fact, nonce)
            img = generate_card(day_name, fun_fact, nonce)

            # Inline buttons
            buttons = {
                "inline_keyboard": [[
                    {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                    {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                    {"text": "💡 Suggest Day", "callback_data": "suggest"}
                ]]
            }

            send_photo(chat_id, img, caption, buttons)
            log_event(make_log(update, "today", text, nonce=nonce))
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

    # handle callback
    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["from"]["id"]
        data = cq["data"]
        msg = cq.get("message", {})

        if data.startswith("share:"):
            nonce = data.split(":")[1]
            link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
            send_msg(chat_id, f"Ông share card này nhé 👉 {link}\n#viaDzDay")
            log_event(make_log(update, "share", data, nonce=nonce, action="share"))

        elif data.startswith("copy:"):
            nonce = data.split(":")[1]
            day_name = "Ngày Bánh Crepe Toàn Cầu"
            fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."
            caption = build_caption("mia_nhe", day_name, fun_fact, nonce)
            send_msg(chat_id, caption)
            log_event(make_log(update, "copy", data, nonce=nonce, action="copy", caption_preset="mia_nhe"))

        elif data == "suggest":
            send_msg(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
            log_event(make_log(update, "suggest_prompt", data, action="suggest"))

    return {"ok": True}

# === Telegram senders ===
def send_msg(chat_id, text, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)

def send_photo(chat_id, photo_bytes, caption, buttons=None):
    files = {"photo": ("card.jpg", photo_bytes, "image/jpeg")}
    data = {"chat_id": chat_id, "caption": caption}
    if buttons:
        data["reply_markup"] = buttons
    requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=15)

# === Logging ===
def make_log(update, command, text, nonce="", action="", caption_preset=""):
    msg = update.get("message") or update.get("callback_query", {}).get("message", {}) or {}
    user = (msg.get("from") or update.get("callback_query", {}).get("from", {})) or {}
    return {
        "chat_id": msg.get("chat", {}).get("id") or user.get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "raw": update,
        "source": "telegram",
        "nonce": nonce,
        "action": action,
        "caption_preset": caption_preset,
        "timestamp": datetime.utcnow().isoformat()
    }

def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

# === Keep alive ===
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
