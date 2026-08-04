from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = ROOT / "assets"
OUT_DIR = ROOT / "out"
CONFIG_DIR = ROOT / "config"
EPUB_DIR = OUT_DIR / "epub"
LOG_DIR = CONFIG_DIR / "logs"

EPUB_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

COOKIES = CONFIG_DIR / "cf_cookies.json"
CONFIG = CONFIG_DIR / "config.ini"
