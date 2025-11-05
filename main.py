# main.py (hardened)
import os, io, json, random, string
import datetime as dt
import requests
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import qrcode

# ========= Env =========
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
LOG_URL   = (os.getenv("LOG_URL") or "").strip()
PORT      = int(os.getenv("PORT", "8000"))
API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Fail-fast: bắt buộc có BOT_TOKEN
if not BOT_TOKEN:
    # In rõ để nhìn thấy ngay trên Railway log
    raise RuntimeError("ENV ERROR: BOT_TOKEN is missing. Set variable BOT_TOKEN for this service and redeploy.")

# ========= App =========
app = Flask(__name__)

# ========= Assets / Fonts =========
ASSETS_DIR       = os.getenv("ASSETS_DIR", "assets")
FONT_REG_PATH    = os.path.join(ASSETS_DIR, "Playfair.ttf")
FONT_ITALIC_PATH = os.path.join(ASSETS_DIR, "Playfair-Italic.ttf")

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size=size)
    except Exception as e:
        print(f"FONT WARN >>> {e} (fallback default)", flush=True)
        return ImageFont.load_default()

# ========= Theme & Layout =========
CANVAS  = (1080, 1350)  # 4:5
PADDING = 64
CARD_R  = 48
GAP     = 24

THEMES = [
    ((238,232,226), (255,255,255), (36,33,30), (92,88,84), (243,241,239)),
    ((245,242,239), (255,255,253), (29,29,29), (100,97,93), (236,233,230)),
]
def pick_theme():
    i = dt.date.today().toordinal() % len(THEMES)
    bg, card, fg, sub, chip = THEMES[i]
    return {"bg": bg, "card": card, "fg": fg, "sub": sub, "chip": chip}

# ========= Text helpers =========
def text_wrap(draw, text, font, max_w, lh_mult=1.3):
    if not text: return [], 0
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * lh_mult)
    return lines, line_h * len(lines)

def draw_multiline(draw, xy, lines, font, fill, line_h):
    x, y = xy
    for ln in lines:
        draw.text((x, y), ln, font=font, fill=fill)
        y += line_h

# ========= Renderer =========
def render_card_square(title, body, fun_fact, short_url):
    theme = pick_theme()
    bg, card, fg, sub, chip_color = theme["bg"], theme["card"], theme["fg"], theme["sub"], theme["chip"]
    W, H = CANVAS

    base = Image.new("RGB", CANVAS, bg)
    card_box = (PADDING, PADDING, W - PADDING, H - PADDING)

    card_img = Image.new("RGB", (card_box[2]-card_box[0], card_box[3]-card_box[1]), card)
    inner_pad = 64
    d = ImageDraw.Draw(card_img)
    cw, ch = card_img.size
    cx, cy = inner_pad, inner_pad

    # Cột QR riêng bên phải
    QR_SIZE, QR_FRAME = 300, 36
    qr_total = QR_SIZE + QR_FRAME
    RIGHT_GUTTER = qr_total + 40

    # Fonts & fit
    title_size = 86
    title_font = load_font(FONT_REG_PATH, title_size)
    while True:
        t_lines, _ = text_wrap(d, title, title_font, cw - inner_pad*2 - RIGHT_GUTTER, lh_mult=1.10)
        if len(t_lines) <= 3 or title_size <= 48: break
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
    d.text((cx + tag_w + 12, cy), f_lines[0] if f_lines else "", font=body_font, fill=fg)
    cy2 = cy + b_lh
    for ln in f_lines[1:]:
        d.text((cx, cy2), ln, font=body_font, fill=fg); cy2 += b_lh

    # Footer chips
    def chip(text, x, y):
        pad_x, pad_y = 20, 10
        w = int(d.textlength(text, font=small_font) + pad_x*2)
        h = int(sum(small_font.getmetrics())*1.15 + pad_y*2)
        d.rounded_rectangle((x, y-h, x+w, y), radius=14, fill=chip_color)
        d.text((x+pad_x, y-h+pad_y), text, font=small_font, fill=sub)
        return w, h

    cy_footer = ch - inner_pad
    left_x = cx
    w1, _  = chip("#viaDzDay", left_x, cy_footer)
    left_x += w1 + 12
    chip("dz.day/today", left_x, cy_footer)

    # QR
    qr_img = qrcode.make(short_url).resize((QR_SIZE, QR_SIZE))
    qr_bg  = Image.new("RGB", (qr_total, qr_total), (255,255,255))
    off    = QR_FRAME // 2
    qr_bg.paste(qr_img, (off, off))
    qr_x = cw - inner_pad - qr_total
    qr_y = cy_footer - qr_total
    card_img.paste(qr_bg, (qr_x, qr_y))

    # Paste card (rounded)
    mask = Image.new("L", card_img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,card_img.size[0], card_img.size[1]), radius=CARD_R, fill=255)
    base.paste(card_img, card_box[:2], mask)

    buf = io.BytesIO()
    base.save(buf, format="JPEG", quality=92, subsampling=1)
    buf.seek(0)
    return buf

# ========= Caption & utils =========
def vn_today_str():
    now = dt.datetime.utcnow() + dt.timedelta(hours=7)
    return f"{now.day}/{now.month}"

def nonce(n=10):
    import string as s
    return "".join(random.choice(s.ascii_lowercase + s.digits) for _ in range(n))

