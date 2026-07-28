import logging
import re
import time

import requests
from bs4 import Tag

from constants import EPOCH
from models import Episode, RawParagraph, TocEntry, WorkImage
from scrapers import BaseScraper
from utils import parse_date, parse_redirect, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://novelup.plus/"
WORK_URL = BASE_URL + "story/{work_id}"

EP_URL = "{work_url}" + "/{episode_id}"

CHAPTER_TITLE_SELECTOR = "div.episode_chapter"
EPISODE_TITLE_SELECTOR = "div.episode_title"

EPISODE_BODY_SELECTORS = ["p.foreword", "p#episode_content", "p.afterword"]

META_FILTER = [
    "タグ",
    "初掲載日",
    "最終更新日",
    "完結日",
    "文字数",
    "総エピソード数",
]


class NupScraper(BaseScraper):
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

        title_tag = soup.select_one(EPISODE_TITLE_SELECTOR)
        title = title_tag.get_text(strip=True) if title_tag else entry.title
        chapter_tag = soup.select_one(CHAPTER_TITLE_SELECTOR)
        category = (chapter_tag.get_text(strip=True),) if chapter_tag else ()

        body_tags = soup.select(", ".join(EPISODE_BODY_SELECTORS))
        raw_paragraphs: list[RawParagraph] = []

        def _continuous_text(paragraphs: list[RawParagraph]) -> bool:
            return (
                paragraphs and not paragraphs[-1].is_blank and not paragraphs[-1].image
            )

        def _insert_image(tag: Tag, counter: int = 0) -> RawParagraph:
            src = tag.get("src", "")
            if not src:
                raise ValueError(f"Invalid image tag: {str(tag)!r}")
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
            for child in tag.children:
                if isinstance(child, str):
                    for i, line in enumerate(child.splitlines()):
                        is_blank = not line.strip()
                        if i == 0 and _continuous_text(paragraphs) and not is_blank:
                            paragraphs[-1].text += line
                        else:
                            paragraphs.append(
                                RawParagraph(text=line, is_blank=is_blank)
                            )
                    continue
                elif child.select("img"):
                    for tag in child.select("img"):
                        counter += 1
                        paragraphs.append(_insert_image(tag, counter))
                    continue
                elif child.name == "a":
                    outer = str(child)
                    if _continuous_text(paragraphs):
                        paragraphs[-1].text += outer
                    else:
                        paragraphs.append(RawParagraph(text=outer, is_blank=False))
                    continue
                is_blank = not child.get_text(strip=True)
                text = self._extract_text(child, is_blank)
                if _continuous_text(paragraphs):
                    paragraphs[-1].text += text
                    continue
                paragraphs.append(RawParagraph(text=text, is_blank=is_blank))
            return paragraphs

        if body_tags:
            for i, tag in enumerate(body_tags):
                counter = sum(1 for p in raw_paragraphs if p.image)
                paragraphs = _parse_paragraph(tag, counter)
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
        r = self._get_response(url)
        content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return r.content, content_type

    def _fetch_next_data(self, url: str) -> dict:
        soup = self._get_soup(url)
        meta = soup.select_one("table.storyMeta")
        title_tag = soup.select_one("h1.storyTitle")
        author_tag = soup.select_one("a.authorName")
        intro_tag = soup.select_one("div.novel_synopsis")
        cover_tag = soup.select_one("div.novel_cover img")
        final_tag = soup.select_one('a[data-label="最後のページへ"]')
        final, eplist = 1, []
        if final_tag:
            href = final_tag.get("href", "")
            match = re.search(r"\?p=(\d+)", href)
            final = int(match.group(1)) if match else final
        for i in range(1, final + 1):
            if i > 1:
                time.sleep(self.delay)
            toc_url = url + f"?p={i}"
            soup = self._get_soup(toc_url)
            eplist.append(soup.select_one("div.episodeList"))
        data = {}
        data.update({
            "meta": meta,
            "title": title_tag,
            "author": author_tag,
            "intro": intro_tag,
            "eplist": eplist,
            "cover": cover_tag,
        })
        return data

    def _get_url(self, series_id: str) -> str:
        return WORK_URL.format(work_id=series_id)

    def _get_ep_url(self, work_url: str, episode_id: str) -> str:
        return EP_URL.format(work_url=work_url, episode_id=episode_id)

    def _apolloize(self, data: dict, series_id: str) -> dict:
        apollo = {}
        user_account = {}
        work = {}
        meta = self._parse_metatable(data.get("meta", None))
        author_tag = data.get("author", None)
        activity_name = author_tag.get_text(strip=True) if author_tag else "Unknown"
        href = author_tag.get("href", "").strip() if author_tag else ""
        user_id = href.rstrip("/profile").split("/")[-1] if href else "0000000"
        title_tag = data.get("title", None)
        title = title_tag.get_text(strip=True) if title_tag else f"Work {series_id}"
        url = self._get_url(series_id)
        published = meta.get("初掲載日", "").strip()
        published = published + "00秒" if published else ""
        last_published = meta.get("最終更新日", "").strip()
        last_published = last_published + "00秒" if last_published else ""
        edited = last_published
        intro_tag = data.get("intro", None)
        for br in intro_tag.find_all("br"):
            br.replace_with("\n")
        for a in intro_tag.find_all("a"):
            link = a.get("href", "")
            a.replace_with(parse_redirect(link))
        introduction = (
            intro_tag.get_text().strip().replace("\r\n", "\n").replace("\r", "\n")
            if intro_tag
            else ""
        )
        cover_tag = data.get("cover", None)
        alter_cover = cover_tag.get("src", "").strip() if cover_tag else ""
        keyword = meta.get("タグ", [])
        status_info = meta.get("完結日", "-").strip("-")
        status = 0 if status_info else 1
        episode_count = int(meta.get("総エピソード数", "").strip().rstrip("話") or 0)
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
            "adminCoverImageUrl": alter_cover if alter_cover else None,
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
        for tag in data.select("tr"):
            label_tag = tag.select_one("th")
            data_tag = tag.select_one("td")
            label = label_tag.get_text(strip=True)
            if label.startswith("タグ"):
                value = list(data_tag.stripped_strings)
                meta[label] = value
                continue
            if label in META_FILTER:
                value = data_tag.get_text(strip=True)
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

        for table in eplist:
            for item in table.select("div.episodeListItem"):
                classes = item.get("class", [])
                if "chapter" in classes:
                    ch_title = item.get_text(strip=True)
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
                ep = item.select_one("a.episodeTitle")
                ep_title = ep.get_text(strip=True) if ep else ""
                href = ep.get("href", "") if ep else ""
                ep_id = href.strip("/").split("/")[-1] if href else ""
                update = item.select_one("p.publishDate")
                published_at = update.get_text(strip=True) if update else ""
                published_at = "20" + published_at + ":00" if published_at else ""
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
