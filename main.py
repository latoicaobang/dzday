# main.py
import os, io, json, time, datetime as dt, random, string
import requests
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import qrcode

# ---------------------------
# Env & Telegram
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
LOG_URL   = os.getenv("LOG_URL", "").strip()
PORT      = int(os.getenv("PORT", "8000"))

app = Flask(__name__)

# ---------------------------
# Assets & Typography
# ---------------------------
ASSETS_DIR       = os.getenv("ASSETS_DIR", "assets")
FONT_REG_PATH    = os.path.join(ASSETS_DIR, "Playfair.ttf")
FONT_ITALIC_PATH = os.path.join(ASSETS_DIR, "Playfair-Italic.ttf")

def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        # fallback hệ thống
        return ImageFont.load_default()

# ---------------------------
# Card layout
# ---------------------------
CANVAS   = (1080, 1350)  # 4:5 IG
PADDING  = 64
CARD_R   = 48
GAP      = 24

# Màu dùng tuple RGB để tránh lỗi "color must be int or tuple"
THEMES = [
    # bg, card, fg, sub, chip
    ((238,232,226), (255,255,255), (36,33,30), (92,88,84), (243,241,239)),
    ((245,242,239), (255,255,253), (29,29,29), (100,97,93), (236,233,230)),
]

def pick_theme_by_today():
    idx = dt.date.today().toordinal() % len(THEMES)
    bg, card, fg, sub, chip = THEMES[idx]
    return {"bg": bg, "card": card, "fg": fg, "sub": sub, "chip": chip}

# ---------------------------
# Text helpers
# ---------------------------
def text_wrap(draw: ImageDraw.ImageDraw, text, font, max_width, lh_mult=1.3):
    if not text:
        return [], 0
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # height estimate
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * lh_mult)
    total_h = line_h * len(lines)
    return lines, total_h

def draw_multiline(draw, pos, lines, font, fill, line_h):
    x, y = pos
    for ln in lines:
        draw.text((x, y), ln, font=font, fill=fill)
        y += line_h

# ---------------------------
# Renderer
# ---------------------------
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
    d = ImageDraw.Draw(card_img)

    # --- QR block (cột phải dành riêng) ---
    QR_SIZE  = 300
    QR_FRAME = 36  # khung trắng
    qr_total = QR_SIZE + QR_FRAME
    RIGHT_GUTTER = qr_total + 40  # chừa cột phải cho QR + khoảng thở

    # fonts
    title_size = 86
    title_font = load_font(FONT_REG_PATH, title_size)

    def title_fit(font):
        l, _ = text_wrap(d, title, font, (cw - inner_pad*2 - RIGHT_GUTTER), lh_mult=1.10)
        return len(l) <= 3

    while not title_fit(title_font) and title_size > 48:
        title_size -= 4
        title_font = load_font(FONT_REG_PATH, title_size)

    body_font   = load_font(FONT_REG_PATH, 40)
    italic_font = load_font(FONT_ITALIC_PATH, 42)
    small_font  = load_font(FONT_REG_PATH, 34)

    inner_w = cw - inner_pad*2 - RIGHT_GUTTER

    # Title
    t_lines, t_h = text_wrap(d, title, title_font, inner_w, lh_mult=1.10)
    t_lh = int(sum(title_font.getmetrics()) * 1.10)
    draw_multiline(d, (cx, cy), t_lines, title_font, fg, t_lh)
    cy += t_h + GAP

    # Body
    b_lines, b_h = text_wrap(d, body, body_font, inner_w, lh_mult=1.35)
    b_lh = int(sum(body_font.getmetrics()) * 1.35)
    draw_multiline(d, (cx, cy), b_lines, body_font, sub, b_lh)
    cy += b_h + GAP

    # Fun fact
    tag = "Fun fact:"
    tag_w = d.textlength(tag, font=italic_font)
    f_lines, _ = text_wrap(d, fun_fact, body_font, inner_w - tag_w - 12, lh_mult=1.35)
    d.text((cx, cy), tag, font=italic_font, fill=sub)
    d.text((cx + tag_w + 12, cy), f_lines[0], font=body_font, fill=fg)
    cy2 = cy + b_lh
    for ln in f_lines[1:]:
        d.text((cx, cy2), ln, font=body_font, fill=fg); cy2 += b_lh

    # Footer chips
    def draw_chip(text, x, y):
        chip_px, chip_py = 20, 10
        w = int(d.textlength(text, font=small_font) + chip_px*2)
        h = int(sum(small_font.getmetrics())*1.15 + chip_py*2)
        d.rounded_rectangle((x, y-h, x+w, y), radius=14, fill=chip_color)
        d.text((x+chip_px, y-h+chip_py), text, font=small_font, fill=sub)
        return w, h

    cy_footer = ch - inner_pad
    left_x = cx
    w1, _  = draw_chip("#viaDzDay", left_x, cy_footer)
    left_x += w1 + 12
    draw_chip("dz.day/today", left_x, cy_footer)

    # QR (góc phải dưới)
    qr_img = qrcode.make(short_url).resize((QR_SIZE, QR_SIZE))
    qr_bg  = Image.new("RGB", (qr_total, qr_total), (255,255,255))
    off    = QR_FRAME // 2
    qr_bg.paste(qr_img, (off, off))
    qr_x = cw - inner_pad - qr_total
    qr_y = cy_footer - qr_total
    card_img.paste(qr_bg, (qr_x, qr_y))

    # paste card bo góc
    mask = Image.new("L", card_img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,card_img.size[0], card_img.size[1]), radius=CARD_R, fill=255)
    base.paste(card_img, card_box[:2], mask)

    buf = io.BytesIO()
    base.save(buf, format="JPEG", quality=92, subsampling=1)
    buf.seek(0)
    return buf

