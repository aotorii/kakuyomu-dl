from dataclasses import dataclass
from pathlib import Path

from utils import EPUB_DIR, OUT_DIR


@dataclass
class FetchConfig:
    overwrite: bool = True
    out_dir: str | Path = OUT_DIR
    # e.g. out_dir: str | Path = r"c:\Users\<username>\Downloads"
    build_epub: bool = False
    epub_out_dir: str | Path = EPUB_DIR
    # e.g. epub_out_dir: str | Path = r"c:\Users\<username>\Downloads"
    clean_title: bool = False
    illustration: bool = True
    batch_size: int = 20


@dataclass
class EpubConfig:
    xhtml_dir: str | Path = OUT_DIR
    out_dir: str | Path = EPUB_DIR
    clean_title: bool = False


@dataclass
class BookmarkUpdateConfig:
    xhtml_dir: str | Path = OUT_DIR
    epub_dir: str | Path = EPUB_DIR
    overwrite: bool = False
    clean_title: bool = True
    skip_completed: bool = True
    illustration: bool = True
