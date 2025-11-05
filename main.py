import os, io, json, logging, time, qrcode, requests
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("dzday")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

def create_app():
    app = Flask(__name__)

    @app.get("/healthz")
    def health():
        return {"ok": True, "ts": int(time.time())}

    @app.post("/webhook")
    def webhook():
        if not BOT_TOKEN:
            log.error("Ignore update: missing BOT_TOKEN")
            return jsonify(ok=True)  # không crash

        update = request.get_json(silent=True) or {}
        log.info("UPDATE >>> %s", update)

        msg = (update.get("message")
               or update.get("edited_message")
               or update.get("callback_query", {}).get("message"))
        if not msg:
            return jsonify(ok=True)

        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()

        if text.startswith("/start"):
            caption = "Xin chào, mình là DzDay. Gõ /today để xem ngày hôm nay!"
            tg("sendMessage", chat_id=chat_id, text=caption)
            return jsonify(ok=True)

        if text.startswith("/today") or update.get("callback_query"):
            # TODO: sinh dữ liệu today_title/body/fun + short_link
            title = "Ngày Bánh Crepe Toàn Cầu 4/11"
            body  = ("Không ai bắt bạn tin, nhưng người ta bày ra để có cớ "
                     "trộn bột rồi đổ mỏng cho sang.")
            fun   = "Crepe mỏng nhưng ăn nhiều vẫn mập."
            link  = "https://dz.day/today"

            img_buf = render_card_square(title, body, fun, link)
            files = {"photo": ("card.jpg", img_buf.getvalue(), "image/jpeg")}
            kb = {
              "inline_keyboard":[
                 [{"text":"📤 Share Story","callback_data":"share:x"},
                  {"text":"📋 Copy Caption","callback_data":"copy:x"},
                  {"text":"💡 Suggest Day","callback_data":"suggest"}]
              ]
            }
            caption = f"🎂 *{title}*\n{body}\n*Fun fact:* {fun}\n#viaDzDay {link}"
            tg("sendPhoto", chat_id=chat_id, caption=caption,
               parse_mode="Markdown", reply_markup=json.dumps(kb), files=files)
            return jsonify(ok=True)

        return jsonify(ok=True)

    return app

def tg(method, files=None, **payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if files:
        return requests.post(url, data=payload, files=files, timeout=20).json()
    return requests.post(url, json=payload, timeout=20).json()

# ------------ RENDER CARD (khung, wrap text an toàn) ------------
ASSETS = os.path.join(os.path.dirname(__file__), "assets")
FONT_REG = ImageFont.truetype(os.path.join(ASSETS, "Playfair.ttf"), 64)
FONT_ITAL= ImageFont.truetype(os.path.join(ASSETS, "Playfair-Italic.ttf"), 48)

def wrap_text(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if draw.textlength(test, font=font) <= max_w:
            cur.append(w)
        else:
            lines.append(" ".join(cur)); cur=[w]
    if cur: lines.append(" ".join(cur))
    return lines

def render_card_square(title, body, fun, link):
    W, H = 1080, 1350
    bg = Image.new("RGB", (W, H), (238, 234, 228))          # nền ngoài
    card = Image.new("RGB", (W-180, H-220), (252, 250, 247))# card trắng ngà
    img = Image.new("RGB", (W, H), (238, 234, 228))
    img.paste(card, (90, 110))

    d = ImageDraw.Draw(img)
    # layout
    pad = 160
    text_w = W - 2*pad - 360       # chừa chỗ QR
    x, y = pad, pad + 40

    # Title
    d.text((x, y), title, fill=(46,41,38), font=ImageFont.truetype(os.path.join(ASSETS,"Playfair.ttf"), 86), spacing=8)
    y += 220

    # Body (wrap)
    body_font = ImageFont.truetype(os.path.join(ASSETS,"Playfair.ttf"), 48)
    for line in wrap_text(d, body, body_font, text_w):
        d.text((x, y), line, fill=(74,66,60), font=body_font, spacing=6)
        y += 68

    # Fun fact (italic + wrap)
    y += 28
    prefix = "Fun fact:"
    pf_w = d.textlength(prefix, font=FONT_ITAL)
    d.text((x, y), prefix, fill=(74,66,60), font=FONT_ITAL)
    fun_lines = wrap_text(d, fun, body_font, text_w - int(pf_w)+8)
    if fun_lines:
        d.text((x+pf_w+12, y), fun_lines[0], fill=(74,66,60), font=body_font)
        y2 = y + 68
        for ln in fun_lines[1:]:
            d.text((x, y2), ln, fill=(74,66,60), font=body_font)
            y2 += 68

    # QR
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(link); qr.make(fit=True)
    qri = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qri = qri.resize((360, 360))
    img.paste(qri, (W - pad - 360, H - pad - 420))

    # Chips footer (màu là tuple, không string!)
    d = ImageDraw.Draw(img)
    chip_font = ImageFont.truetype(os.path.join(ASSETS,"Playfair.ttf"), 38)
    cy = H - pad - 70
    x1, _ = chip("#viaDzDay", x, cy, d, chip_font)
    chip("dz.day/today", x + x1 + 20, cy, d, chip_font)

    # Xuất buffer
    out = io.BytesIO(); img.save(out, format="JPEG", quality=92); out.seek(0)
    return out

def chip(text, x, cy, d, font):
    CHIP = (245, 243, 240); FG = (80,72,60)
    px, py = 22, 12
    w = int(d.textlength(text, font=font)) + px*2
    h = font.size + py*2
    y = cy - h//2
    d.rounded_rectangle((x, y, x+w, y+h), radius=16, fill=CHIP)
    d.text((x+px, y+py-2), text, font=font, fill=FG)
    return w, h

app = create_app()
