import re
from datetime import datetime, timezone

PROMO_RE = re.compile(
    r"【[^】]*(発売|書籍化|アニメ|連載|コミカライズ|コミック|続刊|完結|受賞|大賞|金賞|重版|更新|追加|シリーズ化|PV|達成|開始)[^】]*】",
    re.IGNORECASE,
)
SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")
MITE_RE = re.compile(r"//(\d+)\.mitemin\.net/(i\d+)/")
SERIES_ID_RE = re.compile(
    r"(?:kakuyomu\.jp/works/|syosetu\.com/|syosetu\.org/novel/|akatsuki-novels\.com/stories/index/novel_id~|novelup\.plus/story/)([\da-z]+)"
)
EPOCH = datetime.fromtimestamp(0, timezone.utc).isoformat().replace("+00:00", "Z")
SITE_COLORS = {
    r"kakuyomu": {"id": "0", "color": "#0099cc"},
    r"ncode": {"id": "1", "color": "#18b7cd"},
    r"novel18": {"id": "2", "color": "#db7dc4"},
    r"syosetu\.org": {"id": "3", "color": "#000000"},
    r"akatsuki": {"id": "4", "color": "#202032"},
    r"novelup": {"id": "5", "color": "#0cbf97"},
}
SITE_NAMES = {
    r"kakuyomu": "kakuyomu",
    r"syosetu\.com": "syosetu",
    r"syosetu\.org": "hameln",
    r"akatsuki": "akatsuki",
    r"novelup": "novelup",
}
SITE_ID: list[tuple[str, tuple[str, ...]]] = [
    (r"\d{15,}", ("kakuyomu",)),
    (r"n\d{4}[a-z]{1,2}", ("syosetu",)),
    (r"\d{1,8}", ("hameln", "akatsuki")),
    (r"\d{9}", ("novelup",)),
]
SITE_BASE = {
    "kakuyomu": "kakuyomu.jp/works/",
    "syosetu": "syosetu.com/",
    "hameln": "syosetu.org/novel/",
    "akatsuki": "akatsuki-novels.com/stories/index/novel_id~",
    "novelup": "novelup.plus/story/",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
