import re
import copy
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL  = "https://kakuyomu.jp"
WORK_URL  = BASE_URL + "/works/{work_id}"
EP_URL    = BASE_URL + "/works/{work_id}/episodes/{episode_id}"

CHAPTER_MAIN_TITLE_SELECTOR = "p.chapterTitle"
CHAPTER_SUB_TITLE_SELECTOR  = "p.widget-episodeTitle"
CHAPTER_BODY_SELECTOR       = "div.widget-episodeBody"

_DATE_RE = re.compile(r"\s*(\d{4}年\d{1,2}月\d{1,2}日)公開$")

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
class RawParagraph:
    text: str
    is_blank: bool


@dataclass
class Chapter:
    index: int
    title: str
    category: str
    episode_id: str
    raw_paragraphs: list[RawParagraph] = field(default_factory=list)


@dataclass
class WorkMeta:
    series_id: str
    title: str
    author: str
    description: str
    work_url: str


class KakuyomuScraper:
    def __init__(
        self,
        delay: float = 1.0,
        timeout: int = 15,
        user_agent: str = (
            "Mozilla/5.0 (compatible; kakuyomu-dl/0.1; "
            "+https://github.com/yourname/kakuyomu-dl)"
        ),
    ):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

# Fetch work metadata from __NEXT_DATA__ JSON

    def fetch_work_meta(self, series_id: str) -> WorkMeta:
        url = WORK_URL.format(work_id=series_id)
        data = self._fetch_next_data(url)
        return self._parse_work_meta(data, series_id, url)

    def fetch_meta_and_toc(self, series_id: str) -> tuple[WorkMeta, list[TocEntry], dict]:
        url = WORK_URL.format(work_id=series_id)
        logger.info(f"Fetching work page: {url}")
        data = self._fetch_next_data(url)

        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        meta = self._parse_work_meta(data, series_id, url)
        entries = self._parse_toc(data, series_id)

        logger.info(f"TOC done — {len(entries)} episode(s) found.")
        return meta, entries, apollo

    def fetch_toc(self, series_id: str) -> list[TocEntry]:
        _, entries, _ = self.fetch_meta_and_toc(series_id)
        return entries

    def fetch_chapter(self, entry: TocEntry) -> Chapter:
        logger.info(f"Fetching chapter {entry.index}: {entry.title}")
        soup = self._get_soup(entry.url)

        main_tag = soup.select_one(CHAPTER_MAIN_TITLE_SELECTOR)
        category = main_tag.get_text(strip=True) if main_tag else ""

        sub_tag = soup.select_one(CHAPTER_SUB_TITLE_SELECTOR)
        raw_title = sub_tag.get_text(strip=True) if sub_tag else entry.title
        title = _strip_date(raw_title)

        body_tag = soup.select_one(CHAPTER_BODY_SELECTOR)
        raw_paragraphs: list[RawParagraph] = []
        if body_tag:
            for p in body_tag.find_all("p"):
                is_blank = "blank" in (p.get("class") or [])
                text = self._extract_text(p, is_blank=is_blank)
                raw_paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
        else:
            logger.warning(f"Body not found for episode {entry.episode_id}")

        return Chapter(
            index=entry.index,
            title=title,
            category=category or entry.category,
            episode_id=entry.episode_id,
            raw_paragraphs=raw_paragraphs,
        )

    def fetch_chapters(
        self,
        entries: list[TocEntry],
        indices: Optional[list[int]] = None,
    ) -> list[Chapter]:
        targets = (
            [e for e in entries if e.index in indices]
            if indices is not None
            else entries
        )
        fetch = [e for e in targets if not e.locked]
        skip = [e for e in targets if e.locked]
        if skip:
            logger.info(
                f"Skipping {len(skip)} locked episode(s)"
            )
        chapters: list[Chapter] = []
        for i, entry in enumerate(fetch):
            if i > 0:
                time.sleep(self.delay)
            chapters.append(self.fetch_chapter(entry))
        return chapters

# Extract the __NEXT_DATA__ JSON blob

    def _fetch_next_data(self, url: str) -> dict:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag:
            raise RuntimeError(
                f"__NEXT_DATA__ not found on {url}. "
                "The page structure may have changed."
            )
        return json.loads(tag.string)

    def _parse_work_meta(self, data: dict, series_id: str, url: str) -> WorkMeta:
        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        work_key = f"Work:{series_id}"
        work_node = apollo.get(work_key, {})
        title = work_node.get("title", f"Work {series_id}")

        author = "Unknown"
        author_ref = work_node.get("author", {}).get("__ref", "")
        if author_ref:
            user_node = apollo.get(author_ref, {})
            author = user_node.get("activityName") or user_node.get("name", "Unknown")

        description = work_node.get("introduction", "").strip()

        if not title:
            logger.warning("Work title not found in __NEXT_DATA__")

        return WorkMeta(
            series_id=series_id,
            title=title,
            author=author,
            description=description,
            work_url=url,
        )

    def _parse_toc(self, data: dict, series_id: str) -> list[TocEntry]:
        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        work_key = f"Work:{series_id}"
        work_node = apollo.get(work_key, {})

        toc_refs = work_node.get("tableOfContentsV2", [])
        entries: list[TocEntry] = []
        index = 1

        for toc_ref in toc_refs:
            toc_key = toc_ref.get("__ref", "")
            toc_node = apollo.get(toc_key, {})
            if not toc_node:
                continue

            chapter_val = toc_node.get("chapter")
            chapter_ref = chapter_val.get("__ref", "") if isinstance(chapter_val, dict) else ""
            chapter_node = apollo.get(chapter_ref, {}) if chapter_ref else {}
            category = chapter_node.get("title", "")

            ep_refs = toc_node.get("episodeUnions", [])
            for ep_ref in ep_refs:
                ep_key = ep_ref.get("__ref", "")
                ep_node = apollo.get(ep_key, {})

                typename = ep_node.get("__typename", "") if ep_node else ""
                locked = typename == "EmptyEpisode"

                episode_id = ep_node.get("id", ep_key.split(":")[-1]) if ep_node else ep_key.split(":")[-1]
                raw_title = ep_node.get("title", "") if ep_node else ""
                published_at = ep_node.get("publishedAt", "") if ep_node else ""

                date_match = _DATE_RE.search(raw_title)
                published_on = date_match.group(1) if date_match else published_at[:10]
                title = _strip_date(raw_title)

                entries.append(TocEntry(
                    index=index,
                    title=title,
                    url=EP_URL.format(work_id=series_id, episode_id=episode_id),
                    episode_id=episode_id,
                    category=category,
                    published_on=published_on,
                    locked=locked,
                ))
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
        return p.get_text()

def _strip_date(title: str) -> str:
    return _DATE_RE.sub("", title).strip()
