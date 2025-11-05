# main.py — DzDayBot (stable hotfix)
# - Auto setWebhook on boot (+ /set_webhook, /webhook_info)
# - Fix PIL rounded_rectangle fill (no more "color must be int or tuple")
# - Mobile-first card 1080x1350, smart text-wrap + ellipsis
# - Inline buttons + nonce + caption builder + 10 exports/day limit
# - Google Apps Script logging (11 cột đã dùng trước đó)

from flask import Flask, request
import os, requests, time, threading, io, textwrap, random, string, datetime as dt

from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = Flask(__name__)

# -------- ENV
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL  = os.getenv("SELF_URL")      # eg: https://your-app.onrender.com
LOG_URL   = os.getenv("LOG_URL")       # Google Apps Script endpoint
MAX_UPDATE_AGE = 90

# Optional font urls (Playfair uploaded to your repo/cdn)
PLAYFAIR_URL       = os.getenv("PLAYFAIR_URL")       # e.g. https://raw.githubusercontent.com/.../assets/Playfair.ttf
PLAYFAIR_ITALIC_URL= os.getenv("PLAYFAIR_ITALIC_URL")# e.g. https://raw.githubusercontent.com/.../assets/Playfair-Italic.ttf

# Cache in-memory
DAILY_COUNT = {}  # {(chat_id, YYYYMMDD): int}

