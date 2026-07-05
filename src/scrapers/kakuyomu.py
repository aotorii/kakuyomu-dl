import json
import logging

import requests
from bs4 import BeautifulSoup

from scrapers import BaseScraper, Episode, RawParagraph, TocEntry

logger = logging.getLogger(__name__)

BASE_URL = "https://kakuyomu.jp/works/"
WORK_URL = BASE_URL + "{work_id}"

CHAPTER_TITLE_SELECTOR = "p.chapterTitle"
EPISODE_TITLE_SELECTOR = "p.widget-episodeTitle"
EPISODE_BODY_SELECTOR = "div.widget-episodeBody"


class KakuyomuScraper(BaseScraper):
    EP_URL = "{work_url}" + "/episodes/{episode_id}"

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
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_episode(self, entry: TocEntry, illus: bool = True) -> Episode:
        logger.info(f"Fetching episode {entry.index}: {entry.title}")
        soup = self._get_soup(entry.url)

        main_tag = soup.select_one(CHAPTER_TITLE_SELECTOR)
        category = main_tag.get_text(strip=True) if main_tag else entry.category

        sub_tag = soup.select_one(EPISODE_TITLE_SELECTOR)
        title = sub_tag.get_text(strip=True) if sub_tag else entry.title

        body_tags = soup.select(EPISODE_BODY_SELECTOR)
        raw_paragraphs: list[RawParagraph] = []
        if body_tags:
            for i, body_tag in enumerate(body_tags):
                for p in body_tag.find_all("p"):
                    is_blank = "blank" in (p.get("class") or [])
                    text = self._extract_text(p, is_blank=is_blank)
                    raw_paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
                if i < len(body_tags) - 1:
                    raw_paragraphs.append(RawParagraph(text="", is_hr=True))
        else:
            logger.warning(f"Body not found for episode {entry.episode_id}")

        return Episode(
            index=entry.index,
            title=title,
            category=category,
            episode_id=entry.episode_id,
            raw_paragraphs=raw_paragraphs,
        )

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return r.content, content_type

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

    def _get_url(self, series_id: str) -> str:
        return WORK_URL.format(work_id=series_id)

    def _apolloize(self, data: dict, series_id: str) -> dict:
        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        apollo[f"Work:{series_id}"]["url"] = WORK_URL.format(work_id=series_id)
        return apollo
