import logging
import re

import requests
from bs4 import Tag

from scrapers import BaseScraper, Episode, RawParagraph, TocEntry, WorkImage
from utils import EPOCH, parse_date, parse_redirect, parse_series_id, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://www.akatsuki-novels.com/"
WORK_URL = BASE_URL + "stories/index/novel_id~{work_id}"
META_URL = "https://www.akatsuki-novels.com/novels/view/{work_id}"

EP_URL = BASE_URL + "stories/view/{episode_id}/novel_id~{work_id}"


EPISODE_TITLE_SELECTOR = "h2"
EPISODE_BODY_SELECTOR = "div.body-novel"

META_FILTER = [
    "あらすじ",
    "種別",
    "年齢制限",
    "文字数",
    "掲載日",
    "最終投稿日",
    "完結設定",
    "キーワード",
]


class AkatsukiScraper(BaseScraper):
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

    def fetch_episode(self, entry: TocEntry, illus: bool = True) -> Episode:
        logger.info(f"Fetching episode {entry.index}: {entry.title}")
        soup = self._get_soup(entry.url)

        title_tag = soup.select_one(EPISODE_TITLE_SELECTOR)
        title_text = list(title_tag.stripped_strings or [])
        category = tuple(title_text[:-1]) if title_text else entry.category
        title = title_text[-1] if title_text else entry.title

        body_tags = soup.select(EPISODE_BODY_SELECTOR)
        raw_paragraphs: list[RawParagraph] = []

        def _insert_image(tag: Tag, counter: int = 0) -> RawParagraph:
            src = tag.get("src", "")
            if not src:
                raise ValueError(f"Invalid image tag: {str(tag)!r}")
            src = "https:" + src
            if illus:
                content, content_type = self.fetch_image(src)
                return RawParagraph(
                    text="",
                    image=WorkImage(
                        content=content,
                        media_type=content_type,
                        src=f"{entry.index}_{counter}",
                    ),
                )
            return RawParagraph(
                text=f"【挿絵{entry.index}-{counter}】", image=WorkImage(src=f"{src}")
            )

        def _parse_paragraph(tag: Tag, counter: int = 0) -> list[RawParagraph]:
            paragraphs: list[RawParagraph] = []
            last_child: str | None = None
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
                    outer = str(child)
                    if paragraphs and last_child not in ["br", "hr"]:
                        paragraphs[-1].text += outer
                    else:
                        paragraphs.append(RawParagraph(text=outer, is_blank=False))
                elif child.select("img"):
                    for tag in child.select("img"):
                        counter += 1
                        paragraphs.append(_insert_image(tag, counter))
                elif child.name == "img":
                    counter += 1
                    paragraphs.append(_insert_image(child, counter))
                else:
                    is_blank = not child.get_text(strip=True)
                    text = self._extract_text(child, is_blank)
                    if paragraphs and last_child not in ["br", "hr"]:
                        paragraphs[-1].text += text
                    else:
                        paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
                last_child = child.name
            return paragraphs

        if body_tags:
            for i, tag in enumerate(body_tags):
                counter = sum(1 for p in raw_paragraphs if p.image)
                paragraphs = _parse_paragraph(tag, counter)
                # Remove abundant blank lines
                if i > 0 and paragraphs and paragraphs[0].is_blank:
                    paragraphs.pop(0)
                raw_paragraphs += paragraphs
                if i < len(body_tags) - 1:
                    if raw_paragraphs and raw_paragraphs[-1].is_blank:
                        raw_paragraphs.pop()
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

    def _get_ep_url(self, work_url: str, episode_id: str) -> str:
        series_id = work_url.split("novel_id~")[-1]
        return EP_URL.format(episode_id=episode_id, work_id=series_id)

    def _apolloize(self, data: dict, series_id: str):
        apollo = {}
        user_account = {}
        work = {}
        meta = self._parse_metatable(data.get("meta", None))
        author_tag = data.get("author", None)
        activity_name = author_tag.get_text(strip=True) if author_tag else "Unknown"
        href = author_tag.get("href", "").strip() if author_tag else ""
        user_id = href.strip("/").split("/")[-1] if href else "0000000"
        title_tag = data.get("title", None)
        href = title_tag.get("href", "").strip() if title_tag else ""
        series_id = href.strip("/").split("/")[-1] if href else series_id
        title = title_tag.get_text(strip=True) if title_tag else f"Work {series_id}"
        url = self._get_url(series_id)
        published = meta.get("掲載日", "").strip()
        published = published + " 00秒" if published else ""
        last_published = meta.get("最終投稿日", "").strip()
        last_published = last_published + " 00秒" if last_published else ""
        edited = last_published
        introduction = meta.get("あらすじ", "")
        keyword = meta.get("キーワード", "").strip().split()
        status_info = meta.get("完結設定", "").strip()
        status = 0 if "完結" in status_info or "短編" in status_info else 1
        type_info = meta.get("種別", "").strip()
        match = re.search(r"〔全(\d+)話〕", type_info)
        episode_count = int(match.group(1)) if match else 0
        char_count = int(
            meta.get("文字数", "").strip().rstrip("文字").replace(",", "") or 0
        )
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
            "editedAt": parse_date(edited) or EPOCH,
            "tableOfContentsV2": toc,
            "url": url,
        })
        apollo.update({
            f"UserAccount:{user_id}": user_account,
            f"Work:{series_id}": work,
            **episodes,
            **chapters,
            **toc_ch,
        })
        return apollo

    def _parse_metatable(self, data: Tag | None) -> dict:
        meta = {}
        if not data:
            return meta
        label_tags = data.select("th.fld")
        data_tags = data.select("td.data")
        if len(label_tags) - len(data_tags) != 0:
            raise ValueError("The page structure may have changed.")
        for i, tag in enumerate(label_tags):
            label = tag.get_text(strip=True)
            if label.startswith("あらすじ"):
                data_tag = data_tags[i]
                for br in data_tag.find_all("br"):
                    br.replace_with("\n")
                for a in tag.find_all("a"):
                    link = a.get("href", "")
                    a.replace_with(parse_redirect(link))
                value = data_tag.get_text().strip()
                meta[label] = value
                continue
            if label in META_FILTER:
                value = data_tags[i].get_text(strip=True)
                meta[label] = value
        return meta

    def _parse_eplist(self, eplist: list[Tag | None]) -> tuple[dict, dict, dict, list]:
        episodes = {}
        chapters = {}
        toc_ch = {}
        ch_index, ch_id, toc = 0, "", []
        eplist = [table for table in eplist if table]
        if not eplist:
            return episodes, chapters, toc_ch, toc
        toc_ch["TableOfContentsChapter:"] = {
            "__typename": "TableOfContentsChapter",
            "id": "",
            "episodeUnions": [],
            "chapter": None,
        }

        level, section = 0, {}

        def _flush_chapters(chapters: dict, section: dict, level: int) -> int:
            if len(section) < level:
                for i, (k, v) in enumerate(section.items(), 1):
                    v["level"] = level - len(section) + i
                    chapters[k] = v
                return level
            for i, (k, v) in enumerate(section.items(), 1):
                v["level"] = i
                chapters[k] = v
            return len(section)

        for table in eplist:
            table = table.select_one("tbody")
            for tag in table.select("tr"):
                ep_tag = tag.select_one("td a")
                if ep_tag:
                    if section:
                        level = _flush_chapters(chapters, section, level)
                        section = {}
                    ep_title = ep_tag.get_text(strip=True)
                    href = ep_tag.get("href", "")
                    match = re.search(r"/(\d+)/", href)
                    ep_id = match.group(1) if match else ""
                    update = ep_tag.parent.next_sibling
                    published_at = update.get_text(strip=True) or "" if update else ""
                    published_at = published_at + " 00秒" if published_at else ""
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
                section[f"Chapter:{ch_id}"] = {
                    "__typename": "Chapter",
                    "id": ch_id,
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
        for key in toc_ch:
            toc.append({"__ref": key})
        return episodes, chapters, toc_ch, toc
