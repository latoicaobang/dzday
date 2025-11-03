from flask import Flask, request
import os, requests, time, threading, io, random, string, json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import qrcode

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
SELF_URL  = os.getenv("SELF_URL")
LOG_URL   = os.getenv("LOG_URL")

MAX_UPDATE_AGE = 90  # seconds
DAILY_LIMIT    = {}  # in-memory: {f"{chat_id}_{YYYY-MM-DD}": count}

# ---------- helpers ----------
def generate_nonce(k: int = 8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=k))

def check_daily_limit(chat_id: int, max_per_day: int = 10) -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key   = f"{chat_id}_{today}"
    DAILY_LIMIT[key] = DAILY_LIMIT.get(key, 0) + 1
    return DAILY_LIMIT[key] <= max_per_day

def build_caption(preset: str, day_name: str, fun_fact: str, nonce: str) -> str:
    link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        return f"🤣 Hôm nay là {day_name}!\nLý do? Vì nhân loại rảnh quá thôi.\nFun fact: {fun_fact}\n#viaDzDay {link}"
    if preset == "trung_tinh":
        return f"📅 {day_name}\nFun fact: {fun_fact}\n#viaDzDay {link}"
    # default mia_nhe
    return f"🎂 Hôm nay là {day_name}\nKhông ai bắt ông tin, nhưng người ta bịa ra đấy.\nFun fact: {fun_fact}\n#viaDzDay {link}"

def _safe_font(size: int):
    # Try common fonts, then fall back to default bitmap font
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

def generate_card(day_name: str, fun_fact: str, nonce: str) -> io.BytesIO:
    # 1080×1350 portrait
    W, H = 1080, 1350
    bg = Image.new("RGB", (W, H), color=(245, 240, 230))
    draw = ImageDraw.Draw(bg)

    title_f = _safe_font(64)
    body_f  = _safe_font(38)
    small_f = _safe_font(30)

    # content
    y = 140
    draw.text((80, y), f"🎂 {day_name}", font=title_f, fill=(30, 30, 30))
    y += 120
    body = "Không ai bắt ông tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
    draw.text((80, y), body, font=body_f, fill=(60, 60, 60))
    y += 200
    draw.text((80, y), f"Fun fact: {fun_fact}", font=body_f, fill=(70, 70, 70))

    # QR
    link_qr = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=qr"
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(link_qr)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").resize((220, 220))
    bg.paste(qr_img, (W - 260, H - 280))

    # watermarks
    draw.text((80, H - 160), "#viaDzDay", font=small_f, fill=(100, 100, 100))
    draw.text((80, H - 100), "dz.day/today", font=small_f, fill=(120, 120, 120))

    buff = io.BytesIO()
    bg.save(buff, format="JPEG", quality=90)
    buff.seek(0)
    return buff

# ---------- telegram senders ----------
def send_msg(chat_id, text, parse_mode=None):
    if not API_URL: return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    try:
        r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
        print("SEND text >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("SEND text ERR >>>", e, flush=True)

def send_photo(chat_id, photo_bytes: io.BytesIO, caption: str, buttons: dict | None):
    if not API_URL: return
    data = {"chat_id": chat_id, "caption": caption}
    if buttons:
        # must be JSON string for multipart/form-data
        data["reply_markup"] = json.dumps(buttons)
    files = {"photo": ("card.jpg", photo_bytes, "image/jpeg")}
    try:
        r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=20)
        print("SEND photo >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("SEND photo ERR >>>", e, flush=True)

# ---------- logging ----------
def make_log(update, command, text, nonce="", action="", caption_preset=""):
    msg  = update.get("message") or update.get("callback_query", {}).get("message", {}) or {}
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
        print("LOG >>> skipped", flush=True); return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=6)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

# ---------- routes ----------
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)
    if not update: return {"ok": True}

    # MESSAGE
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text    = (msg.get("text") or "").strip()
        msg_ts  = msg.get("date")
        if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
            print("SKIP old update", flush=True); return {"ok": True}

        if text == "/start":
            send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😏\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
            log_event(make_log(update, "start", text))
            return {"ok": True}

        if text == "/today":
            if not check_daily_limit(chat_id):
                send_msg(chat_id, "Hôm nay ông share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào /start nhé.")
                return {"ok": True}

            nonce    = generate_nonce()
            day_name = "Ngày Bánh Crepe Toàn Cầu"
            fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."
            preset   = "mia_nhe"
            caption  = build_caption(preset, day_name, fun_fact, nonce)

            buttons = {"inline_keyboard": [[
                {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
                {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                {"text": "💡 Suggest Day", "callback_data": "suggest"}
            ]]}

            # Try to send card; if anything fails, send text fallback
            try:
                img = generate_card(day_name, fun_fact, nonce)
                send_photo(chat_id, img, caption, buttons)
            except Exception as e:
                print("CARD ERR >>>", e, flush=True)
                send_msg(chat_id, caption)

            log_event(make_log(update, "today", text, nonce=nonce, caption_preset=preset))
            return {"ok": True}

        if text.startswith("/suggest"):
            idea = text.replace("/suggest", "", 1).strip()
            if not idea:
                send_msg(chat_id, "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
            else:
                send_msg(chat_id, f"Đã ghi nhận gợi ý của ông: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
                log_event(make_log(update, "suggest", idea))
            return {"ok": True}

        # default
        send_msg(chat_id, f"Tôi nghe không rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))
        return {"ok": True}

    # CALLBACK
    if "callback_query" in update:
        cq      = update["callback_query"]
        chat_id = cq["from"]["id"]
        data    = cq.get("data", "")
        if data.startswith("share:"):
            nonce = data.split(":", 1)[1]
            link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
            send_msg(chat_id, f"Ông share card này nhé 👉 {link}\n#viaDzDay")
            log_event(make_log(update, "share", data, nonce=nonce, action="share"))
        elif data.startswith("copy:"):
            nonce    = data.split(":", 1)[1]
            day_name = "Ngày Bánh Crepe Toàn Cầu"
            fun_fact = "Crepe mỏng nhưng ăn nhiều vẫn mập."
            preset   = "mia_nhe"
            caption  = build_caption(preset, day_name, fun_fact, nonce)
            send_msg(chat_id, caption)
            log_event(make_log(update, "copy", data, nonce=nonce, action="copy", caption_preset=preset))
        elif data == "suggest":
            send_msg(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
            log_event(make_log(update, "suggest_prompt", data, action="suggest"))
        return {"ok": True}

    return {"ok": True}

# ---------- keep warm ----------
def keep_warm():
    if not SELF_URL: return
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
            print("WARM >>> ping", flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)

threading.Thread(target=keep_warm, daemon=True).start()
