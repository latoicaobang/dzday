# main.py — DzDay (DzCard v2.1, Playfair Display, VN date, neutral tone)

from flask import Flask, request
import os, io, json, time, random, string, threading, datetime as dt
import requests
from PIL import Image, ImageDraw, ImageFont
import qrcode

app = Flask(__name__)

# ===== ENV =====
BOT_TOKEN   = os.getenv("TELEGRAM_TOKEN")
API_URL     = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
SELF_URL    = os.getenv("SELF_URL")        # https://<app>.up.railway.app/
LOG_URL     = os.getenv("LOG_URL")         # Google Apps Script endpoint
MAX_UPDATE_AGE = 90

# ===== Font paths (Playfair Display) =====
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent

# Tìm các khả năng đặt tên file phổ biến
FONT_CANDIDATES_REG = [
    BASE_DIR / "assets" / "Playfair.ttf",
    BASE_DIR / "assets" / "PlayfairDisplay-Regular.ttf",
    BASE_DIR / "assets" / "PlayfairDisplay.ttf",
]
FONT_CANDIDATES_ITA = [
    BASE_DIR / "assets" / "Playfair-Italic.ttf",
    BASE_DIR / "assets" / "PlayfairDisplay-Italic.ttf",
]

def _pick_font(candidates, label):
    for p in candidates:
        if p.exists():
            print(f"[FONT] {label} => {p}", flush=True)
            return str(p)
    print(f"[FONT ERR] {label} not found. Looked for: {[str(x) for x in candidates]}", flush=True)
    return None

FONT_REG_PATH = _pick_font(FONT_CANDIDATES_REG, "Playfair Regular")
FONT_ITA_PATH = _pick_font(FONT_CANDIDATES_ITA, "Playfair Italic")

def load_font(size, italic=False):
    """Load Playfair (ưu tiên), nếu fail rớt về default và in log."""
    path = FONT_ITA_PATH if italic else FONT_REG_PATH
    try:
        if path is None:
            raise FileNotFoundError("Font path is None")
        # Pillow chấp nhận cả path string hoặc file-like object
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"[FONT LOAD ERR] {path}: {e}. Falling back to default.", flush=True)
        return ImageFont.load_default()

# ===== Runtime state =====
DAILY_LIMIT = 10
user_exports = {}   # {date_str: {chat_id: count}}

# ===== Caption presets =====
PRESETS = {
    "mia_nhe":   ("Không ai bắt bạn tin, nhưng người ta bày ra để có cớ làm chuyện nhỏ cho sang.",),
    "tau_hai":   ("Cứ cho là nhân loại rảnh, nhưng cái rảnh này cũng đáng để cười nhẹ một cái.",),
    "trung_tinh":("Ghi chú hôm nay cho lịch sử cá nhân, khỏi lẫn vào mai.",)
}

# ---------- Time helpers (VN) ----------
VN_OFFSET = dt.timedelta(hours=7)

def now_utc():
    return dt.datetime.utcnow()

def now_vn():
    return now_utc() + VN_OFFSET

def today_key():
    return now_vn().strftime("%Y-%m-%d")

def vn_day_month():
    n = now_vn()
    return f"{n.day}/{n.month}"

def now_iso():
    return now_utc().isoformat() + "Z"

