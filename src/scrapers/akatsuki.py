import logging
import re

import requests

from scrapers import BaseScraper, TocEntry
from utils import parse_series_id

logger = logging.getLogger(__name__)

BASE_URL = "https://www.akatsuki-novels.com/"
WORK_URL = BASE_URL + "stories/index/novel_id~{work_id}"
META_URL = "https://www.akatsuki-novels.com/novels/view/{work_id}"


class AkatsukiScraper(BaseScraper):
    EP_URL = BASE_URL + "stories/view/{episode_id}/novel_id~{work_id}"

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
        self.session.cookies.set(
            "CakeCookie[ALLOWED_ADULT_NOVEL]", "on", domain="www.akatsuki-novels.com"
        )
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_episode(self, entry: TocEntry, illus: bool = True):
        return

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return r.content, content_type

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        meta_url = META_URL.format(work_id=series_id)
        soup = self._get_soup(meta_url)
        meta = soup.select_one("table")
        soup = self._get_soup(url)
        title_tag = soup.select_one("a#LookNovel")
        author_tag = title_tag.find_next("h3").select_one("a")
        final_tag = soup.select_one("span.table_of_contents a")
        final, eplist = 1, []
        if final_tag:
            href = final_tag.get("href", "")
            match = re.search(r"/page~(\d+)/", href)
            final = int(match.group(1)) if match else final
        for i in range(1, final + 1):
            toc_url = url + f"/page~{i}"
            soup = self._get_soup(toc_url)
            eplist.append(soup.select_one("table.list"))
        print(eplist)
        data = {}
        data.update({
            "meta": meta,
            "title": title_tag,
            "author": author_tag,
            "eplist": eplist,
        })
        return data

    def _get_url(self, series_id: str) -> str:
        return WORK_URL.format(work_id=series_id)

    def _apolloize(self, data: dict, series_id: str):
        return
