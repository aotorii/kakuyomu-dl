import argparse
import io
import json
import re
import sys
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import emoji
import inflect
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROMO_RE = re.compile(
    r"【[^】]*(発売|書籍化|アニメ|連載|コミカライズ|コミック|続刊|完結|受賞|大賞|金賞|重版|更新|追加|シリーズ化|PV|達成|開始)[^】]*】",
    re.IGNORECASE,
)
SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")
MITE_RE = re.compile(r"//(\d+)\.mitemin\.net/(i\d+)/")
SERIES_ID_RE = re.compile(
    r"(?:kakuyomu\.jp/works/|syosetu\.com/|syosetu\.org/novel/|akatsuki-novels\.com/stories/index/novel_id~)([\da-z]+)"
)

EPOCH = datetime.fromtimestamp(0, timezone.utc).isoformat().replace("+00:00", "Z")

SITE_COLORS = {
    r"kakuyomu": {"id": "0", "color": "#0099cc"},
    r"ncode": {"id": "1", "color": "#18b7cd"},
    r"novel18": {"id": "2", "color": "#db7dc4"},
    r"syosetu\.org": {"id": "3", "color": "#000000"},
    r"akatsuki": {"id": "4", "color": "#202032"},
}
SITE_NAMES = {
    r"kakuyomu": "kakuyomu",
    r"syosetu\.com": "syosetu",
    r"syosetu\.org": "hameln",
    r"akatsuki": "akatsuki",
}
SITE_ID: list[tuple[str, tuple[str, ...]]] = [
    (r"\d{15,}", ("kakuyomu",)),
    (r"n\d{4}[a-z]{1,2}", ("syosetu",)),
    (r"\d{1,8}", ("hameln", "akatsuki")),
]
SITE_BASE = {
    "kakuyomu": "kakuyomu.jp/works/",
    "syosetu": "syosetu.com/",
    "hameln": "syosetu.org/novel/",
    "akatsuki": "akatsuki-novels.com/stories/index/novel_id~",
}


ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = ROOT / "assets"
OUT_DIR = ROOT / "out"
CONFIG_DIR = ROOT / "config"
EPUB_DIR = OUT_DIR / "epub"

OUT_DIR.mkdir(exist_ok=True)
EPUB_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

COOKIES = CONFIG_DIR / "cf_cookies.json"


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
    key_visual: str | None = None


def parse_plural(noun: str, num: int, prefix: str = "") -> str:
    P = inflect.engine()
    return f"{num} {prefix}{P.plural_noun(noun, num)}"


def parse_status(status: int) -> str:
    return "Running" if status else "Completed"


def parse_id_and_site(value: str) -> tuple[str, str]:
    series_id = parse_series_id(value)
    site = parse_site(value)
    return series_id, site


def parse_series_id(value: str) -> str:
    value = value.strip().rstrip("/")
    match = SERIES_ID_RE.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\da-z]+", value, re.IGNORECASE):
        return value.lower()
    print(f"[error] Could not parse a series ID from: {value!r}.", file=sys.stderr)
    sys.exit(1)


def parse_site(value: str) -> str:
    value = value.strip().rstrip("/")
    for pattern, site in SITE_NAMES.items():
        if re.search(pattern, value):
            return site
    series_id = parse_series_id(value)
    matches: tuple[type, ...] = ()
    for pattern, sites in SITE_ID:
        if re.fullmatch(pattern, series_id, re.IGNORECASE):
            matches = sites
            break
    if not matches:
        print(f"[error] Unsupported series ID: {series_id!r}.", file=sys.stderr)
        sys.exit(1)
    if len(matches) == 1:
        return matches[0]

    print(f"Series ID {series_id!r} is ambiguous. Which site is this from?")
    for i, site in enumerate(matches, start=1):
        print(f"  {i}. {site}")
    choice = input("> ").strip()
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(matches)):
            raise ValueError
    except ValueError:
        print(f"[error] Invalid selection: {choice!r}.", file=sys.stderr)
        sys.exit(1)
    return matches[idx]


