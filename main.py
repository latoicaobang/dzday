# main.py — DzDay v3.2 (fix: color must be int or tuple)
from flask import Flask, request
import os, io, time, threading, json, random, string, datetime as dt
import requests
from PIL import Image, ImageDraw, ImageFont
import qrcode

app = Flask(__name__)

BOT_TOKEN   = os.getenv("TELEGRAM_TOKEN")
API_URL     = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
SELF_URL    = os.getenv("SELF_URL")
LOG_URL     = os.getenv("LOG_URL")
MAX_UPDATE_AGE = 90

# Fonts (Playfair)
FONT_REG_PATH    = os.getenv("FONT_REG_PATH", "assets/Playfair.ttf")
FONT_ITALIC_PATH = os.getenv("FONT_ITALIC_PATH", "assets/Playfair-Italic.ttf")

# Square canvas – mobile first
CANVAS  = (1080, 1080)
CARD_R  = 40
PADDING = 64
GAP     = 28

THEMES = {
    "ivory": {"bg":(243,238,231), "card":(255,255,255), "fg":(36,34,30), "sub":(94,92,88), "chip":(245,242,238)},
    "night": {"bg":(14,15,19),    "card":(24,26,32),    "fg":(238,238,240), "sub":(170,170,176), "chip":(36,38,44)},
}

# in-memory daily limit
LIMIT = {}
LIMIT_MAX = 10

def iso_now(): return dt.datetime.utcnow().isoformat()

def generate_nonce(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def pick_theme_by_today():
    return THEMES["ivory"] if (dt.datetime.utcnow().day % 2 == 0) else THEMES["night"]

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()

def text_wrap(draw, text, font, max_w, lh_mult=1.15):
    words = text.split()
    if not words: return [], 0
    lines, cur = [], words[0]
    for w in words[1:]:
        test = cur + " " + w
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * lh_mult)
    return lines, line_h * len(lines)

def draw_multiline(draw, xy, lines, font, fill, line_h):
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h

def ensure_daily_limit(chat_id):
    key = dt.datetime.utcnow().strftime("%Y-%m-%d")
    LIMIT.setdefault(key, {})
    cnt = LIMIT[key].get(chat_id, 0)
    if cnt >= LIMIT_MAX: return False
    LIMIT[key][chat_id] = cnt + 1
    return True

def build_caption(preset, day_name, fun_fact, nonce):
    link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    if preset == "tau_hai":
        body = f"🎉 Hôm nay… {day_name}.\nKhông ép bạn tin, nhưng có cớ để vui chút.\nFun fact: {fun_fact}"
    elif preset == "trung_tinh":
        body = f"📌 Hôm nay: {day_name}.\nFun fact: {fun_fact}"
    else:
        body = (f"🎂 Hôm nay là {day_name}\n"
                f"Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.\n"
                f"Fun fact: {fun_fact}")
    return f"{body}\n#viaDzDay {link}"

# ---------- Card renderer (square) ----------
def render_card_square(title, body, fun_fact, short_url):
    theme = pick_theme_by_today()
    bg, card, fg, sub, chip_color = theme["bg"], theme["card"], theme["fg"], theme["sub"], theme["chip"]
    W, H = CANVAS

    base = Image.new("RGB", CANVAS, bg)
    card_box = (PADDING, PADDING, W-PADDING, H-PADDING)

    # card image & inner
    card_img = Image.new("RGB", (card_box[2]-card_box[0], card_box[3]-card_box[1]), card)
    inner_pad = 64
    cx, cy = inner_pad, inner_pad
    cw, ch = card_img.size
    inner_w = cw - inner_pad*2
    d = ImageDraw.Draw(card_img)

    # fonts
    title_size = 86
    title_font = load_font(FONT_REG_PATH, title_size)
    def ok(f):
        l,_ = text_wrap(d, title, f, inner_w, lh_mult=1.10)
        return len(l) <= 3
    while not ok(title_font) and title_size > 48:
        title_size -= 4
        title_font = load_font(FONT_REG_PATH, title_size)

    body_font   = load_font(FONT_REG_PATH, 40)
    italic_font = load_font(FONT_ITALIC_PATH, 42)
    small_font  = load_font(FONT_REG_PATH, 34)

    # title
    t_lines, t_h = text_wrap(d, title, title_font, inner_w, lh_mult=1.10)
    t_lh = int(sum(title_font.getmetrics()) * 1.10)
    draw_multiline(d, (cx, cy), t_lines, title_font, fg, t_lh)
    cy += t_h + GAP

    # body
    b_lines, b_h = text_wrap(d, body, body_font, inner_w, lh_mult=1.35)
    b_lh = int(sum(body_font.getmetrics()) * 1.35)
    draw_multiline(d, (cx, cy), b_lines, body_font, sub, b_lh)
    cy += b_h + GAP

    # fun fact with italic tag
    tag = "Fun fact:"
    tag_w = d.textlength(tag, font=italic_font)
    f_lines, _ = text_wrap(d, fun_fact, body_font, inner_w - tag_w - 12, lh_mult=1.35)
    d.text((cx, cy), tag, font=italic_font, fill=sub)
    d.text((cx + tag_w + 12, cy), f_lines[0], font=body_font, fill=fg)
    cy += b_lh
    for ln in f_lines[1:]:
        d.text((cx, cy), ln, font=body_font, fill=fg); cy += b_lh

    # footer chips
    chip_px, chip_py = 20, 10
    def draw_chip(text, x, y):
        w = int(d.textlength(text, font=small_font) + chip_px*2)
        h = int(sum(small_font.getmetrics())*1.15 + chip_py*2)
        d.rounded_rectangle((x, y-h, x+w, y), radius=14, fill=chip_color)
        d.text((x+chip_px, y-h+chip_py), text, font=small_font, fill=sub)
        return w, h

    cy_footer = ch - inner_pad
    left_x = cx
    w1, _ = draw_chip("#viaDzDay", left_x, cy_footer)
    left_x += w1 + 12
    draw_chip("dz.day/today", left_x, cy_footer)

    # QR
    qr = qrcode.make(short_url).resize((300, 300))
    qr_bg = Image.new("RGB", (336, 336), "white")
    qr_bg.paste(qr, (18, 18))
    qr_x = cw - inner_pad - qr_bg.size[0]
    qr_y = cy_footer - qr_bg.size[1]
    card_img.paste(qr_bg, (qr_x, qr_y))

    # paste card with rounded mask
    mask = Image.new("L", card_img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,card_img.size[0], card_img.size[1]), radius=CARD_R, fill=255)
    base.paste(card_img, card_box[:2], mask)

    buf = io.BytesIO()
    base.save(buf, format="JPEG", quality=92, subsampling=1)
    buf.seek(0)
    return buf

