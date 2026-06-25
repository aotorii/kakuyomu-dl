import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from scrapers import BaseScraper, Episode, RawParagraph, TocEntry
from utils import EPOCH, parse_date, parse_series_id, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://{novel}.syosetu.com/"
WORK_URL = BASE_URL + "{work_id}"
META_URL = "https://api.syosetu.com/{api}/api/?ncode={work_id}&out=json"

CHAPTER_TITLE_SELECTOR = "div.c-announce span:not([class])"
EPISODE_TITLE_SELECTOR = "h1.p-novel__title"
EPISODE_BODY_SELECTOR = "div.js-novel-text"


class NaroScraper(BaseScraper):
    EP_URL = "{work_url}" + "/{episode_id}"

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

    def fetch_episode(self, entry: TocEntry) -> Episode:
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
                    is_blank = not p.get_text(strip=True)
                    text = self._extract_text(p, is_blank=is_blank)
                    raw_paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
                if i < len(body_tags) - 1:
                    raw_paragraphs.append(RawParagraph(text="", is_blank=True))
        else:
            logger.warning(f"Body not found for episode {entry.episode_id}")

        return Episode(
            index=entry.index,
            title=title,
            category=category,
            episode_id=entry.episode_id,
            raw_paragraphs=raw_paragraphs,
        )

    # def parse_work_meta(self, data: dict, series_id: str) -> WorkMeta:
    #     url = WORK_URL.format(
    #         novel="novel18" if data.get("isr18") else "ncode", work_id=series_id
    #     )
    #     title = data.get("title", f"Work {series_id}")
    #     author = data.get("writer", "Unknown")
    #     description = data.get("story", "")
    #     status = data.get("end", 1)
    #     character_count = data.get("length", 0)
    #     episode_count = data.get("general_all_no", 0)
    #     published = data.get("general_firstup", "")
    #     last_episode = data.get("general_lastup", "")
    #     last_edited = data.get("novelupdated_at", "")

    #     return WorkMeta(
    #         series_id=series_id,
    #         title=title.strip(),
    #         author=author.strip(),
    #         description=description.strip(),
    #         work_url=url,
    #         status=status,
    #         character_count=character_count,
    #         episode_count=episode_count,
    #         published=published,
    #         last_episode=last_episode,
    #         last_edited=last_edited,
    #     )

    # def parse_toc(self, data: dict, series_id: str) -> list[TocEntry]:
    #     eplist = data.get("eplist", [])
    #     isr18 = data.get("isr18")
    #     base_url = BASE_URL.format(novel="novel18" if isr18 else "ncode")
    #     entries: list[TocEntry] = []
    #     index, category = 1, ""
    #     for entry in eplist:
    #         classes = entry.get("class", [])
    #         if "p-eplist__chapter-title" in classes:
    #             category = entry.get_text(strip=True)
    #             continue
    #         ep = entry.select_one("a.p-eplist__subtitle")
    #         title = ep.get_text(strip=True) if ep else ""
    #         href = ep.get("href", "") if ep else ""
    #         episode_id = href.split("/")[2] if href else ""
    #         update = entry.select_one("div.p-eplist__update")
    #         published_at = (
    #             (update.find(string=True, recursive=False) or "").strip()
    #             if update
    #             else ""
    #         )
    #         published_on = published_at.split(" ")[0].replace("/", "-")
    #         entries.append(
    #             TocEntry(
    #                 index=index,
    #                 title=title,
    #                 url=urljoin(base_url, href),
    #                 episode_id=episode_id,
    #                 category=category,
    #                 published_on=published_on,
    #             )
    #         )
    #         index += 1
    #     return entries

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

    def _get_url(self, series_id: str) -> str:
        url = WORK_URL.format(novel="ncode", work_id=series_id)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        if "novel18" in response.url:
            url = WORK_URL.format(novel="novel18", work_id=series_id)
            return url
        return url

    def _apolloize(self, data: dict, series_id: str) -> dict:
        apollo = {}
        user_account = {}
        work = {}
        user_id = data.get("userid", "0000000")
        ncode = data.get("ncode", "").lower() or series_id
        url = WORK_URL.format(
            novel="novel18" if data.get("isr18") else "ncode", work_id=ncode
        )
        title = data.get("title", f"Work {ncode}")
        published = data.get("general_firstup", "")
        last_published = data.get("general_lastup", "")
        activity_name = data.get("writer", "Unknown")
        introduction = data.get("story", "")
        keyword = data.get("keyword", "")
        status = data.get("end", 1)
        episode_count = data.get("general_all_no", 0)
        char_count = data.get("length", 0)
        edited = data.get("novelupdated_at", "")
        eplist = data.get("eplist", [])
        episodes, chapters, toc_ch, toc = self._parse_eplist(eplist)
        user_account.update({
            "__typename": "UserAccount",
            "id": f"{user_id}",
            "name": f"{user_id}",
            "activityName": activity_name.strip(),
        })
        work.update({
            "__typename": "Work",
            "id": ncode,
            "title": title.strip(),
            "author": {"__ref": f"UserAccount:{user_id}"},
            "publishedAt": parse_date(published) or EPOCH,
            "lastEpisodePublishedAt": parse_date(last_published) or EPOCH,
            "introduction": introduction.strip(),
            "tagLabels": keyword.split(),
            "serialStatus": parse_status(status).upper(),
            "publicEpisodeCount": episode_count,
            "totalCharacterCount": char_count,
            "editedAt": parse_date(edited) or EPOCH,
            "tableOfContentsV2": toc,
            "url": url,
        })
        apollo.update({
            f"UserAccount:{user_id}": user_account,
            f"Work:{ncode}": work,
            **episodes,
            **chapters,
            **toc_ch,
        })
        return apollo

    def _parse_eplist(self, eplist: list[Tag]) -> tuple[dict, dict, dict, list]:
        episodes = {}
        chapters = {}
        toc_ch = {}
        ch_index, ch_id, toc = 0, "", []
        toc_ch["TableOfContentsChapter:"] = {
            "__typename": "TableOfContentsChapter",
            "id": "",
            "episodeUnions": [],
            "chapter": None,
        }
        for tag in eplist:
            classes = tag.get("class", [])
            if "p-eplist__chapter-title" in classes:
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
                continue
            ep = tag.select_one("a.p-eplist__subtitle")
            ep_title = ep.get_text(strip=True) if ep else ""
            href = ep.get("href", "") if ep else ""
            ep_id = href.split("/")[2] if href else ""
            update = tag.select_one("div.p-eplist__update")
            published_at = (
                (update.find(string=True, recursive=False) or "")
                .strip()
                .replace("/", "-")
                if update
                else ""
            )
            if published_at:
                published_at += ":00"
            toc_ch[f"TableOfContentsChapter:{ch_id}"]["episodeUnions"].append({
                "__ref": f"Episode:{ep_id}"
            })
            episodes[f"Episode:{ep_id}"] = {
                "__typename": "Episode",
                "id": ep_id,
                "title": ep_title,
                "publishedAt": parse_date(published_at).replace("Z", ".000Z"),
            }
        if not toc_ch.get("TableOfContentsChapter:").get("episodeUnions"):
            del toc_ch["TableOfContentsChapter:"]
        for key, entry in toc_ch.items():
            if entry.get("episodeUnions"):
                toc.append({"__ref": key})

        return episodes, chapters, toc_ch, toc
