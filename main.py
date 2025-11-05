# main.py — DzDayBot (stable P0 mobile-card)

from flask import Flask, request
import os, requests, time, threading, io, textwrap, random, string, datetime, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = Flask(__name__)

# ===== ENV =====
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SELF_URL = os.getenv("SELF_URL")  # MUST include scheme, e.g. https://dzday-production.up.railway.app
LOG_URL = os.getenv("LOG_URL")    # Google Apps Script endpoint

PLAYFAIR_URL = os.getenv("PLAYFAIR_URL", "https://raw.githubusercontent.com/latoicaobang/dzday/main/assets/Playfair.ttf")
PLAYFAIR_ITALIC_URL = os.getenv("PLAYFAIR_ITALIC_URL", "https://raw.githubusercontent.com/latoicaobang/dzday/main/assets/Playfair-Italic.ttf")

MAX_UPDATE_AGE = 90  # seconds
DAILY_LIMIT = 10

# ===== In-mem counters =====
daily_counts = {}  # { (chat_id, 'YYYY-MM-DD'): count }

# ===== Helpers =====
def today_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def vn_day_month(d: datetime.date):
    return f"{d.day}/{d.month}"

def generate_nonce(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def shortlink_with_nonce(nonce):
    return f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

def check_daily_limit(chat_id: int):
    key = (chat_id, datetime.date.today().isoformat())
    c = daily_counts.get(key, 0)
    if c >= DAILY_LIMIT:
        return False
    daily_counts[key] = c + 1
    return True

def build_caption(preset, day_name, fun_fact, nonce):
    link = shortlink_with_nonce(nonce)
    if preset not in ("mia_nhe", "tau_hai", "trung_tinh"):
        preset = "mia_nhe"

    title_line = f"🎂 Hôm nay là {day_name}"
    if preset == "mia_nhe":
        body = "Không ai bắt bạn tin, nhưng nhân loại luôn cần cái cớ để vui."
    elif preset == "tau_hai":
        body = "Đời quá ngắn để bỏ lỡ dịp bày trò."
    else:
        body = "Ghi nhận một ngày khá thú vị trong lịch nhân loại."

    return f"{title_line}\n{body}\n*Fun fact:* {fun_fact}\n#viaDzDay {link}"

def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True)
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=6)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

def make_log(update, command, text, nonce="", caption_preset="mia_nhe", action="", extra=None):
    msg = (update.get("message")
           or update.get("callback_query", {}).get("message")
           or {})
    user = (msg.get("from")
            or update.get("callback_query", {}).get("from")
            or {})
    chat = msg.get("chat") or {}
    base = {
        "timestamp": today_iso(),
        "chat_id": chat.get("id"),
        "username": user.get("username") or user.get("first_name") or "",
        "text": text,
        "command": command,
        "nonce": nonce,
        "caption_preset": caption_preset,
        "action": action,
        "raw": update
    }
    if extra:
        base.update(extra)
    return base

# ===== Font loader (robust) =====
_font_cache = {}

def _fetch_font(url, size):
    try:
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        return ImageFont.truetype(io.BytesIO(r.content), size=size)
    except Exception as e:
        print("FONT ERR >>>", e, flush=True)
        return None

def load_font(size=48, italic=False):
    key = (size, italic)
    if key in _font_cache:
        return _font_cache[key]

    # 1) Try Playfair (GitHub raw)
    url = PLAYFAIR_ITALIC_URL if italic else PLAYFAIR_URL
    f = _fetch_font(url, size)
    if f:
        _font_cache[key] = f
        return f

    # 2) Try DejaVu in container
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            f = ImageFont.truetype(path, size=size)
            _font_cache[key] = f
            return f
        except Exception:
            pass

    # 3) Fallback default
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f

