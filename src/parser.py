import re
from dataclasses import dataclass, field
from enum import Enum, auto

from scraper import Episode, RawParagraph


class BlockType(Enum):
    PARAGRAPH = auto()
    SCENE_BREAK = auto()


@dataclass
class Block:
    type: BlockType
    text: str = ""


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


_SCENE_BREAK_RE = re.compile(r"^[　\s\*＊※◆◇■□▼△▽○●◎〇—―─·・…〜~＝=\-_]+$")
_DATE_RE = re.compile(r"\s*(\d{4}年\d{1,2}月\d{1,2}日)公開$")


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
            title=self._clean_title(Episode.title),
            category=Episode.category,
            blocks=blocks,
        )

    def parse_many(self, episodes: list[Episode]) -> list[ParsedEpisode]:
        return [self.parse(ch) for ch in episodes]

    def _classify(self, raw: RawParagraph) -> Block | None:
        if raw.is_blank:
            return Block(type=BlockType.SCENE_BREAK)

        cleaned = self._clean_text(raw.text)
        if not cleaned:
            return None

        if _SCENE_BREAK_RE.match(cleaned):
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

    def _clean_title(self, title: str) -> str:
        title = _DATE_RE.sub("", title).strip()
        # title = re.sub(r"^[【『](.+)[】』]$", r"\1", title)
        return title
