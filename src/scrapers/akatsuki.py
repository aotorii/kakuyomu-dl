import logging
import re

import requests
from bs4 import Tag

from scrapers import BaseScraper, TocEntry
from utils import EPOCH, parse_date, parse_redirect, parse_series_id, parse_status

logger = logging.getLogger(__name__)

BASE_URL = "https://www.akatsuki-novels.com/"
WORK_URL = BASE_URL + "stories/index/novel_id~{work_id}"
META_URL = "https://www.akatsuki-novels.com/novels/view/{work_id}"

EP_URL = BASE_URL + "stories/view/{episode_id}/novel_id~{work_id}"

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
        for table in eplist:
            table = table.select_one("tbody")
            for tag in table.select("tr"):
                ep_tag = tag.select_one("td a")
                if ep_tag:
                    ep_title = ep_tag.get_text(strip=True)
                    href = ep_tag.get("href", "")
                    match = re.search(r"/(\d+)/", href)
                    ep_id = int(match.group(1)) if match else ""
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
