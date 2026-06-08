from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUT_DIR = ROOT / "out"
EPUB_DIR = OUT_DIR / "epub"


@dataclass
class FetchConfig:
    overwrite: bool = True
    out_dir: str | Path = OUT_DIR
    # e.g. out_dir: str | Path = r"c:\Users\<username>\Downloads"
    build_epub: bool = False
    epub_out_dir: str | Path = EPUB_DIR
    # e.g. epub_out_dir: str | Path = r"c:\Users\<username>\Downloads"
    clean_title: bool = False


@dataclass
class EpubConfig:
    xhtml_dir: str | Path = OUT_DIR
    out_dir: str | Path = EPUB_DIR
    clean_title: bool = True


@dataclass
class BookmarkUpdateConfig:
    xhtml_dir: str | Path = OUT_DIR
    epub_dir: str | Path = EPUB_DIR
    overwrite = False
    clean_title = True
