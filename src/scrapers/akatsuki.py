import logging

import requests

from scrapers import BaseScraper, Episode, TocEntry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.akatsuki-novels.com/"
WORK_URL = BASE_URL + "stories/index/novel_id~{work_id}"


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
        self.session.headers.update({"User-Agent": user_agent})

        def fetch_episode(self, entry: TocEntry, illus: bool = True) -> Episode:
            return

        def fetch_image(self, url: str) -> tuple[bytes, str]:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            content_type = (
                r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            )
            return r.content, content_type

        def _fetch_next_data(self, url: str) -> dict:
            return

        def _get_url(self, series_id: str) -> str:
            return WORK_URL.format(work_id=series_id)

        def _apolloize(self, data: dict, series_id: str) -> dict:
            return