# --------- HELPERS: TELEGRAM
def send_msg(chat_id, text, parse_mode=None, reply_markup=None):
    if not BOT_TOKEN:
        print("NO TOKEN >>>", flush=True)
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    if reply_markup: payload["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
    print("SEND >>>", r.text[:200], flush=True)

def send_photo(chat_id, photo_bytes, caption=None, parse_mode=None, reply_markup=None):
    if not BOT_TOKEN:
        print("NO TOKEN >>>", flush=True)
        return
    files = {"photo": ("card.jpg", photo_bytes, "image/jpeg")}
    data  = {"chat_id": str(chat_id)}
    if caption: data["caption"] = caption
    if parse_mode: data["parse_mode"] = parse_mode
    if reply_markup: data["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=30)
    print("PHOTO >>>", r.text[:400], flush=True)

def send_callback_answer(callback_id, text=None, show_alert=False):
    if not BOT_TOKEN: return
    payload = {"callback_query_id": callback_id, "show_alert": show_alert}
    if text: payload["text"] = text
    requests.post(f"{API_URL}/answerCallbackQuery", json=payload, timeout=10)

# --------- HELPERS: LOG
def make_log(update, command, text, extra=None):
    msg = update.get("message") or update.get("callback_query", {}).get("message") or {}
    user = (update.get("message") or update.get("callback_query", {}).get("from") or {}).get("from") or (update.get("message", {}) or {}).get("from") or {}
    base = {
        "chat_id": msg.get("chat", {}).get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "nonce": (extra or {}).get("nonce") or "",
        "caption_preset": (extra or {}).get("caption_preset") or "",
        "action": (extra or {}).get("action") or "",
        "timestamp": dt.datetime.utcnow().isoformat()+"Z",
        "raw": update,
    }
    return base

def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=8)
        print("LOG >>>", r.status_code, r.text[:160], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

# --------- HELPERS: NONCE & LIMIT
def generate_nonce(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def check_daily_limit(chat_id, max_per_day=10):
    day = dt.datetime.now().strftime("%Y%m%d")
    key = (chat_id, day)
    cnt = DAILY_COUNT.get(key, 0)
    if cnt >= max_per_day:
        return False
    DAILY_COUNT[key] = cnt + 1
    return True

# --------- CAPTION BUILDER
def build_caption(preset, day_name, fun_fact, nonce):
    short = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
    lines_mia = [
        f"🎂 *Hôm nay là {day_name}*",
        "Không ai bắt bạn tin, nhưng thôi kệ—có cớ vui là được.",
        f"*Fun fact:* {fun_fact}",
        f"#viaDzDay {short}"
    ]
    lines_tau = [
        f"🎉 *{day_name}* á? Share cho vui nhà vui cửa nè.",
        f"Fun fact: {fun_fact}",
        f"#viaDzDay {short}"
    ]
    lines_trung = [
        f"🗓️ *{day_name}*",
        f"Thông tin nhanh: {fun_fact}",
        f"#viaDzDay {short}"
    ]
    if preset == "tau_hai":
        return "\n".join(lines_tau)
    if preset == "trung_tinh":
        return "\n".join(lines_trung)
    return "\n".join(lines_mia)

# --------- FONT LOADER (Playfair fallback to PIL default)
def load_font(url, size):
    try:
        if not url:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return ImageFont.truetype(io.BytesIO(r.content), size)
    except Exception as e:
        print("FONT ERR >>>", e, flush=True)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size)

# --------- CARD RENDER (1080x1350, mobile-first)
def render_card_square(title, body, fun_fact, short_link):
    W, H = 1080, 1350
    MARGIN = 64
    BG = (248, 246, 241)         # warm paper
    FG = (20, 20, 20)
    SUB = (90, 90, 90)
    CHIP_BG = (230, 230, 230)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # Decorative shadow top
    overlay = Image.new("RGBA", (W, 280), (0,0,0,0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((-200, -220, W+200, 400), fill=(0,0,0,25))
    overlay = overlay.filter(ImageFilter.GaussianBlur(24))
    im.paste(overlay, (0,0), overlay)

    # Fonts
    title_f = load_font(PLAYFAIR_URL, 84)
    body_f  = load_font(PLAYFAIR_URL, 40)
    small_f = load_font(PLAYFAIR_URL, 34)

    # Title
    max_title_w = W - 2*MARGIN
    title_wrapped = smart_wrap(title, title_f, max_title_w, max_lines=3)
    cur_y = MARGIN + 16
    d.multiline_text((MARGIN, cur_y), title_wrapped, font=title_f, fill=FG, spacing=6)
    cur_y += text_height(title_wrapped, title_f, spacing=6) + 24

    # Body
    max_body_w = W - 2*MARGIN
    body_wrapped = smart_wrap(body, body_f, max_body_w, max_lines=8)
    d.multiline_text((MARGIN, cur_y), body_wrapped, font=body_f, fill=FG, spacing=8)
    cur_y += text_height(body_wrapped, body_f, spacing=8) + 18

    # Fun fact (italic-ish: just smaller + gray)
    fun_text = f"Fun fact: {fun_fact}"
    fun_wrapped = smart_wrap(fun_text, small_f, max_body_w, max_lines=3)
    d.multiline_text((MARGIN, cur_y), fun_wrapped, font=small_f, fill=SUB, spacing=6)
    # footer
    cy_footer = H - 84

    # watermark chips (FIX: use color tuple, NOT function ref)
    def chip(text, x, cy):
        pad_x, pad_y = 18, 10
        w, h = d.textbbox((0,0), text, font=small_f)[2:]
        w += pad_x*2; h += pad_y*2
        y = cy - h//2
        d.rounded_rectangle((x, y, x+w, y+h), radius=14, fill=CHIP_BG)
        d.text((x+pad_x, y+pad_y), text, font=small_f, fill=FG)
        return w, h

    left_x = MARGIN
    w1, _ = chip("#viaDzDay", left_x, cy_footer)
    chip(short_link.replace("https://", ""), left_x + w1 + 12, cy_footer)

    # Export buffer
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92, optimize=True, progressive=True)
    buf.seek(0)
    return buf

def text_height(text, font, spacing=4):
    lines = text.split("\n")
    h = 0
    for i, line in enumerate(lines):
        bbox = font.getbbox(line or " ")
        lh = bbox[3]-bbox[1]
        h += lh + (spacing if i<len(lines)-1 else 0)
    return h

def smart_wrap(text_, font, max_w, max_lines=4, ellipsis="…"):
    words = text_.split()
    lines, cur = [], ""
    d = ImageDraw.Draw(Image.new("RGB",(10,10)))
    for w in words:
        test = (cur+" "+w).strip()
        bw = d.textlength(test, font=font)
        if bw <= max_w: cur = test
        else:
            lines.append(cur); cur = w
            if len(lines) >= max_lines:
                # squeeze last line with ellipsis
                while d.textlength(cur+ellipsis, font=font) > max_w and len(cur)>1:
                    cur = cur[:-1]
                lines[-1] = lines[-1]  # keep previous
                return "\n".join(lines[:max_lines-1]+[cur+ellipsis])
    if cur: lines.append(cur)
    return "\n".join(lines[:max_lines])

# --------- WEBHOOK SETUP
def ensure_webhook():
    if not (BOT_TOKEN and SELF_URL): 
        print("WEBHOOK >>> skip (missing token or SELF_URL)", flush=True)
        return
    try:
        url = f"{SELF_URL.rstrip('/')}/webhook"
        r = requests.get(f"{API_URL}/setWebhook", params={"url": url}, timeout=10)
        print("WEBHOOK SET >>>", r.text, flush=True)
    except Exception as e:
        print("WEBHOOK ERR >>>", e, flush=True)

def get_webhook_info():
    if not BOT_TOKEN: return {}
    try:
        r = requests.get(f"{API_URL}/getWebhookInfo", timeout=10)
        return r.json()
    except Exception:
        return {}

# --------- ROUTES
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/set_webhook", methods=["GET"])
def set_webhook_route():
    ensure_webhook()
    return {"ok": True, "webhook": get_webhook_info()}

@app.route("/webhook_info", methods=["GET"])
def webhook_info_route():
    return get_webhook_info()

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json() or {}
    print("UPDATE >>>", update, flush=True)

    # callback buttons
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data") or ""
        msg  = cq.get("message") or {}
        chat = (msg.get("chat") or {})
        chat_id = chat.get("id")
        if data.startswith("share:"):
            nonce = data.split(":",1)[1]
            send_callback_answer(cq["id"], "Tạo ảnh story để bạn share nè!")
            # regenerate same card quickly
            day_name, body, fun = get_today_stub()  # same stub as /today
            short_link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"
            img_buf = render_card_square(day_name, body, fun, short_link)
            caption = build_caption("mia_nhe", day_name, fun, nonce)
            send_photo(chat_id, img_buf, caption=caption, parse_mode="Markdown")
            log_event(make_log(update, "today", "/today", {"nonce":nonce,"caption_preset":"mia_nhe","action":"share"}))
        elif data.startswith("copy:"):
            nonce = data.split(":",1)[1]
            send_callback_answer(cq["id"], "Đã chuẩn bị caption để bạn copy.")
            day_name, body, fun = get_today_stub()
            caption = build_caption("mia_nhe", day_name, fun, nonce)
            send_msg(chat_id, caption, parse_mode="Markdown")
            log_event(make_log(update, "today", "/today", {"nonce":nonce,"caption_preset":"mia_nhe","action":"copy"}))
        elif data == "suggest":
            send_callback_answer(cq["id"])
            send_msg(chat_id, "Gửi kiểu này nha: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
            log_event(make_log(update, "suggest", "/suggest", {"action":"suggest"}))
        return {"ok": True}

    # message commands
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    # block stale
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP >>> old update", flush=True)
        return {"ok": True}

    if text == "/start":
        send_msg(chat_id, "Xin chào, mình là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😏\nGõ /today để xem hôm nay nhân loại lại bịa ra ngày gì.")
        log_event(make_log(update, "start", text))
        return {"ok": True}

    if text == "/today":
        if not check_daily_limit(chat_id):
            send_msg(chat_id, "Hôm nay bạn share chăm quá. Muốn tiếp thì rủ thêm 2 bạn vào /start nhé.")
            log_event(make_log(update, "today", text, {"action":"limit"}))
            return {"ok": True}

        # Stub nội dung hôm nay (data mining sẽ cắm sau)
        day_name, body, fun = get_today_stub()
        nonce = generate_nonce()
        short_link = f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

        # Caption mặc định preset 'mia_nhe'
        caption = build_caption("mia_nhe", day_name, fun, nonce)

        # Render ảnh
        img_buf = render_card_square(day_name, body, fun, short_link)

        # Inline keyboard
        kb = {
            "inline_keyboard":[
                [
                    {"text":"📤 Share Story", "callback_data": f"share:{nonce}"},
                    {"text":"📋 Copy Caption", "callback_data": f"copy:{nonce}"},
                    {"text":"💡 Suggest Day", "callback_data": "suggest"},
                ]
            ]
        }

        # Gửi ảnh + caption
        send_photo(chat_id, img_buf, caption=caption, parse_mode="Markdown", reply_markup=kb)

        # Log
        log_event(make_log(update, "today", text, {
            "nonce": nonce,
            "caption_preset": "mia_nhe",
            "action": "generate"
        }))
        return {"ok": True}

    if text.startswith("/suggest"):
        idea = text.replace("/suggest","",1).strip()
        if not idea:
            send_msg(chat_id, "Gửi kiểu này nha: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của bạn: “{idea}”. Mình sẽ chê trước rồi mới duyệt 😌")
            log_event(make_log(update, "suggest", idea, {"action":"suggest"}))
        return {"ok": True}

    # fallback
    send_msg(chat_id, f"Mình chưa rõ: {text}\nGõ /today hoặc /suggest nhé.")
    log_event(make_log(update, "unknown", text))
    return {"ok": True}

# --------- STUB DATA (tạm thời)
def get_today_stub():
    # Ví dụ cho 5/11 (sẽ thay bằng data mining)
    today = dt.datetime.now().strftime("%-d/%-m") if hasattr(time, 'tzset') else dt.datetime.now().strftime("%d/%m")
    title = f"Ngày Bánh Crepe Toàn Cầu {today}"
    body  = "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
    fun   = "Crepe mỏng nhưng ăn nhiều vẫn mập."
    return title, body, fun

# --------- KEEP WARM + AUTO WEBHOOK
def keep_warm():
    if not SELF_URL: return
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
            print("WARM >>> ping", flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)

def auto_webhook():
    # chờ container lên hẳn rồi set
    time.sleep(2)
    ensure_webhook()

if __name__ == "__main__":
    ensure_webhook()
    threading.Thread(target=keep_warm, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)
else:
    # chạy trên gunicorn
    threading.Thread(target=keep_warm, daemon=True).start()
    threading.Thread(target=auto_webhook, daemon=True).start()
