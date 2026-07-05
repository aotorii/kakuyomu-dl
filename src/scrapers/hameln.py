import logging
from datetime import datetime

from bs4 import Tag
from scraper import PageSoup, Scraper, default_config

from scrapers import BaseScraper, Episode, RawParagraph, TocEntry, WorkImage
from utils import (
    EPOCH,
    load_cookies,
    parse_date,
    parse_redirect,
    parse_series_id,
    parse_status,
)

logger = logging.getLogger(__name__)

TEST_URL = "https://syosetu.org"

BASE_URL = "https://{novel}.org/"
WORK_URL = BASE_URL + "novel/{work_id}"
META_URL = BASE_URL + "?mode=ss_detail&nid={work_id}"

MAEGAKI_SELECTOR = "div#maegaki"
HONBUN_SELECTOR = "div#honbun"
ATOGAKI_SELECTOR = "div#atogaki"

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
        self.scraper = Scraper(origin=TEST_URL, config=self.config)
        self.scraper.apply_browser_clearance(
            TEST_URL,
            cf_clearance=self.cf_clearance,
            user_agent=self.user_agent,
            cookies=self.cookies,
        )

    def fetch_episode(self, entry: TocEntry) -> Episode:
        logger.info(f"Fetching episode {entry.index}: {entry.title}")
        url = (
            entry.url.rstrip("/1.html") if entry.meta.get("is_short", 0) else entry.url
        )
        soup = self._get_soup_cf(url)

        start_tag = soup.select_one("span#analytics_start").tag
        title_tag = start_tag.find_previous_sibling()
        title_text = list(title_tag.stripped_strings or [])
        category = title_text[0] if len(title_text) > 1 else entry.category
        title = title_text[-1] if title_text else entry.title

        counter = 0
        mae_tag = soup.select_one(MAEGAKI_SELECTOR).tag
        if mae_tag:
            maegaki, counter = self._parse_paragraph(mae_tag, entry.index, counter)
        else:
            maegaki = []

        body_tag = soup.select_one(HONBUN_SELECTOR).tag
        raw_paragraphs: list[RawParagraph] = []
        if body_tag:
            for p in body_tag.find_all("p"):
                img_tag = p.select_one('a[alt="挿絵"]')
                if img_tag:
                    counter += 1
                    raw_paragraphs.append(
                        self._get_image(img_tag, entry.index, counter)
                    )
                    continue
                is_blank = not p.get_text(strip=True)
                text = self._extract_text(p, is_blank=is_blank)
                raw_paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
        else:
            logger.warning(f"Body not found for episode {entry.episode_id}")

        ato_tag = soup.select_one(ATOGAKI_SELECTOR).tag
        if ato_tag:
            atogaki, _ = self._parse_paragraph(ato_tag, entry.index, counter)
        else:
            atogaki = []

        raw_paragraphs = maegaki + raw_paragraphs + atogaki
        return Episode(
            index=entry.index,
            title=title,
            category=category,
            episode_id=entry.episode_id,
            raw_paragraphs=raw_paragraphs,
        )

    def _fetch_next_data(self, url: str) -> dict:
        series_id = parse_series_id(url)
        meta_url, is_r18 = META_URL.format(novel="syosetu", work_id=series_id), 0
        if "h.syosetu" in url:
            meta_url, is_r18 = META_URL.format(novel="h.syosetu", work_id=series_id), 1
        soup = self._get_soup_cf(meta_url)
        meta = soup.select("table.table1")
        meta = [table.tag for table in meta]
        soup = self._get_soup_cf(url)
        eplist = soup.select_one("div table").tag
        data = {}
        data.update({"meta": meta, "eplist": eplist, "is_r18": is_r18})
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
        published = meta.get("掲載開始", "").strip()
        published = published + ":00" if published else ""
        last_published = meta.get("最新投稿", "").strip()
        last_published = last_published + ":00" if last_published else ""
        activity_name = meta.get("作者", "Unknown")
        introduction = meta.get("あらすじ", "")
        keyword_1 = meta.get("必須タグ", "").split()
        keyword_2 = meta.get("タグ", "").split()
        keyword = keyword_1 + [k for k in keyword_2 if k not in keyword_1]
        status_info = meta.get("話数", "").strip()
        status = 0 if "完結" in status_info or "短編" in status_info else 1
        is_short = 1 if "短編 1話" in status_info else 0
        episode_count = int(status_info.rstrip("話").split()[-1]) if status_info else 0
        char_count = int(
            meta.get("合計文字数", "").strip().rstrip("文字").replace(",", "") or 0
        )
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
            ep_edited = [published]
        else:
            eplist = data.get("eplist")
            episodes, chapters, toc_ch, toc, ep_edited = self._parse_eplist(eplist)
        edited = [parse_date(time) or EPOCH for time in ep_edited]
        edited = max(edited, key=lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ"))
        props.update({"is_short": is_short, "is_r18": data.get("is_r18", 0)})
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
            "adminSquareImageUrl": None,
            "author": {"__ref": f"UserAccount:{user_id}"},
            "publishedAt": parse_date(published) or EPOCH,
            "lastEpisodePublishedAt": parse_date(last_published) or EPOCH,
            "introduction": introduction.strip(),
            "tagLabels": keyword,
            "serialStatus": parse_status(status).upper(),
            "publicEpisodeCount": episode_count,
            "totalCharacterCount": char_count,
            "editedAt": edited,
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

    def _parse_metatable(self, data: list[Tag]) -> dict:
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
                    for br in tag.find_all("br"):
                        br.replace_with("\n")
                    for a in tag.find_all("a"):
                        link = a.get("href", "")
                        a.replace_with(parse_redirect(link))
                    value = tag.get_text().strip()
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

    def _parse_eplist(self, eplist: Tag | None) -> tuple[dict, dict, dict, list, list]:
        episodes = {}
        chapters = {}
        toc_ch = {}
        ch_index, ch_id, toc, edited_at = 0, "", [], []
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
                update = tag.select_one("nobr time") or tag.select_one("nobr")
                published_at = (
                    update.find(string=True, recursive=False) or "" if update else ""
                )
                published_at = published_at + ":00" if published_at else ""
                edit = tag.select_one("nobr span")
                text = edit.get("title", "").strip("改稿").strip() if edit else ""
                if text:
                    edited_at.append(text + ":00")
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
        return episodes, chapters, toc_ch, toc, edited_at

    def _get_soup_cf(self, url: str) -> PageSoup:
        soup = self.scraper.get_soup(url, timeout=(self.timeout, 301))
        return soup

    def _parse_paragraph(
        self, tag: Tag, index: int, counter: int = 0
    ) -> tuple[list[RawParagraph], int]:
        paragraphs: list[RawParagraph] = []
        last_child = None
        for child in tag.children:
            if isinstance(child, str):
                if paragraphs and last_child not in ["br", "hr"]:
                    paragraphs[-1].text += child
                else:
                    is_blank = not child.strip()
                    paragraphs.append(RawParagraph(text=child, is_blank=is_blank))
            elif child.name == "br":
                if last_child == "br":
                    paragraphs.append(RawParagraph(text="", is_blank=True))
            elif child.name == "hr":
                if paragraphs and paragraphs[-1].is_blank:
                    paragraphs.pop()
                paragraphs.append(RawParagraph(text="", is_hr=True))
            elif child.name == "a":
                if child.get("alt") == "挿絵":
                    counter += 1
                    paragraphs.append(self._get_image(child, index, counter))
                else:
                    outer = str(child)
                    if paragraphs and last_child not in ["br", "hr"]:
                        paragraphs[-1].text += outer
                    else:
                        paragraphs.append(RawParagraph(text=outer, is_blank=False))
            else:
                is_blank = not child.get_text(strip=True)
                text = self._extract_text(child, is_blank)
                if paragraphs and last_child not in ["br", "hr"]:
                    paragraphs[-1].text += text
                else:
                    paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
            last_child = child.name
        return paragraphs, counter

    def _get_image(self, tag: Tag, index: int, counter: int) -> RawParagraph:
        src = tag.get("href", "")
        if not src:
            raise ValueError(f"Invalid image tag: {str(tag)!r}")
        r = self.scraper.get(src, timeout=self.timeout)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return RawParagraph(
            text="",
            image=WorkImage(
                content=r.content,
                media_type=content_type,
                src=f"{index}_{counter}",
            ),
        )