# ---------------------------
# Caption & utils
# ---------------------------
def vn_today_str():
    now = dt.datetime.utcnow() + dt.timedelta(hours=7)  # VN time
    return f"{now.day}/{now.month}"

def generate_nonce(n=10):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))

def build_caption(title, fun, nonce):
    # Không dùng parse_mode để tránh lỗi; giữ plain text
    lines = [
        f"🎂 Hôm nay là {title}",
        "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.",
        f"Fun fact: {fun}",
        "#viaDzDay https://dz.day/today?nonce=" + nonce + "&utm_source=telegram&utm_medium=share_button"
    ]
    return "\n".join(lines)

# ---------------------------
# Telegram wrappers
# ---------------------------
def send_msg(chat_id, text, buttons=None):
    if not API_URL: return
    data = {"chat_id": chat_id, "text": text}
    if buttons:
        data["reply_markup"] = json.dumps(buttons)
    r = requests.post(f"{API_URL}/sendMessage", data=data, timeout=30)
    print("MSG >>>", r.text, flush=True)

def send_photo(chat_id, img_buf, caption=None, buttons=None):
    if not API_URL: return
    files = {"photo": ("dzcard.jpg", img_buf, "image/jpeg")}
    data  = {"chat_id": chat_id}
    if caption: data["caption"] = caption
    if buttons: data["reply_markup"] = json.dumps(buttons)
    r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=30)
    print("PHOTO >>>", r.text, flush=True)

# ---------------------------
# Logging 11 cột (Apps Script)
# ---------------------------
def log_event(payload: dict):
    try:
        if not LOG_URL: return
        requests.post(LOG_URL, json=payload, timeout=8)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

def make_log(update, type_, command="", raw=None, nonce="", action="", caption_preset=""):
    now = dt.datetime.utcnow().isoformat()
    chat = update.get("message", update.get("callback_query", {})).get("chat", {})
    frm  = update.get("message", {}).get("from", update.get("callback_query", {}).get("from", {}))
    return {
        "ts": now,
        "chat_id": chat.get("id"),
        "chat_name": chat.get("first_name") or chat.get("title"),
        "username": frm.get("username"),
        "command": command,
        "raw": raw or update,
        "source": "telegram",
        "nonce": nonce,
        "action": action,
        "caption_preset": caption_preset,
        "iso_ts": now,
        "type": type_,
    }

# ---------------------------
# Flask routes
# ---------------------------
@app.get("/")
def index():
    return "DzDay up"

@app.get("/ping")
def ping():
    print("WARM >>> ping", flush=True)
    return jsonify(ok=True)

@app.post("/webhook")
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    print("UPDATE >>>", data, flush=True)

    # callback buttons
    if "callback_query" in data:
        cq   = data["callback_query"]
        cid  = cq["message"]["chat"]["id"]
        dval = cq.get("data","")
        if dval.startswith("copy:"):
            nonce = dval.split(":",1)[1]
            title_text = f"Ngày Bánh Crepe Toàn Cầu {vn_today_str()}"
            caption = build_caption(title_text, "Crepe mỏng nhưng ăn nhiều vẫn mập.", nonce)
            send_msg(cid, caption)
            log_event(make_log(data, "cb_copy", command="copy", nonce=nonce, action="copy_caption"))
        elif dval.startswith("share:"):
            nonce = dval.split(":",1)[1]
            link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
            send_msg(cid, f"Bạn share card này nhé 👉 {link}")
            log_event(make_log(data, "cb_share", command="share", nonce=nonce, action="share_link"))
        elif dval == "suggest":
            send_msg(cid, "Gợi ý bằng lệnh: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
            log_event(make_log(data, "cb_suggest", command="suggest"))
        return jsonify(ok=True)

    # messages
    msg  = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = (msg.get("text") or "").strip()

    if not text:
        return jsonify(ok=True)

    if text == "/start":
        send_msg(chat_id, "Xin chào, tôi là DzDay – giọng Dandattone, hơi mía nhưng chân thành 😊.\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(make_log(data, "start", command="/start"))
        return jsonify(ok=True)

    if text == "/today":
        # Nội dung mẫu
        today_label = vn_today_str()
        title_text = f"Ngày Bánh Crepe Toàn Cầu {today_label}"
        body = "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
        fun  = "Crepe mỏng nhưng ăn nhiều vẫn mập."

        nonce = generate_nonce()
        short_link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

        img_buf = render_card_square(title_text, body, fun, short_link)
        caption = build_caption(title_text, fun, nonce)

        kb = {
            "inline_keyboard":[
                [
                    {"text":"📤 Share Story","callback_data":f"share:{nonce}"},
                    {"text":"📋 Copy Caption","callback_data":f"copy:{nonce}"},
                    {"text":"💡 Suggest Day","callback_data":"suggest"},
                ]
            ]
        }
        send_photo(chat_id, img_buf, caption=caption, buttons=kb)
        log_event(make_log(data, "today", command="/today", nonce=nonce, action="render", caption_preset="playfair"))
        return jsonify(ok=True)

    if text.startswith("/suggest"):
        idea = text[len("/suggest"):].strip()
        if not idea:
            send_msg(chat_id, "Bạn gõ: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
        else:
            send_msg(chat_id, f"Đã ghi nhận: “{idea}”. Cảm ơn bạn!")
        log_event(make_log(data, "suggest", command="/suggest", raw=text))
        return jsonify(ok=True)

    # fallback
    send_msg(chat_id, "Gõ /today để lấy card ngày hôm nay nhé.")
    log_event(make_log(data, "fallback", command=text))
    return jsonify(ok=True)

# ---------------------------
# Boot
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
