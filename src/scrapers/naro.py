import logging
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from scrapers import BaseScraper
from utils import parse_series_id

logger = logging.getLogger(__name__)

BASE_URL = "https://{novel}.syosetu.com/"
WORK_URL = BASE_URL + "{work_id}"
EP_URL = BASE_URL + "{work_id}/{episode_id}"
META_URL = "https://api.syosetu.com/{api}/api/?ncode={work_id}&out=json"


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


class NaroScraper(BaseScraper):
    def __init__(
        self,
        delay: float = 1.0,
        timeout: int = 15,
        user_agent: str = (
            "Mozilla/5.0 (compatible; kakuyomu-dl/0.1; "
            "+https://github.com/aotorii/kakuyomu-dl)"
        ),
    ):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.cookies.set("over18", "yes", domain=".syosetu.com")
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_work_meta(self, series_id: str) -> WorkMeta:
        url = self._get_url(series_id)
        data = self._fetch_next_data(url)
        return self.parse_work_meta(data, series_id)

    def fetch_meta_and_toc(
        self, series_id: str
    ) -> tuple[WorkMeta, list[TocEntry], dict]:
        url = self._get_url(series_id)
        logger.info(f"Fetching work page: {url}")
        data = self._fetch_next_data(url)
        meta = self.parse_work_meta(data, series_id)
        entries = self.parse_toc(series_id)
        return meta, entries, data

    def parse_work_meta(self, data: dict, series_id: str) -> WorkMeta:
        url = (
            WORK_URL.format(novel="novel18", work_id=series_id)
            if data["isr18"]
            else WORK_URL.format(novel="ncode", work_id=series_id)
        )
        title = data["title"] or f"Work {series_id}"
        author = data["writer"] or "Unknown"
        description = data["story"].strip() or ""
        status = data["end"] or 1
        character_count = data["length"] or 0
        episode_count = data["general_all_no"] or 0
        published = data["general_firstup"] or ""
        last_episode = data["general_lastup"] or ""
        last_edited = data["novelupdated_at"] or ""

        return WorkMeta(
            series_id=series_id,
            title=title,
            author=author,
            description=description,
            work_url=url,
            status=status,
            character_count=character_count,
            episode_count=episode_count,
            published=published,
            last_episode=last_episode,
            last_edited=last_edited,
        )

    def parse_toc(self, series_id: str) -> None:
        return

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        meta_url, isr18 = META_URL.format(api="novelapi", work_id=series_id), 0
        if "novel18" in url:
            meta_url, isr18 = META_URL.format(api="novel18api", work_id=series_id), 1
        response = self.session.get(meta_url, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()[1]
        data["isr18"] = isr18
        return data

    def _get_soup(self, url: str) -> BeautifulSoup:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def _get_url(self, series_id: str) -> str:
        url = WORK_URL.format(novel="ncode", work_id=series_id)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        if "novel18" in response.url:
            url = WORK_URL.format(novel="novel18", work_id=series_id)
            return url
        return url