# ---------- Misc ----------
def generate_nonce(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def shortlink_with_nonce(nonce):
    return f"https://dz.day/today?nonce={nonce}&utm_source=telegram&utm_medium=share_button"

def check_daily_limit(chat_id):
    key = today_key()
    if key not in user_exports:
        user_exports[key] = {}
    cnt = user_exports[key].get(chat_id, 0)
    if cnt >= DAILY_LIMIT:
        return False
    user_exports[key][chat_id] = cnt + 1
    return True

def log_event(payload):
    if not LOG_URL:
        print("LOG >>> skipped (no LOG_URL)", flush=True); 
        return
    try:
        r = requests.post(LOG_URL, json=payload, timeout=5)
        print("LOG >>>", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("LOG ERR >>>", e, flush=True)

def make_log(update, command, text, nonce="", action="", caption_preset=""):
    msg = update.get("message") or update.get("callback_query", {}).get("message") or {}
    user_from_msg = (update.get("message") or {}).get("from") or {}
    user_from_cq  = (update.get("callback_query") or {}).get("from") or {}
    user = user_from_msg or user_from_cq
    username = user.get("username") or user.get("first_name") or "DzDayBot"
    chat_id = (msg.get("chat") or {}).get("id") or user_from_cq.get("id")
    return {
        "chat_id": chat_id,
        "username": username,
        "text": text,
        "command": command,
        "raw": update,
        "source": "telegram",
        "nonce": nonce,
        "action": action,
        "caption_preset": caption_preset,
        "timestamp": now_iso()
    }

# ---------- Typography (Pillow) ----------
def load_font(size, italic=False):
    path = FONT_ITA_PATH if italic else FONT_REG_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"[FONT LOAD ERR] {path}: {e}. Falling back to default.", flush=True)
        return ImageFont.load_default()

def wrap_text(draw, text, font, max_width, line_height_mult=1.2):
    """
    Trả về (lines, total_height, line_height). Tự xuống dòng khi vượt max_width.
    """
    words = text.replace("\n", " \n ").split(" ")
    lines, current = [], ""
    for w in words:
        if w == "\n":
            lines.append(current.rstrip()); current = ""
            continue
        test = (current + " " + w).strip() if current else w
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            # Nếu 1 từ quá dài, cắt mềm theo chiều rộng
            while draw.textlength(w, font=font) > max_width and len(w) > 1:
                cut = len(w)
                while cut > 1 and draw.textlength(w[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(w[:cut] + "-")
                w = w[cut:]
            current = w
    if current:
        lines.append(current)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * line_height_mult)
    total_height = int(len(lines) * line_height)
    return lines, total_height, line_height

# ---------- Card render ----------
def render_card(day_name, hook_text, fun_fact, short_url, theme=None):
    """
    PNG 1080x1350, text bọc trong content box, Playfair Display.
    """
    W, H = 1080, 1350
    THEMES = {
        "beige":   {"bg": (244, 239, 232), "panel": (255,255,255), "fg": (45, 45, 45), "muted": (92,92,92)},
        "charcoal":{"bg": (20, 22, 24),   "panel": (35,37,39),     "fg": (238,238,238), "muted": (200,200,200)},
        "mint":    {"bg": (235, 246, 242), "panel": (255,255,255), "fg": (34,49,46),    "muted": (78,98,93)},
    }
    theme = theme or random.choice(list(THEMES.keys()))
    C = THEMES[theme]

    img = Image.new("RGB", (W, H), C["bg"])
    draw = ImageDraw.Draw(img)

    # Khung tổng
    PAD_X, PAD_TOP, PAD_BOTTOM = 80, 120, 180
    box_radius = 36
    box = (PAD_X, PAD_TOP, W-PAD_X, H-PAD_BOTTOM)
    draw.rounded_rectangle(box, radius=box_radius, fill=C["panel"])

    # Vùng nội dung
    IN = 72
    left, top = box[0]+IN, box[1]+IN
    content_w = (box[2]-box[0]) - 2*IN

    # Font
    title_font = load_font(88)        # to, Playfair
    sub_font   = load_font(40)        # body
    ita_font   = load_font(40, italic=True)
    wm_font    = load_font(34)

    # ===== Title =====
    title = f"Ngày {day_name} {vn_day_month()}"  # thêm ngày/tháng VN
    t_lines, t_h, lh_t = wrap_text(draw, title, title_font, content_w, 1.12)
    y = top
    for line in t_lines:
        draw.text((left, y), line, font=title_font, fill=C["fg"])
        y += lh_t

    y += 24

    # ===== Hook (màu muted) =====
    hook_lines, hook_h, lh_h = wrap_text(draw, hook_text, sub_font, content_w, 1.35)
    for line in hook_lines:
        draw.text((left, y), line, font=sub_font, fill=C["muted"])
        y += lh_h

    y += 36

    # ===== Fun fact (prefix italic) =====
    prefix = "Fun fact: "
    pf_w = draw.textlength(prefix, font=ita_font)
    ff_lines, ff_h, lh_ff = wrap_text(draw, fun_fact, sub_font, content_w - pf_w, 1.35)

    draw.text((left, y), prefix, font=ita_font, fill=C["fg"])
    draw.text((left+pf_w, y), ff_lines[0], font=sub_font, fill=C["fg"])
    y += lh_ff
    for line in ff_lines[1:]:
        draw.text((left, y), line, font=sub_font, fill=C["fg"])
        y += lh_ff

    # ===== Footer =====
    foot_y = box[3] - IN
    draw.text((left, foot_y-80), "#viaDzDay", font=wm_font, fill=C["muted"])
    draw.text((left, foot_y-40), "dz.day/today", font=wm_font, fill=C["muted"])

    # QR
    qr_size = 220
    qr = qrcode.QRCode(box_size=8, border=1)
    qr.add_data(short_url); qr.make(fit=True)
    qr_img = qr.make_image(
        fill_color=C["fg"],
        back_color=C["panel"]
    ).convert("RGB")
    qr_img = qr_img.resize((qr_size, qr_size))
    img.paste(qr_img, (box[2]-IN-qr_size, foot_y-qr_size+20))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

# ---------- Caption ----------
def build_caption(preset, day_name, fun_fact, nonce):
    preset = (preset or "mia_nhe").strip()
    if preset not in PRESETS: preset = "mia_nhe"
    hook = PRESETS[preset][0]
    link = shortlink_with_nonce(nonce)
    return (
        f"🎂 Hôm nay là Ngày {day_name} {vn_day_month()}\n"
        f"{hook}\n"
        f"Fun fact: {fun_fact}\n"
        f"#viaDzDay {link}"
    )

# ---------- Telegram I/O ----------
def send_msg(chat_id, text, parse_mode=None, reply_markup=None):
    if not BOT_TOKEN: return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(f"{API_URL}/sendMessage", data=payload, timeout=10)
    print("SEND >>>", r.text, flush=True)

def send_photo(chat_id, png_bytes_io, caption=None, reply_markup=None):
    data = {"chat_id": str(chat_id)}
    if caption: data["caption"] = caption
    if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
    files = {"photo": ("dzcard.png", png_bytes_io, "image/png")}
    r = requests.post(f"{API_URL}/sendPhoto", data=data, files=files, timeout=20)
    print("PHOTO >>>", r.text, flush=True)

def kb_today(nonce):
    return {
      "inline_keyboard":[
        [
          {"text":"📤 Share Story", "callback_data": f"share:{nonce}"},
          {"text":"📋 Copy Caption", "callback_data": f"copy:{nonce}"},
          {"text":"💡 Suggest Day", "callback_data": "suggest"}
        ]
      ]
    }

# ---------- Today stub ----------
def get_today():
    # TODO: thay bằng source thực tế
    return {
        "day_name": "Bánh Crepe Toàn Cầu",
        "hook": "Không ai bắt bạn tin, nhưng người ta bày ra để có cớ trộn bột rồi đổ mỏng cho sang.",
        "fun_fact": "Crepe mỏng nhưng ăn nhiều vẫn mập."
    }

# ---------- Webhook ----------
@app.route("/", methods=["GET"])
def index():
    return "DzDayBot alive"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    print("UPDATE >>>", update, flush=True)

    # skip old updates
    msg = update.get("message") or {}
    msg_ts = msg.get("date")
    if msg_ts and time.time() - msg_ts > MAX_UPDATE_AGE:
        print("SKIP old", flush=True); 
        return {"ok": True}

    # messages
    if "message" in update:
        chat_id = (update["message"].get("chat") or {}).get("id")
        text = (update["message"].get("text") or "").strip()
        if text == "/start":
            send_msg(chat_id,
                "Xin chào, tôi là DzDay – giọng Dandattone, hơi mỉa nhưng chân thành 😉\n"
                "Gõ /today để xem hôm nay nhân loại lại bịa ra ngày gì."
            )
            log_event(make_log(update,"start",text))
        elif text == "/today":
            if not check_daily_limit(chat_id):
                send_msg(chat_id,"Hôm nay bạn share chăm quá. Muốn tiếp thì rủ thêm 2 bạn vào gõ /start nhé.")
                log_event(make_log(update,"today",text, action="limit_reached"))
                return {"ok": True}

            d = get_today()
            nonce = generate_nonce()
            url  = shortlink_with_nonce(nonce)
            theme = random.choice(["beige","charcoal","mint"])
            card = render_card(d["day_name"], d["hook"], d["fun_fact"], url, theme=theme)
            caption = (
                f"🎂 *Hôm nay là Ngày {d['day_name']} {vn_day_month()}*\n"
                f"{d['hook']}\n"
                f"*Fun fact:* {d['fun_fact']}\n"
                f"#viaDzDay {url}"
            )
            send_photo(chat_id, card, caption=caption, reply_markup=kb_today(nonce))
            log_event(make_log(update,"today",text, nonce=nonce, caption_preset="mia_nhe"))
        elif text.startswith("/suggest"):
            idea = text.replace("/suggest","",1).strip()
            if not idea:
                send_msg(chat_id, "Gửi kiểu này nè: `/suggest Ngày thế giới ăn bún riêu`.", parse_mode="Markdown")
                log_event(make_log(update,"suggest_prompt","suggest"))
            else:
                send_msg(chat_id, f"Đã ghi nhận gợi ý của bạn: “{idea}”. Tôi sẽ chê trước rồi mới duyệt.")
                log_event(make_log(update,"suggest",idea, action="suggest"))
        else:
            send_msg(chat_id, "Tôi nghe không rõ lắm. Gõ /today hoặc /suggest cho tử tế.")
            log_event(make_log(update,"unknown",text))

    # callback buttons
    if "callback_query" in update:
        cq = update["callback_query"]; data = cq.get("data","")
        chat_id = cq.get("from",{}).get("id")
        d = get_today()
        if data.startswith("share:"):
            nonce = data.split(":",1)[1]
            url = shortlink_with_nonce(nonce)
            send_msg(chat_id, f"Bạn share card này nhé 👉 {url}\n#viaDzDay")
            log_event(make_log(update,"today","share", nonce=nonce, action="share"))
        elif data.startswith("copy:"):
            nonce = data.split(":",1)[1]
            cap = build_caption("mia_nhe", d["day_name"], d["fun_fact"], nonce)
            send_msg(chat_id, cap)
            log_event(make_log(update,"today","copy", nonce=nonce, action="copy", caption_preset="mia_nhe"))
        elif data == "suggest":
            send_msg(chat_id, "Gửi gợi ý bằng lệnh: /suggest Tên ngày")
            log_event(make_log(update,"suggest_prompt","suggest"))

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
