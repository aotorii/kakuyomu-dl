import io
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import inflect
from PIL import Image, ImageDraw, ImageFont
from wcwidth import wcswidth

BASE_URL = "https://kakuyomu.jp/works/"
DATE_RE = re.compile(r"\s*(\d{4}年\d{1,2}月\d{1,2}日)公開$")
PROMO_RE = re.compile(
    r"【[^】]*(発売|書籍化|連載|コミカライズ|コミック|続刊|完結|受賞|大賞)[^】]*】"
)
SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")


ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = ROOT / "assets"
OUT_DIR = ROOT / "out"
EPUB_DIR = OUT_DIR / "epub"

OUT_DIR.mkdir(exist_ok=True)
EPUB_DIR.mkdir(exist_ok=True)


@dataclass
class WorkMeta:
    series_id: str
    title: str
    author: str
    description: str
    work_url: str
    status: str
    character_count: int
    episode_count = int
    published: str
    last_episode: str
    last_edited: str


def parse_plural(noun: str, num: int, prefix: str = "") -> str:
    P = inflect.engine()
    return f"{num} {prefix}{P.plural_noun(noun, num)}"


def clean_title(title: str, clean: bool) -> str:
    return PROMO_RE.sub("", title).strip() if clean else title


def strip_date(title: str) -> str:
    return DATE_RE.sub("", title).strip()


def display_date(time: str) -> str:
    dt = datetime.fromisoformat(time.replace("Z", "+00:00"))
    return f"{dt:%Y-%m-%d}"


def display_title(title: str) -> str:
    space = 100 - wcswidth(title)
    if space <= 0:
        return title
    left = space // 2
    right = space - left
    return "-" * left + title + "-" * right


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


def generate_colophon(meta: WorkMeta, clean: bool = False, lang: str = "ja") -> bytes:
    status = "完結済" if meta.status == "COMPLETED" else "連載中"
    title = clean_title(meta.title, clean)
    line = [
        ("執筆状況", f"{status}"),
        ("エピソード", f"{meta.episode_count}話"),
        ("総文字数", f"{meta.character_count:,}文字"),
        ("公開日", f"{meta.published}"),
        ("最終更新日", f"{meta.last_edited}"),
    ]
    info = '<table style="border-collapse: collapse; line-height: 2;">'
    for key, value in line:
        info += (
            '<tr><td style="padding-right: 2em;">'
            + key
            + "</td><td>"
            + value
            + "</td></tr>"
        )
    info += "</table>"
    html = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{
        lang
    }">
<head>
<meta charset="UTF-8"/>
<title>奥付</title>
</head>
<body style="font-family: serif; padding: 3em; line-height: 2;">
<div style="max-width: 36em; margin: 6em auto;">
  <p style="font-size: 1.2em; font-weight: bold;">{title}</p>
  <p style="font-size: 0.9em;">{meta.author}</p>
  <hr/>
  {info}
  <p><a href="{meta.work_url}">{meta.work_url}</a></p>
</div>
</body>
</html>"""
    return html.encode("utf-8")


def safe_filename(title: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title)
    safe = safe.strip().replace(" ", "_")
    return safe or "novel"