def build_caption(title, fun, n):
    return "\n".join([
        f"🎂 Hôm nay là {title}",
        "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.",
        f"Fun fact: {fun}",
        "#viaDzDay https://dz.day/today?nonce=" + n + "&utm_source=telegram&utm_medium=share_button",
    ])

# ========= Telegram wrappers (log chi tiết) =========
def tg_post(method, data=None, files=None):
    url = f"{API_URL}/{method}"
    try:
        r = requests.post(url, data=data or {}, files=files, timeout=30)
        print(f"TG >>> {method} {r.status_code} {r.text[:300]}", flush=True)
        return r
    except Exception as e:
        print(f"TG ERR >>> {method}: {e}", flush=True)

def send_msg(chat_id, text, buttons=None):
        data = {"chat_id": chat_id, "text": text}
        if buttons:
            data["reply_markup"] = json.dumps(buttons)
        tg_post("sendMessage", data=data)

def send_photo(chat_id, img_buf, caption=None, buttons=None):
        files = {"photo": ("dzcard.jpg", img_buf, "image/jpeg")}
        data  = {"chat_id": chat_id}
        if caption: data["caption"] = caption
        if buttons: data["reply_markup"] = json.dumps(buttons)
        tg_post("sendPhoto", data=data, files=files)

# ========= Logging to Sheet (11 cột) =========
def log_event(payload):
    if not LOG_URL: return
    try:
        requests.post(LOG_URL, json=payload, timeout=8)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

def mklog(update, type_, command="", raw=None, nonce_val="", action="", caption_preset=""):
    now = dt.datetime.utcnow().isoformat()
    msg = update.get("message") or update.get("callback_query", {}).get("message", {})
    chat = msg.get("chat", {})
    user = (update.get("message") or update.get("callback_query", {})).get("from", {})
    return {
        "ts": now,
        "chat_id": chat.get("id"),
        "chat_name": chat.get("first_name") or chat.get("title"),
        "username": user.get("username"),
        "command": command,
        "raw": raw or update,
        "source": "telegram",
        "nonce": nonce_val,
        "action": action,
        "caption_preset": caption_preset,
        "iso_ts": now,
        "type": type_,
    }

# ========= Routes =========
@app.get("/")
def index(): return "DzDay up"

@app.get("/health")
def health():
    return jsonify(ok=True, has_token=bool(BOT_TOKEN), api=len(API_URL) > 0)

@app.get("/ping")
def ping():
    print("WARM >>> ping", flush=True)
    return jsonify(ok=True)

@app.post("/webhook")
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    print("UPDATE >>>", update, flush=True)

    # Callback
    if "callback_query" in update:
        cq = update["callback_query"]
        cid = cq["message"]["chat"]["id"]
        data = cq.get("data", "")
        if data.startswith("copy:"):
            n = data.split(":", 1)[1]
            title_text = f"Ngày Bánh Crepe Toàn Cầu {vn_today_str()}"
            cap = build_caption(title_text, "Crepe mỏng nhưng ăn nhiều vẫn mập.", n)
            send_msg(cid, cap)
            log_event(mklog(update, "cb_copy", command="copy", nonce_val=n, action="copy_caption"))
        elif data.startswith("share:"):
            n = data.split(":", 1)[1]
            link = f"https://dz.day/today?nonce={n}&utm_source=telegram&utm_medium=share_button"
            send_msg(cid, f"Bạn share card này nhé 👉 {link}")
            log_event(mklog(update, "cb_share", command="share", nonce_val=n, action="share_link"))
        elif data == "suggest":
            send_msg(cid, "Gợi ý bằng lệnh: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
            log_event(mklog(update, "cb_suggest", command="suggest"))
        return jsonify(ok=True)

    # Message
    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not text: return jsonify(ok=True)

    if text == "/start":
        send_msg(chat_id,
                 "Xin chào, tôi là DzDay – giọng Dandattone, hơi mía nhưng chân thành 😊.\n"
                 "Gõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(mklog(update, "start", command="/start"))
        return jsonify(ok=True)

    if text == "/today":
        n = nonce()
        today = vn_today_str()
        title_text = f"Ngày Bánh Crepe Toàn Cầu {today}"
        body = "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
        fun  = "Crepe mỏng nhưng ăn nhiều vẫn mập."
        link = f"https://dz.day/today?nonce={n}&utm_source=telegram&utm_medium=share_button"

        img = render_card_square(title_text, body, fun, link)
        cap = build_caption(title_text, fun, n)
        kb = {
            "inline_keyboard": [[
                {"text":"📤 Share Story","callback_data":f"share:{n}"},
                {"text":"📋 Copy Caption","callback_data":f"copy:{n}"},
                {"text":"💡 Suggest Day","callback_data":"suggest"},
            ]]
        }
        send_photo(chat_id, img, caption=cap, buttons=kb)
        log_event(mklog(update, "today", command="/today", nonce_val=n, action="render", caption_preset="playfair"))
        return jsonify(ok=True)

    if text.startswith("/suggest"):
        idea = text[len("/suggest"):].strip()
        if not idea:
            send_msg(chat_id, "Bạn gõ: /suggest Tên ngày nhé.\nVí dụ: /suggest Ngày thế giới ăn bún riêu")
        else:
            send_msg(chat_id, f"Đã ghi nhận: “{idea}”. Cảm ơn bạn!")
        log_event(mklog(update, "suggest", command="/suggest", raw=text))
        return jsonify(ok=True)

    send_msg(chat_id, "Gõ /today để lấy card ngày hôm nay nhé.")
    log_event(mklog(update, "fallback", command=text))
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
