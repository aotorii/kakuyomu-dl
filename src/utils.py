import io
import re
import textwrap

import inflect
from PIL import Image, ImageDraw, ImageFont

from config import ASSETS_DIR

BASE_URL = "https://kakuyomu.jp/works/"
DATE_RE = re.compile(r"\s*(\d{4}年\d{1,2}月\d{1,2}日)公開$")
PROMO_RE = re.compile(
    r"【[^】]*(発売|書籍化|連載|コミカライズ|コミック|続刊|完結|受賞|大賞)[^】]*】"
)
SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")


def parse_plural(noun: str, num: int, prefix: str = "") -> str:
    P = inflect.engine()
    return f"{num} {prefix}{P.plural_noun(noun, num)}"


def clean_title(title: str, clean: bool) -> str:
    return PROMO_RE.sub("", title).strip() if clean else title


def strip_date(title: str) -> str:
    return DATE_RE.sub("", title).strip()


def escape(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text


def generate_cover(
    title: str, author: str, bg_path: str = ASSETS_DIR / "cover.png"
) -> bytes:
    img = Image.open(bg_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    # expects 1400x2000
    W, H = img.size

    try:
        font_title = ImageFont.truetype(ASSETS_DIR / "NotoSerifJP-Bold.ttf", 80)
        font_author = ImageFont.truetype(ASSETS_DIR / "NotoSerifJP-Regular.ttf", 48)
    except IOError:
        font_title = ImageFont.load_default()
        font_author = ImageFont.load_default()

    BLUE = "#0099cc"
    DARK = "#1a1a1a"
    GREY = "#444444"

    TEXT_X_START = 180
    TEXT_WIDTH = W - 220
    STRIP_W = 114
    TEXT_PAD = 40
    TEXT_X = STRIP_W + TEXT_PAD
    TEXT_W = W - TEXT_X - TEXT_PAD

    avg_char_w = draw.textbbox((0, 0), "あ", font=font_title)[2]
    chars_per_line = max(1, int(TEXT_W / avg_char_w))
    lines = textwrap.wrap(title, width=chars_per_line)

    line_h = draw.textbbox((0, 0), "あ", font=font_title)[3]
    line_gap = 20
    block_h = len(lines) * line_h + (len(lines) - 1) * line_gap

    y = (H * 0.70 - block_h) / 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        tw = bbox[2] - bbox[0]
        x = TEXT_X + (TEXT_W - tw) / 2
        draw.text((x, y), line, font=font_title, fill=DARK)
        y += line_h + line_gap

    y += 20
    draw.rectangle([TEXT_X_START, y, TEXT_X_START + TEXT_WIDTH, y + 4], fill=BLUE)
    y += 24

    bbox = draw.textbbox((0, 0), author, font=font_author)
    aw = bbox[2] - bbox[0]
    x = TEXT_X_START + (TEXT_WIDTH - aw) / 2
    draw.text((x, y), author, font=font_author, fill=GREY)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def safe_filename(title: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title)
    safe = safe.strip().replace(" ", "_")
    return safe or "novel"