# ===== Text wrapping that fits width with ellipsis =====
def wrap_text_to_width(draw, text, font, max_width, max_lines):
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            wbox = draw.textbbox((0,0), test, font=font)
            if wbox[2] - wbox[0] <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
                if len(lines) >= max_lines:
                    break
        if len(lines) >= max_lines:
            break
        if cur:
            lines.append(cur)
    # clamp + ellipsis
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    # ensure last line shows ellipsis if content might be truncated
    joined = " ".join(text.split())
    rejoined = " ".join(lines)
    if len(lines) and joined != rejoined:
        last = lines[-1]
        while True:
            test = (last + "…").strip()
            wbox = draw.textbbox((0,0), test, font=font)
            if wbox[2] - wbox[0] <= max_width and len(last) > 1:
                lines[-1] = test
                break
            last = last[:-1]
            if not last:
                lines[-1] = "…"
                break
    return lines

# ===== Card renderer (1080x1350) mobile-first =====
def render_card_square(title, body, funfact, link_text):
    W, H = 1080, 1350
    P = 64  # padding
    BG = (248, 247, 245)  # warm paper
    TITLE = (24, 24, 26)
    TEXT = (40, 40, 44)
    CHIP_BG = (229, 232, 236)
    CHIP_FG = (55, 58, 63)
    ACCENT = (26, 115, 232)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # background subtle texture
    overlay = Image.new("RGBA", (W, H), (255,255,255,0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, H-280, W, H), fill=(0,0,0,18))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Fonts
    title_f = load_font(76, italic=False)
    body_f = load_font(44, italic=False)
    fun_f = load_font(42, italic=True)
    chip_f = load_font(36, italic=False)
    link_f = load_font(40, italic=False)

    # Title block (max 3 lines)
    max_title_w = W - P*2
    title_lines = wrap_text_to_width(d, title, title_f, max_title_w, 3)
    y = P + 8
    for line in title_lines:
        d.text((P, y), line, font=title_f, fill=TITLE)
        y += title_f.getbbox(line)[3] + 6

    y += 12

    # Body block (max 6 lines)
    max_body_w = W - P*2
    body_lines = wrap_text_to_width(d, body, body_f, max_body_w, 6)
    for line in body_lines:
        d.text((P, y), line, font=body_f, fill=TEXT)
        y += body_f.getbbox(line)[3] + 4

    y += 12

    # Fun fact (max 3 lines)
    ff_prefix = "Fun fact: "
    ff_lines = wrap_text_to_width(d, ff_prefix + funfact, fun_f, max_body_w, 3)
    for line in ff_lines:
        d.text((P, y), line, font=fun_f, fill=TEXT)
        y += fun_f.getbbox(line)[3] + 2

    # Footer chips
    cy = H - P - 20

    def draw_chip(text, x, baseline_y):
        tw = d.textbbox((0,0), text, font=chip_f)[2]
        padx, pady = 24, 14
        w, h = tw + padx*2, chip_f.size + pady*2
        # rect (use CHIP_BG, not the function name!)
        d.rounded_rectangle((x, baseline_y-h, x+w, baseline_y), radius=16, fill=CHIP_BG)
        d.text((x+padx, baseline_y-h+pady-2), text, font=chip_f, fill=CHIP_FG)
        return w, h

    left_x = P
    w1, _ = draw_chip("#viaDzDay", left_x, cy)
    left_x += w1 + 12
    w2, _ = draw_chip(link_text.replace("https://", ""), left_x, cy)

    # QR (optional: placeholder tiny square right)
    # d.rectangle((W-P-140, cy-140, W-P, cy), fill=(255,255,255), outline=(220,220,220))
    # d.text((W-P-132, cy-90), "QR", font=chip_f, fill=(160,160,160))

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92, optimize=True)
    out.seek(0)
    return out

# ===== Telegram senders =====
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

def send_photo(chat_id, photo_bytes, caption, reply_markup=None, parse_mode="Markdown"):
    files = {"photo": ("card.jpg", photo_bytes, "image/jpeg")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode}
    if reply_markup:
        data["reply_markup"] = reply_markup
    r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=15)
    print("PHOTO >>>", r.text, flush=True)

def inline_keyboard(nonce):
    return {
        "inline_keyboard": [[
            {"text": "📤 Share Story", "callback_data": f"share:{nonce}"},
            {"text": "📋 Copy Caption", "callback_data": f"copy:{nonce}"},
            {"text": "💡 Suggest Day", "callback_data": "suggest"}
        ]]
    }

