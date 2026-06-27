import io
import re
import sys
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import inflect
from PIL import Image, ImageDraw, ImageFont

PROMO_RE = re.compile(
    r"【[^】]*(発売|書籍化|アニメ|連載|コミカライズ|コミック|続刊|完結|受賞|大賞|金賞|重版|更新|追加|シリーズ化|PV|達成|開始)[^】]*】",
    re.IGNORECASE,
)
SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")
MITE_RE = re.compile(r"//(\d+)\.mitemin\.net/(i\d+)/")

EPOCH = datetime.fromtimestamp(0, timezone.utc).isoformat().replace("+00:00", "Z")

SITE = {
    r"ncode": {"site": "naro", "color": "#18b7cd"},
    r"novel18": {"site": "naro18", "color": "#db7dc4"},
    r"kakuyomu": {"site": "kakuyomu", "color": "#0099cc"},
}

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
    status: int
    character_count: int
    episode_count: int
    published: str
    last_episode: str
    last_edited: str


def parse_plural(noun: str, num: int, prefix: str = "") -> str:
    P = inflect.engine()
    return f"{num} {prefix}{P.plural_noun(noun, num)}"


def parse_status(status: int) -> str:
    return "Running" if status else "Completed"


def parse_series_id(value: str) -> str:
    value = value.strip().rstrip("/")
    match = re.search(r"(?:kakuyomu\.jp/works|syosetu\.com)/([\da-z]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\da-z]+", value, re.IGNORECASE):
        return value.lower()
    print(f"[error] Could not parse a series ID from: {value!r}.", file=sys.stderr)
    sys.exit(1)


def parse_date(date: str) -> str | None:
    JST = timezone(timedelta(hours=9))
    if not date:
        return None
    return (
        datetime
        .strptime(date, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=JST)
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def clean_title(title: str, clean: bool) -> str:
    return PROMO_RE.sub("", title).strip() if clean else title


def display_date(time: str) -> str:
    dt = datetime.fromisoformat(time.replace("Z", "+00:00"))
    return f"{dt:%Y-%m-%d}"


def display_title(title: str) -> str:
    space = 100 - display_width(title)
    if space <= 0:
        return title
    left = space // 2
    right = space - left
    return "-" * left + title + "-" * right


def print_meta(meta: WorkMeta) -> None:
    line = [
        ("Title", f"{meta.title}"),
        ("Author", f"{meta.author}"),
        ("Status", f"{parse_status(meta.status)}"),
        ("Publish date", f"{display_date(meta.published)}"),
        ("Last episode on", f"{display_date(meta.last_episode)}"),
        ("Last edited on", f"{display_date(meta.last_edited)}"),
        ("Total character count", f"{meta.character_count:,}"),
    ]
    width = max(len(key) for key, _ in line)
    for key, value in line:
        print(f"  {key:<{width}}   {value}")


def display_width(text: str) -> int:
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        elif eaw == "A":
            width += 2
        else:
            width += 1
    return width


def better_view(data: list[tuple[str, str]]) -> str:
    width, result = max(display_width(key) for key, _ in data), []
    for key, value in data:
        result.append(f"{key}{' ' * (width - display_width(key))}{value}")
    return result


def escape(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text


def generate_cover(title: str, author: str, site: dict) -> bytes:
    identifier = site.get("site")
    color = site.get("color")
    bg_path = ASSETS_DIR / "covers" / f"cover_{identifier}.png"
    img = Image.open(bg_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    # expects 1400x2000
    W, H = img.size

    try:
        font_title = ImageFont.truetype(
            ASSETS_DIR / "fonts" / "NotoSerifJP-Bold.ttf", 80
        )
        font_author = ImageFont.truetype(
            ASSETS_DIR / "fonts" / "NotoSerifJP-Regular.ttf", 48
        )
    except IOError:
        font_title = ImageFont.load_default()
        font_author = ImageFont.load_default()

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
    draw.rectangle([TEXT_X_START, y, TEXT_X_START + TEXT_WIDTH, y + 4], fill=color)
    y += 24

    bbox = draw.textbbox((0, 0), author, font=font_author)
    aw = bbox[2] - bbox[0]
    x = TEXT_X_START + (TEXT_WIDTH - aw) / 2
    draw.text((x, y), author, font=font_author, fill=GREY)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def generate_colophon(meta: WorkMeta, clean: bool = False, lang: str = "ja") -> bytes:
    status = "連載中" if meta.status else "完結済"
    title = clean_title(meta.title, clean)
    line = [
        ("執筆状況", f"{status}"),
        ("エピソード", f"{meta.episode_count}話"),
        ("総文字数", f"{meta.character_count:,}文字"),
        ("公開日", f"{meta.published}"),
        ("最終更新日", f"{meta.last_edited}"),
    ]
    info = '<table style="border-collapse: collapse; border: none; line-height: 2;">'
    for key, value in line:
        info += (
            '<tr><td style="border: none; width: 8em;">'
            # 'padding-right: 2em;">'
            + key
            + '</td><td style="border: none">'
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
