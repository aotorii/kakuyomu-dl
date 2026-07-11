import copy
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

from utils import parse_plural

logger = logging.getLogger(__name__)


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


class BaseScraper(ABC):
    @abstractmethod
    def fetch_episode(self, entry: TocEntry, illus: bool = True): ...

    @abstractmethod
    def fetch_image(self, url: str): ...

    @abstractmethod
    def _fetch_next_data(self, url: str): ...

    @abstractmethod
    def _get_url(self, series_id: str): ...

    @abstractmethod
    def _get_ep_url(self, work_url: str, episode_id: str): ...

    @abstractmethod
    def _apolloize(self, data: dict, series_id: str): ...

    def fetch_work_meta(self, series_id: str) -> WorkMeta:
        url = self._get_url(series_id)
        data = self._fetch_next_data(url)
        apollo = self._apolloize(data, series_id)
        return self.parse_work_meta(apollo, series_id)

    def fetch_meta_and_toc(
        self, series_id: str
    ) -> tuple[WorkMeta, list[TocEntry], dict]:
        url = self._get_url(series_id)
        logger.info(f"Fetching work page: {url}")
        data = self._fetch_next_data(url)
        apollo = self._apolloize(data, series_id)
        meta = self.parse_work_meta(apollo, series_id)
        entries = self.parse_toc(apollo, series_id)
        chapter = (
            f"{parse_plural('chapter', len({e.category for e in entries if e.category}))}, "
            if any(e.category for e in entries)
            else ""
        )
        episode = f"{parse_plural('episode', len(entries))}"
        locked_number = sum(1 for episode in entries if episode.locked)
        lock = f" ({locked_number} locked)" if locked_number else ""

        logger.info(f"TOC done — {chapter}{episode} found{lock}.")
        return meta, entries, apollo

    def fetch_toc(self, series_id: str) -> list[TocEntry]:
        _, entries, _ = self.fetch_meta_and_toc(series_id)
        return entries

    def fetch_episodes(
        self,
        entries: list[TocEntry],
        indices: Optional[list[int]] = None,
        illus: bool = True,
    ) -> list[Episode]:
        targets = (
            [e for e in entries if e.index in indices]
            if indices is not None
            else entries
        )
        fetch = [e for e in targets if not e.locked]
        skip = [e for e in targets if e.locked]
        if skip:
            logger.info(f"Skipping {parse_plural('episode', len(skip), 'locked ')}…")
        episodes: list[Episode] = []
        for i, entry in enumerate(fetch):
            if i > 0:
                time.sleep(self.delay)
            episodes.append(self.fetch_episode(entry, illus))
        return episodes

    def parse_work_meta(self, apollo: dict, series_id: str) -> WorkMeta:
        work_url = apollo.get(f"Work:{series_id}", {}).get("url", "")
        work_key = f"Work:{series_id}"
        work_node = apollo.get(work_key, {})
        title = work_node.get("title", f"Work {series_id}")

        author = "Unknown"
        author_ref = work_node.get("author", {}).get("__ref", "")
        if author_ref:
            user_node = apollo.get(author_ref, {})
            author = user_node.get("activityName") or user_node.get("name", "Unknown")

        description = work_node.get("introduction", "")
        status = work_node.get("serialStatus", "")
        status = 0 if status == "COMPLETED" else 1
        character_count = work_node.get("totalCharacterCount", 0)
        episode_count = work_node.get("publicEpisodeCount", 0)
        published = work_node.get("publishedAt", "")
        last_episode = work_node.get("lastEpisodePublishedAt", "")
        last_edited = work_node.get("editedAt", "")
        key_visual = work_node.get("adminSquareImageUrl", None)

        return WorkMeta(
            series_id=series_id,
            title=title.strip(),
            author=author.strip(),
            description=description.strip(),
            work_url=work_url,
            status=status,
            character_count=character_count,
            episode_count=episode_count,
            published=published,
            last_episode=last_episode,
            last_edited=last_edited,
            key_visual=key_visual,
        )

    def parse_toc(self, apollo: dict, series_id: str) -> list[TocEntry]:
        work_url = apollo.get(f"Work:{series_id}", {}).get("url", "")
        work_key = f"Work:{series_id}"
        work_node = apollo.get(work_key, {})

        toc_refs = work_node.get("tableOfContentsV2", [])
        prop_refs = work_node.get("property", [])
        entries: list[TocEntry] = []
        category: tuple[str, ...] = ()
        index = 1

        prop_keys = [prop_ref.get("__ref", "") for prop_ref in prop_refs]
        prop = {prop_key: work_node.get(prop_key) for prop_key in prop_keys}

        # for toc_ref in toc_refs:
        #     toc_key = toc_ref.get("__ref", "")
        #     toc_node = apollo.get(toc_key, {})
        #     if not toc_node:
        #         continue

        #     chapter_val = toc_node.get("chapter")
        #     chapter_ref = (
        #         chapter_val.get("__ref", "") if isinstance(chapter_val, dict) else ""
        #     )
        #     chapter_node = apollo.get(chapter_ref, {}) if chapter_ref else {}
        #     category = chapter_node.get("title", "")

        #     ep_refs = toc_node.get("episodeUnions", [])
        #     for ep_ref in ep_refs:
        #         ep_key = ep_ref.get("__ref", "")
        #         ep_node = apollo.get(ep_key, {})

        #         typename = ep_node.get("__typename", "") if ep_node else ""
        #         locked = typename == "EmptyEpisode"

        #         episode_id = (
        #             ep_node.get("id", ep_key.split(":")[-1])
        #             if ep_node
        #             else ep_key.split(":")[-1]
        #         )
        #         title = ep_node.get("title", "") if ep_node else ""
        #         published_at = ep_node.get("publishedAt", "") if ep_node else ""

        #         published_on = published_at[:10]

        #         entries.append(
        #             TocEntry(
        #                 index=index,
        #                 title=title,
        #                 url=self._get_ep_url(work_url=work_url, episode_id=episode_id),
        #                 episode_id=episode_id,
        #                 category=category,
        #                 published_on=published_on,
        #                 locked=locked,
        #                 meta=prop,
        #             )
        #         )
        #         index += 1

        level = 0
        for toc_ref in toc_refs:
            toc_key = toc_ref.get("__ref", "")
            toc_node = apollo.get(toc_key, {})
            if not toc_node:
                continue

            chapter_val = toc_node.get("chapter")
            chapter_ref = (
                chapter_val.get("__ref", "") if isinstance(chapter_val, dict) else ""
            )
            chapter_node = apollo.get(chapter_ref, {}) if chapter_ref else {}
            chapter_title = chapter_node.get("title")
            chapter_level = chapter_node.get("level", 0)
            if chapter_title is not None:
                if chapter_level > level:
                    category += (chapter_title,)
                elif chapter_level <= level:
                    delta = chapter_level - level - 1
                    category = category[:delta] + (chapter_title,)
            level = chapter_level

            ep_refs = toc_node.get("episodeUnions", [])
            for ep_ref in ep_refs:
                ep_key = ep_ref.get("__ref", "")
                ep_node = apollo.get(ep_key, {})
                typename = ep_node.get("__typename", "") if ep_node else ""
                locked = typename == "EmptyEpisode"

                episode_id = (
                    ep_node.get("id", ep_key.split(":")[-1])
                    if ep_node
                    else ep_key.split(":")[-1]
                )
                title = ep_node.get("title", "") if ep_node else ""
                published_at = ep_node.get("publishedAt", "") if ep_node else ""
                published_on = published_at[:10]

                entries.append(
                    TocEntry(
                        index=index,
                        title=title,
                        url=self._get_ep_url(work_url=work_url, episode_id=episode_id),
                        episode_id=episode_id,
                        category=category,
                        published_on=published_on,
                        locked=locked,
                        meta=prop,
                    )
                )
                index += 1
        return entries

    def _get_soup(self, url: str) -> BeautifulSoup:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def _extract_text(self, tag: Tag, is_blank: bool = False) -> str:
        if is_blank:
            return ""
        p = copy.copy(tag)
        for rp in p.find_all("rp"):
            rp.decompose()
        return p.decode_contents()