# ===== Flask routes =====
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("UPDATE >>>", update, flush=True)

    if not update:
        return {"ok": True}

    # Handle callbacks first
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data") or ""
        message = cq.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        if data.startswith("share:"):
            nonce = data.split(":",1)[1]
            log_event(make_log(update, "today", "btn_share", nonce=nonce, action="share"))
            send_msg(chat_id, "Cứ tải ảnh rồi úp story cho lẹ. Caption đã kèm trong ảnh nhé 😉")
        elif data.startswith("copy:"):
            nonce = data.split(":",1)[1]
            caption = build_caption("mia_nhe", "Ngày Bánh Crepe Toàn Cầu", "Crepe mỏng nhưng ăn nhiều vẫn mập.", nonce)
            log_event(make_log(update, "today", "btn_copy", nonce=nonce, action="copy"))
            send_msg(chat_id, caption, parse_mode="Markdown")
        elif data == "suggest":
            log_event(make_log(update, "today", "btn_suggest", action="suggest"))
            send_msg(chat_id, "Gõ như này nè: `/suggest Ngày thế giới ăn bún riêu`", parse_mode="Markdown")
        return {"ok": True}

    # Normal messages
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    # Skip stale updates
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP >>> old update", flush=True)
        return {"ok": True}

    if text == "/start":
        send_msg(chat_id,
                 "Xin chào, mình là DzDay – giọng Dandattone (mỉa nhẹ mà thương). "
                 "Gõ /today để xem hôm nay là ngày gì nhé 😏")
        log_event(make_log(update, "start", text))
        return {"ok": True}

    if text.startswith("/suggest"):
        idea = text.replace("/suggest", "", 1).strip()
        if not idea:
            send_msg(chat_id, "Gõ như này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
        else:
            send_msg(chat_id, f"Đã ghi nhận gợi ý của bạn: “{idea}”. Mình sẽ ngẫm nghĩ rồi duyệt.")
            log_event(make_log(update, "suggest", idea, action="suggest_submit"))
        return {"ok": True}

    if text == "/today":
        # limit
        if not check_daily_limit(chat_id):
            send_msg(chat_id, "Hôm nay bạn share chăm quá. Muốn tiếp thì rủ thêm 2 bạn vào /start nhé.")
            log_event(make_log(update, "today", "limit_hit", action="limit"))
            return {"ok": True}

        # sample content (placeholder; sau này gắn data source)
        today = datetime.date.today()
        titledate = f"Ngày Bánh Crepe Toàn Cầu {vn_day_month(today)}"
        body = "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang."
        fun = "Crepe mỏng nhưng ăn nhiều vẫn mập."
        nonce = generate_nonce()
        short_link = shortlink_with_nonce(nonce)
        caption = f"🎂 *{titledate}*\n{body}\n*Fun fact:* {fun}\n#viaDzDay {short_link}"

        # render + send photo (single message)
        try:
            img_buf = render_card_square(titledate, body, fun, short_link)
            kb = inline_keyboard(nonce)
            send_photo(chat_id, img_buf, caption, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            # never be silent
            print("RENDER ERR >>>", e, flush=True)
            send_msg(chat_id, caption, parse_mode="Markdown", reply_markup=inline_keyboard(nonce))

        # log
        log_event(make_log(update, "today", "/today", nonce=nonce, caption_preset="mia_nhe", action="today"))
        return {"ok": True}

    # fallback
    send_msg(chat_id, "Mình chưa rõ ý bạn. Gõ /today hoặc /suggest nhé.")
    log_event(make_log(update, "unknown", text))
    return {"ok": True}

# ===== keep warm =====
def keep_warm():
    if not SELF_URL:
        return
    # ensure scheme
    url = SELF_URL.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    while True:
        try:
            requests.get(url, timeout=5)
            print("WARM >>> ping", flush=True)
        except Exception as e:
            print("WARM ERR >>>", e, flush=True)
        time.sleep(25)

threading.Thread(target=keep_warm, daemon=True).start()
