from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUT_DIR = ROOT / "out"
ASSETS_DIR = ROOT / "assets"
EPUB_DIR = OUT_DIR / "epub"

OUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
EPUB_DIR.mkdir(exist_ok=True)

# def SERIES_DIR(series_id: str) -> Path:
#     return OUT_DIR / series_id
