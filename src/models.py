from dataclasses import dataclass, field
from enum import Enum, auto


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
