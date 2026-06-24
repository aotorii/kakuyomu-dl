from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TocEntry:
    index: int
    title: str
    url: str
    episode_id: str
    category: str = ""
    published_on: str = ""
    locked: bool = False


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


@dataclass
class RawParagraph:
    text: str
    is_blank: bool


@dataclass
class Episode:
    index: int
    title: str
    category: str
    episode_id: str
    raw_paragraphs: list[RawParagraph] = field(default_factory=list)


class BaseScraper(ABC):
    @abstractmethod
    def fetch_meta_and_toc(self, series_id: str): ...

    @abstractmethod
    def fetch_work_meta(self, series_id: str): ...

    @abstractmethod
    def fetch_toc(self, series_id: str): ...

    @abstractmethod
    def fetch_episode(self, entry: TocEntry): ...

    @abstractmethod
    def fetch_episodes(
        self,
        entries: list[TocEntry],
        indices: Optional[list[int]] = None,
    ): ...

    @abstractmethod
    def parse_work_meta(self, data: dict, series_id: str): ...

    @abstractmethod
    def parse_toc(self, data: dict, series_id: str): ...