# ---------- Telegram ----------
@app.route("/", methods=["GET"])
def index(): return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)
    if not update: return {"ok": True}

    # callbacks
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        msg  = cq.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        action, nonce = (data.split(":",1)+[""])[:2] if ":" in data else (data, "")

        if action == "share":
            send_msg(chat_id, f"Bạn share card này nhé 👉 https://dz.day/today?nonce={nonce}\n#viaDzDay")
            log_event(make_log(update, "share", f"share:{nonce}", nonce=nonce, action="share"))
        elif action == "copy":
            cap = build_caption("mia_nhe", "Ngày Bánh Crepe Toàn Cầu", "Crepe mỏng nhưng ăn nhiều vẫn mập.", nonce)
            send_msg(chat_id, cap)
            log_event(make_log(update, "copy", f"copy:{nonce}", nonce=nonce, action="copy", caption_preset="mia_nhe"))
        elif action == "suggest":
            send_msg(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
            log_event(make_log(update, "suggest_prompt", "suggest", action="suggest"))
        return {"ok": True}

    # messages
    msg = update.get("message", {})
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP >>> old update", flush=True); return {"ok": True}

    if text == "/start":
        send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😉\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(make_log(update, "start", text))

    elif text == "/today":
        if not ensure_daily_limit(chat_id):
            send_msg(chat_id, "Hôm nay bạn share chăm quá. Muốn tiếp thì rủ thêm 2 đứa vào gõ /start nhé.")
            log_event(make_log(update, "limit", text)); return {"ok": True}

        today = dt.datetime.utcnow()
        title_text = f"Ngày Bánh Crepe Toàn Cầu {today.day}/{today.month}"
        body = "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
        fun  = "Crepe mỏng nhưng ăn nhiều vẫn mập."

        nonce = generate_nonce()
        short_link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

        img_buf = render_card_square(title_text, body, fun, short_link)
        caption = build_caption("mia_nhe", "Ngày Bánh Crepe Toàn Cầu", fun, nonce)
        send_photo(chat_id, img_buf, caption=caption)   # không set parse_mode để tránh lỗi _ trong URL

        send_inline_buttons(chat_id, nonce)
        log_event(make_log(update, "today", text, nonce=nonce, caption_preset="mia_nhe", action="render"))

    elif text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            send_msg(chat_id, "Gửi kiểu này nè: /suggest Ngày thế giới ăn bún riêu")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của bạn: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
            log_event(make_log(update, "suggest", idea, action="suggest"))
    else:
        send_msg(chat_id, f"Tôi nghe chưa rõ lắm: {text}\nGõ /today hoặc /suggest cho tử tế.")
        log_event(make_log(update, "unknown", text))

    return {"ok": True}

def send_msg(chat_id, text, parse_mode=None):
    if not API_URL: return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
    print("SEND >>>", r.text, flush=True)

def send_photo(chat_id, img_buf, caption=None):
    if not API_URL: return
    files = {"photo": ("dzcard.jpg", img_buf, "image/jpeg")}
    data = {"chat_id": chat_id}
    if caption: data["caption"] = caption  # không gán parse_mode
    r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=30)
    print("PHOTO >>>", r.text, flush=True)

def send_inline_buttons(chat_id, nonce):
    if not API_URL: return
    kb = {
        "inline_keyboard":[[
            {"text":"📤 Share Story","callback_data":f"share:{nonce}"},
            {"text":"📋 Copy Caption","callback_data":f"copy:{nonce}"},
            {"text":"💡 Suggest Day","callback_data":"suggest"},
        ]]
    }
    payload = {"chat_id": chat_id, "text": "\u2063", "reply_markup": json.dumps(kb)}  # zero-width char
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
    print("BTN >>>", r.text, flush=True)

# ---------- Logging to Google Apps Script ----------
def make_log(update, command, text, nonce="", action="", caption_preset=""):
    msg = update.get("message") or update.get("callback_query", {}).get("message", {}) or {}
    if "message" in update:
        user = update["message"].get("from", {})
    else:
        user = update.get("callback_query", {}).get("from", {}) or {}
    return {
        "chat_id": msg.get("chat", {}).get("id"),
        "username": (user.get("username") or user.get("first_name") or "user"),
        "text": text,
        "command": command,
        "raw": update,
        "source": "telegram",
        "nonce": nonce,
        "action": action,
        "caption_preset": caption_preset,
        "timestamp": iso_now(),
    }

def log_event(payload):
    if not LOG_URL: return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=10)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

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