def parse_date(date: str) -> str | None:
    date = re.sub(r"\(.+?\)", "", date).strip()
    JST = timezone(timedelta(hours=9))
    FORMAT = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年 %m月 %d日 %H時 %M分 %S秒",
    ]
    if not date:
        return None
    for fmt in FORMAT:
        try:
            return (
                datetime
                .strptime(date, fmt)
                .replace(tzinfo=JST)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except ValueError:
            continue
    raise ValueError(f"Unknown date format: {date}")


def parse_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.query:
        qs = parse_qs(parsed.query)
        target = qs.get("url", [""])[0]
        url = unquote(target)
    return url


def parse_episode_selection(spec: str, total: int) -> list[int]:
    indices: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            indices.update(range(int(start), int(end) + 1))
        else:
            indices.add(int(part))

    valid = sorted(i for i in indices if 1 <= i <= total)
    invalid = sorted(i for i in indices if i < 1 or i > total)
    if invalid:
        print(
            f"[warning] Ignoring out-of-range episode indices: {invalid}",
            file=sys.stderr,
        )
    return valid


def get_base(site: str, series_id: str) -> str:
    return SITE_BASE[site] + series_id


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


def print_bookmarks(bookmarks: list[dict]) -> None:
    header = ("#", "Title", "Author", "ID", "Status")
    data = []

    def chop_title(text: str, width: int = 35) -> str:
        if len(text) > width:
            return text[:width] + "…"
        return text

    for i, series in enumerate(bookmarks):
        data.append((
            f"{i + 1:02d}",
            chop_title(series["title"]),
            series["author"],
            series["series_id"],
            series["status"],
        ))
    table = write_table(header, data)
    print_table(table)


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


def write_table(
    header: tuple[str, ...], data: list[tuple[str, ...]]
) -> list[tuple[tuple[str, ...], int]]:
    table = []
    is_invalid = sum(abs(len(header) - len(row)) for row in data)
    if is_invalid:
        raise ValueError(
            "Please make sure every row of the table aligns with the header."
        )
    for i, entry in enumerate(header):
        column = (entry,) + tuple(row[i] for row in data)
        width = max(display_width(entry) for entry in column)
        table.append((column, width))
    return table


def print_table(table: list[tuple[tuple[str, ...], int]]) -> None:

    def print_hr(branch: str = "┼─") -> None:
        hr = ""
        for j, (_, width) in enumerate(table):
            if j == 0:
                hr += f" ─{branch}"
            hr += "─" * width + branch
        print(hr)

    height = len(table[0][0])
    for i in range(height):
        print_hr("┬─" if i == 0 else "┼─")
        row = ""
        for j, (column, width) in enumerate(table):
            space = width - display_width(column[i])
            left = space // 2
            if j == 0:
                row += "  │ "
            row += " " * left + f"{column[i]}" + " " * (space - left) + "│ "
        print(row)
    print_hr("┴─")


def batched(iterable, n: int):
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch


def positive_int(value) -> int:
    try:
        value = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer value: '{value}'")

    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def better_view(data: list[tuple[str, str]]) -> str:
    width, result = max(display_width(key) for key, _ in data), []
    for key, value in data:
        result.append(f"{key}{' ' * (width - display_width(key))}{value}")
    return result


def get_spec(indices: list[int]) -> list[str]:
    spec: list[str] = []
    indices = sorted(list(set(indices)))
    i = 0
    while i < len(indices):
        j = i
        while j + 1 < len(indices) and indices[j + 1] == indices[j] + 1:
            j += 1
        if i == j:
            spec.append(str(indices[i]))
        else:
            spec.append(f"{indices[i]}-{indices[j]}")
        i = j + 1
    return spec


def load_cookies(file: str | Path = COOKIES) -> dict:
    if not file.exists():
        raise FileNotFoundError(
            f"Cookies for clearing cloudflare challenges not found: {file}."
            f"Export it first."
        )
    return json.loads(file.read_text())


def strip_emoji(text: str) -> str:
    return emoji.replace_emoji(text, replace=" ").strip()


def escape(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text


def process_image(
    content: bytes, max_width: int = 1200, max_height: int = 1800
) -> bytes:
    img = Image.open(io.BytesIO(content)).convert("RGB")
    scale = min(max_width / img.width, max_height / img.height)
    if scale < 1:
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)), Image.LANCZOS
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _feather_mask(size: tuple[int, int], opacity: int, feather: int) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle([feather, feather, w - feather, h - feather], fill=opacity)
    return mask.filter(ImageFilter.GaussianBlur(feather / 2))


def _place_visual(
    img: Image.Image,
    key_visual: bytes,
    box: tuple[int, int, int, int],
    opacity: float = 0.5,
    feather: int = 36,
) -> None:
    x0, y0, x1, y1 = (round(v) for v in box)
    box_w, box_h = x1 - x0, y1 - y0
    if box_w <= 0 or box_h <= 0:
        return

    visual = Image.open(io.BytesIO(key_visual)).convert("RGB")
    vw, vh = visual.size
    scale = min(box_w / vw, box_h / vh)
    new_w, new_h = max(1, round(vw * scale)), max(1, round(vh * scale))
    if scale < 1 or scale > 1:
        visual = visual.resize((new_w, new_h), Image.LANCZOS)

    mask = _feather_mask((new_w, new_h), opacity=round(255 * opacity), feather=feather)

    paste_x = x0 + (box_w - new_w) // 2
    paste_y = y0
    img.paste(visual, (paste_x, paste_y), mask)


def generate_cover(
    title: str, author: str, site: dict, key_visual: bytes | None = None
) -> bytes:
    identifier = site.get("id")
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
    BOTTOM_MARGIN = 100

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

    if key_visual:
        _place_visual(
            img,
            key_visual,
            box=(TEXT_X_START, y, TEXT_X_START + TEXT_WIDTH, H - BOTTOM_MARGIN),
        )

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
