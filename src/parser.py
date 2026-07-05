import re
from dataclasses import dataclass, field
from enum import Enum, auto

from scrapers import Episode, RawParagraph, WorkImage
from utils import SCENE_BREAK_RE


class BlockType(Enum):
    PARAGRAPH = auto()
    IMAGE = auto()
    SCENE_BREAK = auto()
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
    category: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.blocks if b.type == BlockType.PARAGRAPH]


class EpisodeParser:
    def __init__(self):
        pass

    def parse(self, Episode: Episode) -> ParsedEpisode:
        blocks: list[Block] = []

        for raw in Episode.raw_paragraphs:
            block = self._classify(raw)
            if block is None or (
                block.type == BlockType.SCENE_BREAK
                and blocks
                and blocks[-1].type == BlockType.SCENE_BREAK
            ):
                continue
            blocks.append(block)

        while blocks and blocks[0].type == BlockType.SCENE_BREAK:
            blocks.pop(0)
        while blocks and blocks[-1].type == BlockType.SCENE_BREAK:
            blocks.pop()

        return ParsedEpisode(
            index=Episode.index,
            episode_id=Episode.episode_id,
            title=Episode.title,
            category=Episode.category,
            blocks=blocks,
        )

    def parse_many(self, episodes: list[Episode]) -> list[ParsedEpisode]:
        return [self.parse(ch) for ch in episodes]

    def _classify(self, raw: RawParagraph) -> Block | None:
        if raw.image:
            return Block(type=BlockType.IMAGE, image=raw.image)

        if raw.is_blank:
            return Block(type=BlockType.SCENE_BREAK)

        if raw.is_hr:
            return Block(type=BlockType.THEMATIC_BREAK)

        cleaned = self._clean_text(raw.text)
        if not cleaned:
            return None

        if SCENE_BREAK_RE.match(cleaned):
            is_pure_whitespace = not cleaned.strip()
            return Block(
                type=BlockType.SCENE_BREAK,
                text="" if is_pure_whitespace else cleaned.strip(),
            )

        return Block(type=BlockType.PARAGRAPH, text=cleaned)

    def _clean_text(self, text: str) -> str:
        leading_match = re.match(r"^[　]+", text)
        prefix = leading_match.group(0) if leading_match else ""
        rest = text[len(prefix) :]

        rest = re.sub(r"[ \t]+", " ", rest)
        rest = rest.rstrip()
        return prefix + rest
