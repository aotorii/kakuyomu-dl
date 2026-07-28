import configparser
from configparser import SectionProxy
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from errors import ConfigError
from paths import CONFIG, EPUB_DIR, OUT_DIR
from validators import positive_int


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
    alter_cover: str | None = None


@dataclass
class TocEntry:
    index: int
    title: str
    url: str
    episode_id: str
    category: tuple[str, ...] = ()
    published_on: str = ""
    locked: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class WorkImage:
    src: str
    content: bytes | None = None
    media_type: str | None = None


@dataclass
class RawParagraph:
    text: str
    image: WorkImage | None = None
    is_blank: bool = False
    is_hr: bool = False


@dataclass
class Episode:
    index: int
    title: str
    category: tuple[str, ...]
    episode_id: str
    raw_paragraphs: list[RawParagraph] = field(default_factory=list)


@dataclass
class UpdateResult:
    has_update: bool
    has_new_unlocked: bool
    new_episode_ids: list[str]
    new_episode_titles: list[str]
    old_count: int
    new_count: int
    new_unlocked: list[str]
    meta_updated: bool


class BlockType(Enum):
    PARAGRAPH = auto()
    IMAGE = auto()
    LINK = auto()
    SCENE_BREAK = auto()
    SPECIAL_BREAK = auto()
    THEMATIC_BREAK = auto()


@dataclass
class Block:
    type: BlockType
    text: str = ""
    image: WorkImage | None = None


@dataclass
class ParsedEpisode:
    index: int
    episode_id: str
    title: str
    category: tuple[str, ...]
    blocks: list[Block] = field(default_factory=list)

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.blocks if b.type == BlockType.PARAGRAPH]


def _section_getboolean(section: SectionProxy, key: str, fallback: bool) -> bool:
    try:
        return section.getboolean(key) if section.get(key) else fallback
    except ValueError as e:
        raise ConfigError(str(e))


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

    @classmethod
    def load(cls, filename=CONFIG):
        cfg = cls()
        parser = configparser.ConfigParser()
        parser.read(filename, encoding="utf-8")
        if parser.has_section("fetch"):
            section = parser["fetch"]
            cfg.overwrite = _section_getboolean(
                section, key="overwrite", fallback=cfg.overwrite
            )
            cfg.build_epub = _section_getboolean(
                section, key="build_epub", fallback=cfg.build_epub
            )
            cfg.clean_title = _section_getboolean(
                section, key="clean_title", fallback=cfg.clean_title
            )
            cfg.illustration = _section_getboolean(
                section, key="illustration", fallback=cfg.illustration
            )
            cfg.batch_size = positive_int(section.get("batch_size") or cfg.batch_size)
            cfg.out_dir = Path(section.get("out_dir") or cfg.out_dir)
            cfg.epub_out_dir = Path(section.get("epub_out_dir") or cfg.epub_out_dir)
        return cfg


@dataclass
class EpubConfig:
    xhtml_dir: str | Path = OUT_DIR
    out_dir: str | Path = EPUB_DIR
    clean_title: bool = False

    @classmethod
    def load(cls, filename=CONFIG):
        cfg = cls()
        parser = configparser.ConfigParser()
        parser.read(filename, encoding="utf-8")
        if parser.has_section("epub"):
            section = parser["epub"]
            cfg.clean_title = _section_getboolean(
                section, key="clean_title", fallback=cfg.clean_title
            )
            cfg.xhtml_dir = Path(section.get("xhtml_dir") or cfg.xhtml_dir)
            cfg.out_dir = Path(section.get("out_dir") or cfg.out_dir)
        return cfg


@dataclass
class BookmarkUpdateConfig:
    xhtml_dir: str | Path = OUT_DIR
    epub_dir: str | Path = EPUB_DIR
    overwrite: bool = False
    clean_title: bool = True
    skip_completed: bool = True
    illustration: bool = True

    @classmethod
    def load(cls, filename=CONFIG):
        cfg = cls()
        parser = configparser.ConfigParser()
        parser.read(filename, encoding="utf-8")
        if parser.has_section("bookmark_update"):
            section = parser["bookmark_update"]
            cfg.overwrite = _section_getboolean(
                section, key="overwrite", fallback=cfg.overwrite
            )
            cfg.clean_title = _section_getboolean(
                section, key="clean_title", fallback=cfg.clean_title
            )
            cfg.skip_completed = _section_getboolean(
                section, key="skip_completed", fallback=cfg.skip_completed
            )
            cfg.illustration = _section_getboolean(
                section, key="illustration", fallback=cfg.illustration
            )
            cfg.xhtml_dir = Path(section.get("xhtml_dir") or cfg.xhtml_dir)
            cfg.epub_dir = Path(section.get("epub_dir") or cfg.epub_dir)
        return cfg
