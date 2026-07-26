import logging
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from scrapers import BaseScraper, Episode, RawParagraph, TocEntry, WorkImage
from utils import EPOCH, MITE_RE, parse_date, parse_series_id, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://{novel}.syosetu.com/"
WORK_URL = BASE_URL + "{work_id}"
META_URL = "https://api.syosetu.com/{api}/api/?ncode={work_id}&out=json"
MITE_URL = "https://{uid}.mitemin.net/userpageimage/viewimage/icode/{img_id}"

EP_URL = "{work_url}" + "/{episode_id}"

CHAPTER_TITLE_SELECTOR = "div.c-announce span:not([class])"
EPISODE_TITLE_SELECTOR = "h1.p-novel__title"
EPISODE_BODY_SELECTOR = "div.js-novel-text"

PROPERTY = ["is_short", "is_r18"]


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

    def fetch_episode(self, entry: TocEntry, illus: bool = True) -> Episode:
        logger.info(f"Fetching episode {entry.index}: {entry.title}")
        url = entry.url.rstrip("/1") if entry.meta.get("is_short", 0) else entry.url
        soup = self._get_soup(url)

        main_tag = soup.select_one(CHAPTER_TITLE_SELECTOR)
        category = (main_tag.get_text(strip=True),) if main_tag else entry.category

        sub_tag = soup.select_one(EPISODE_TITLE_SELECTOR)
        title = sub_tag.get_text(strip=True) if sub_tag else entry.title

        body_tags = soup.select(EPISODE_BODY_SELECTOR)
        raw_paragraphs: list[RawParagraph] = []
        if body_tags:
            counter = 0
            for i, body_tag in enumerate(body_tags):
                for p in body_tag.find_all("p"):
                    link_tag = p.select_one("a")
                    img_tag = p.select_one("a img")
                    if img_tag:
                        counter += 1
                        src = link_tag.get("href", "")
                        match = MITE_RE.search(src)
                        if not match:
                            raise ValueError(f"Unknown image source: {src!r}")
                        uid, img_id = match.groups()
                        img_url = MITE_URL.format(uid=uid, img_id=img_id)
                        if illus:
                            content, content_type = self.fetch_image(img_url)
                            raw_paragraphs.append(
                                RawParagraph(
                                    text="",
                                    image=WorkImage(
                                        content=content,
                                        media_type=content_type,
                                        src=f"{entry.index}_{counter}",
                                    ),
                                )
                            )
                            continue
                        raw_paragraphs.append(
                            RawParagraph(
                                text=f"【挿絵{entry.index}-{counter}】",
                                image=WorkImage(src=f"{img_url}"),
                            )
                        )
                        continue
                    is_blank = not p.get_text(strip=True)
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
        if isr18:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            tag = soup.select_one("div.p-novel__author a")
            author_page = tag.get("href", "") if tag else ""
            parsed = urlparse(author_page)
            user_id = parsed.path.strip("/")
            data["userid"] = user_id
        if data.get("novel_type", 1) - 1:
            return data
        eplist, next_page = [], series_id
        while next_page:
            if next_page != series_id:
                time.sleep(self.delay)
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

    def _get_ep_url(self, work_url: str, episode_id: str) -> str:
        return EP_URL.format(work_url=work_url, episode_id=episode_id)

    def _apolloize(self, data: dict, series_id: str) -> dict:
        apollo = {}
        user_account = {}
        work = {}
        props = {}
        user_id = data.get("userid", "0000000") or "0000000"
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
        is_short = data.get("novel_type", 1) - 1
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
            eplist = data.get("eplist", [])
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
            "id": ncode,
            "title": title.strip(),
            "adminCoverImageUrl": None,
            "adminSquareImageUrl": None,
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
            "property": [{"__ref": prop} for prop in PROPERTY],
            **props,
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
            ep_id = href.strip("/").split("/")[-1] if href else ""
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
                "publishedAt": (parse_date(published_at) or EPOCH).replace(
                    "Z", ".000Z"
                ),
            }
        if not toc_ch.get("TableOfContentsChapter:").get("episodeUnions"):
            del toc_ch["TableOfContentsChapter:"]
        for key, entry in toc_ch.items():
            if entry.get("episodeUnions"):
                toc.append({"__ref": key})
        return episodes, chapters, toc_ch, toc
