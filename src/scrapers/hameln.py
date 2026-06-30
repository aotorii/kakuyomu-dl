import logging

from scraper import PageSoup, Scraper, default_config

from scrapers import BaseScraper, TocEntry
from utils import load_cookies, parse_series_id

logger = logging.getLogger(__name__)

BASE_URL = "https://syosetu.org/"
WORK_URL = BASE_URL + "novel/{work_id}"
META_URL = "https://syosetu.org/?mode=ss_detail&nid={work_id}"


class HamelnScraper(BaseScraper):
    EP_URL = "{work_url}" + "/{episode_id}.html"

    def __init__(self, delay: float = 1.0, timeout: int = 15):
        self.delay = delay
        self.timeout = timeout
        self.cf_clearance = load_cookies().get("cf_clearance")
        self.user_agent = load_cookies().get("user_agent")
        self.cookies = {"over18": "off"}

    def fetch_episode(self, entry: TocEntry):
        return

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        meta_url = META_URL.format(work_id=series_id)
        soup = self._get_soup_cf(meta_url)
        meta = soup.select("table.table1")
        soup = self._get_soup_cf(url)
        eplist = soup.select_one("div table")
        data = {}
        data.update({"meta": meta, "eplist": eplist})
        return data

    def _get_url(self, series_id: str) -> str:
        return WORK_URL.format(work_id=series_id)

    def _apolloize(self, data: dict, series_id: str):
        return

    def _get_soup_cf(self, url: str) -> PageSoup:
        config = default_config()
        config.min_request_interval = self.delay
        s = Scraper(origin=BASE_URL, config=config)
        s.apply_browser_clearance(
            BASE_URL,
            cf_clearance=self.cf_clearance,
            user_agent=self.user_agent,
            cookies=self.cookies,
        )
        soup = s.get_soup(url, timeout=(self.timeout, 301))
        return soup
