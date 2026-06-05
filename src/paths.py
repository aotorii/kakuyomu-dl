from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUT_DIR = ROOT / "out"
OUT_DIR.mkdir(exist_ok=True)

ASSETS_DIR = ROOT / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

EPUB_DIR = OUT_DIR / "epub"


# def SERIES_DIR(series_id: str) -> Path:
#     return OUT_DIR / series_id
