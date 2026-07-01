import logging
import re

from scraper import PageSoup, Scraper, default_config

from scrapers import BaseScraper, TocEntry
from utils import EPOCH, load_cookies, parse_date, parse_series_id, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://{novel}.org/"
WORK_URL = BASE_URL + "novel/{work_id}"
META_URL = BASE_URL + "?mode=ss_detail&nid={work_id}"

META_FILTER = [
    "タイトル",
    "小説ID",
    "作者",
    "あらすじ",
    "タグ",
    "必須タグ",
    "掲載開始",
    "話数",
    "最新投稿",
    "合計文字数",
]
PROPERTY = ["is_short", "is_r18"]


class HamelnScraper(BaseScraper):
    EP_URL = "{work_url}" + "/{episode_id}.html"

    def __init__(self, delay: float = 1.0, timeout: int = 15):
        self.delay = delay
        self.timeout = timeout
        self.cf_clearance = load_cookies().get("cf_clearance")
        self.user_agent = load_cookies().get("user_agent")
        self.cookies = {"over18": "off"}
        self.config = default_config()
        self.config.min_request_interval = self.delay
        base = BASE_URL.format(novel="syosetu")
        self.scraper = Scraper(origin=base, config=self.config)
        self.scraper.apply_browser_clearance(
            base,
            cf_clearance=self.cf_clearance,
            user_agent=self.user_agent,
            cookies=self.cookies,
        )

    def fetch_episode(self, entry: TocEntry):
        return

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        meta_url, is_r18 = META_URL.format(novel="syosetu", work_id=series_id), 0
        if "h.syosetu" in url:
            meta_url, is_r18 = META_URL.format(novel="h.syosetu", work_id=series_id), 1
        soup = self._get_soup_cf(meta_url)
        meta = soup.select("table.table1")
        soup = self._get_soup_cf(url)
        eplist = soup.select_one("div table")
        data = {}
        data.update({"meta": meta, "eplist": eplist, "is_r18": is_r18})

        # dates = eplist.select("nobr")
        # out = []
        # for date in dates:
        #     out.append(date.find(string=True, recursive=False) or "oops")
        #     out.append(date.get_text() or "oops")
        return data

    def _get_url(self, series_id: str) -> str:
        url = WORK_URL.format(novel="syosetu", work_id=series_id)
        response = self.scraper.get(url, timeout=self.timeout)
        response.raise_for_status()
        if "h.syosetu" in response.url:
            url = WORK_URL.format(novel="h.syosetu", work_id=series_id)
        return url

    def _apolloize(self, data: dict, series_id: str):
        apollo = {}
        user_account = {}
        work = {}
        props = {}
        meta = self._parse_metatable(data.get("meta", []))
        user_id = meta.get("user_id", "0000000") or "0000000"
        series_id = meta.get("小説ID", "") or series_id
        url = WORK_URL.format(
            novel="h.syosetu" if data.get("is_r18") else "syosetu", work_id=series_id
        )
        title = meta.get("タイトル", f"Work {series_id}")
        published = meta.get("掲載開始", "")
        published = (
            re.sub(r"\(.+?\)", "", published).strip() + ":00" if published else ""
        )
        last_published = meta.get("最新投稿", "")
        last_published = (
            re.sub(r"\(.+?\)", "", last_published).strip() + ":00"
            if last_published
            else ""
        )
        activity_name = meta.get("作者", "Unknown")
        introduction = meta.get("あらすじ", "")
        keyword_1 = meta.get("必須タグ", "").split()
        keyword_2 = meta.get("タグ", "").split()
        keyword = keyword_1 + [k for k in keyword_2 if k not in keyword_1]
        status_info = meta.get("話数", "")
        status = 0 if "完結" or "短編" in status_info else 1
        is_short = 1 if "短編" in status_info else 0
        episode_count = int(status_info.rstrip("話").split()[-1]) if status_info else 0
        char_count = int(
            meta.get("合計文字数", "").rstrip("文字").replace(",", "") or 0
        )
        edited = last_published
        if is_short:
            episodes = {
                "Episode:1": {
                    "__typename": "Episode",
                    "id": "1",
                    "title": title.strip(),
                    "publishedAt": (parse_date(published) or EPOCH).replace(
                        "Z", ".000Z"
                    ),
                }
            }
            chapters = {}
            toc_ch = {
                "TableOfContentsChapter:": {
                    "__typename": "TableOfContentsChapter",
                    "id": "",
                    "episodeUnions": [{"__ref": "Episode:1"}],
                    "chapter": None,
                }
            }
            toc = [{"__ref": "TableOfContentsChapter:"}]
        else:
            eplist = data.get("eplist")
            episodes, chapters, toc_ch, toc = self._parse_eplist(eplist)
        props.update({"is_short": is_short, "is_r18": data.get("isr18", 0)})
        user_account.update({
            "__typename": "UserAccount",
            "id": f"{user_id}",
            "name": f"{user_id}",
            "activityName": activity_name.strip(),
        })
        work.update({
            "__typename": "Work",
            "id": series_id,
            "title": title.strip(),
            "author": {"__ref": f"UserAccount:{user_id}"},
            "publishedAt": parse_date(published) or EPOCH,
            "introduction": introduction.strip(),
            "tagLabels": keyword,
            "serialStatus": parse_status(status).upper(),
            "publicEpisodeCount": episode_count,
            "totalCharacterCount": char_count,
            "editedAt": parse_date(edited) or EPOCH,
            "tableOfContentsV2": toc,
            "url": url,
            "property": [{"__ref": prop} for prop in PROPERTY],
            **props,
        })
        apollo.update({
            f"UserAccount:{user_id}": user_account,
            f"Work:{series_id}": work,
            **episodes,
            **chapters,
            **toc_ch,
        })
        return apollo

    def _parse_metatable(self, data: list[PageSoup]) -> dict:
        meta = {}
        for table in data:
            tags = table.select("tr td")
            label, value = "", ""
            for tag in tags:
                if "label" in tag.get("class", []):
                    label = tag.get_text(strip=True)
                    continue
                if label.endswith("タグ"):
                    value = tag.get_text(separator=" ", strip=True)
                    meta[label] = value
                    continue
                if label.startswith("あらすじ"):
                    value = self._get_text_with_br(tag)
                    meta[label] = value
                    continue
                if label.startswith("作者"):
                    link = tag.select_one("a")
                    author_page = link.get("href", "") if link else ""
                    user_id = (
                        author_page.strip("/").split("/")[-1] if author_page else ""
                    )
                    meta["user_id"] = user_id
                if label in META_FILTER:
                    value = tag.get_text(strip=True)
                    meta[label] = value
        return meta

    def _parse_eplist(self, eplist: PageSoup | None) -> tuple[dict, dict, dict, list]:
        episodes = {}
        chapters = {}
        toc_ch = {}
        ch_index, ch_id, toc = 0, "", []
        if not eplist:
            return episodes, chapters, toc_ch, toc
        toc_ch["TableOfContentsChapter:"] = {
            "__typename": "TableOfContentsChapter",
            "id": "",
            "episodeUnions": [],
            "chapter": None,
        }
        for tag in eplist.select("tr"):
            ep_tag = tag.select_one("td a")
            if ep_tag:
                ep_title = ep_tag.get_text(strip=True)
                href = ep_tag.get("href", "")
                ep_id = href.strip(".html").split("/")[-1] if href else ""
                update = tag.select_one("nobr")
                published_at = update.get_text(strip=True) or "" if update else ""
                published_at = (
                    re.sub(r"\(.+?\)", "", published_at).rstrip("(改)") + ":00"
                    if published_at
                    else ""
                )
                toc_ch[f"TableOfContentsChapter:{ch_id}"]["episodeUnions"].append({
                    "__ref": f"Episode:{ep_id}"
                })
                episodes[f"Episode:{ep_id}"] = {
                    "__typename": "Episode",
                    "id": ep_id,
                    "title": ep_title,
                    "publishedAt": (parse_date(published_at) or EPOCH).replace(
                        "Z", ".000Z"
                    ),
                }
                continue
            ch_title = tag.get_text(strip=True)
            ch_index += 1
            ch_id = str(ch_index)
            chapters[f"Chapter:{ch_id}"] = {
                "__typename": "Chapter",
                "id": ch_id,
                "level": 1,
                "title": ch_title,
            }
            toc_ch[f"TableOfContentsChapter:{ch_id}"] = {
                "__typename": "TableOfContentsChapter",
                "id": ch_id,
                "episodeUnions": [],
                "chapter": {"__ref": f"Chapter:{ch_id}"},
            }
        if not toc_ch.get("TableOfContentsChapter:").get("episodeUnions"):
            del toc_ch["TableOfContentsChapter:"]
        for key, entry in toc_ch.items():
            if entry.get("episodeUnions"):
                toc.append({"__ref": key})
        return episodes, chapters, toc_ch, toc

    def _get_soup_cf(self, url: str) -> PageSoup:
        soup = self.scraper.get_soup(url, timeout=(self.timeout, 301))
        return soup

    def _get_text_with_br(self, tag: PageSoup) -> str:
        html = tag.decode_contents()
        html = re.sub(r"<br\s*/?>", "\n", html)
        html = re.sub(r"<[^>]+>", "", html)
        return html.strip()
