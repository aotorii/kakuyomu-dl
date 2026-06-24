import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scrapers import BaseScraper, TocEntry, WorkMeta
from utils import parse_series_id

logger = logging.getLogger(__name__)

BASE_URL = "https://{novel}.syosetu.com/"
WORK_URL = BASE_URL + "{work_id}"
# EP_URL = BASE_URL + "{work_id}/{episode_id}"
META_URL = "https://api.syosetu.com/{api}/api/?ncode={work_id}&out=json"


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
        entries = self.parse_toc(data, series_id)
        return meta, entries, data

    def parse_work_meta(self, data: dict, series_id: str) -> WorkMeta:
        url = (
            WORK_URL.format(novel="novel18", work_id=series_id)
            if data["isr18"]
            else WORK_URL.format(novel="ncode", work_id=series_id)
        )
        title = data.get("title", f"Work {series_id}")
        author = data.get("writer", "Unknown")
        description = data.get("story", "").strip()
        status = data.get("end", 1)
        character_count = data.get("length", 0)
        episode_count = data.get("general_all_no", 0)
        published = data.get("general_firstup", "")
        last_episode = data.get("general_lastup", "")
        last_edited = data.get("novelupdated_at", "")

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

    def fetch_toc(self, series_id: str) -> list[TocEntry]:
        _, entries, _ = self.fetch_meta_and_toc(series_id)
        return entries

    def parse_toc(self, data: dict, series_id: str) -> list[TocEntry]:
        eplist = data.get("eplist", [])
        isr18 = data.get("isr18")
        base_url = BASE_URL.format(novel="novel18" if isr18 else "ncode")
        entries: list[TocEntry] = []
        index, category = 1, ""
        for entry in eplist:
            classes = entry.get("class", [])
            if "p-eplist__chapter-title" in classes:
                category = entry.get_text(strip=True)
                continue
            ep = entry.select_one("a.p-eplist__subtitle")
            title = ep.get_text(strip=True) if ep else ""
            href = ep.get("href", "") if ep else ""
            episode_id = href.split("/")[2]
            update = entry.select_one("div.p-eplist__update")
            published_at = (
                (update.find(string=True, recursive=False) or "").strip()
                if update
                else ""
            )
            published_on = published_at.split(" ")[0].replace("/", "-")
            entries.append(
                TocEntry(
                    index=index,
                    title=title,
                    url=urljoin(base_url, href),
                    episode_id=episode_id,
                    category=category,
                    published_on=published_on,
                )
            )
            index += 1
        return entries

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        meta_url, isr18 = META_URL.format(api="novelapi", work_id=series_id), 0
        if "novel18" in url:
            meta_url, isr18 = META_URL.format(api="novel18api", work_id=series_id), 1
        response = self.session.get(meta_url, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()[1]
        data["isr18"] = isr18
        eplist, next_page = [], series_id
        while next_page:
            url = urljoin(base_url, next_page)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            eplist.extend(
                soup.select("div.p-eplist__sublist, div.p-eplist__chapter-title")
            )
            tag = soup.select_one("a.c-pager__item--next")
            next_page = tag.get("href", "") if tag else ""
        data["eplist"] = eplist
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
