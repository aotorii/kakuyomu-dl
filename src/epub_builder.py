import logging
import re
import uuid
from pathlib import Path

from ebooklib import epub

from scrapers import TocEntry, WorkMeta
from utils import (
    EPUB_DIR,
    OUT_DIR,
    SITE_COLORS,
    clean_title,
    generate_colophon,
    generate_cover,
    get_spec,
    parse_plural,
    process_image,
    safe_filename,
    strip_emoji,
)

logger = logging.getLogger(__name__)


DEFAULT_CSS = """\
@charset "UTF-8";

html {
  font-size: 100%;
}

body {
  margin: 2%;
  line-height: 1.8;
  font-size: 1em;
}

body.p-text {
  font-family: "Yu Mincho", "MS Mincho", serif;
  font-size: 1em;
  line-height: 1.8;
  color: #1a1a1a;
  background-color: #fdfbf7;
  text-align: justify;
  text-justify: inter-ideograph;
  margin: 0;
  padding: 0;
  -webkit-text-size-adjust: 100%;
  orphans: 2;
  widows: 2;
}

div.main {
  max-width: 36em;
  margin: 1em auto;
  padding: 0 1.5em;
}

p.chapter-category {
  font-size: 0.78em;
  color: #888;
  margin: 0 0 0.3em 0;
  padding: 0;
  text-indent: 0;
  letter-spacing: 0.08em;
}

h1.chapter-title {
  page-break-after: avoid;
  break-after: avoid;
  font-size: 1.15em;
  font-weight: bold;
  line-height: 1.5;
  margin: 1em 0 2em 0;
  padding-bottom: 0.5em;
  border-bottom: 1px solid #c8b89a;
  letter-spacing: 0.05em;
}

hr.horizontal-break {
  border: none;
  border-top: 4px double #c8b89a;
  margin: 1.5em auto;
  width: 95%;
}

p {
  margin: 0;
  padding: 0;
  text-indent: 1em;
  word-break: normal;
  overflow-wrap: break-word;
  hanging-punctuation: first last allow-end;
}

p:has(> br) {
  text-indent: 0;
  line-height: 1.2;
}

p.scene-break-deco {
  text-align: center;
  text-indent: 0;
  color: #888;
  margin: 0.2em 0;
  letter-spacing: 0.5em;
}

ruby {
  ruby-align: center;
}

rt {
  font-size: 0.5em;
  line-height: 1;
}

em {
  font-style: normal;
  font-weight: bold;
}

span.sesame {
  -webkit-text-emphasis: sesame;
  text-emphasis: sesame;
  -webkit-text-emphasis-position: under right;
  text-emphasis-position: under right;
}

blockquote {
  margin: 1em 2em;
  padding: 0;
  font-style: normal;
}

img.fit {
  max-width: 100%;
  max-height: 100vh;
  width: auto;
  height: auto;
  display: block;
  margin: 0 auto;
  page-break-inside: avoid;
  break-inside: avoid;
}

div.page-break {
  page-break-after: always;
  break-after: page;
}
"""


class EpubBuilder:
    def __init__(
        self,
        series_id: str = "",
        xhtml_dir: str | Path = OUT_DIR / "{series_id}",
        out_dir: str | Path = EPUB_DIR,
        filename: str | None = None,
        cover: bytes | None = None,
        clean_title: bool = False,
        language: str = "ja",
    ):
        self.xhtml_dir = Path(str(xhtml_dir).format(series_id=series_id))
        self.out_dir = Path(str(out_dir))
        self.filename = filename
        self.cover = cover
        self.clean = clean_title
        self.language = language

    def build(self, meta: WorkMeta, toc_entries: list[TocEntry]) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        xhtml_dir = self.xhtml_dir / "xhtml"
        image_dir = self.xhtml_dir / "image"
        visual_path = next(image_dir.glob("visual.*"), None)
        cover_path = next(image_dir.glob("alter_cover.*"), None)

        book = epub.EpubBook()
        title = clean_title(meta.title, self.clean)
        site = self._get_cover(meta.work_url)
        identifier = site.get("id")
        book.set_identifier(f"{identifier}-{meta.series_id}-{uuid.uuid4().hex[:8]}")
        book.set_title(title)
        book.set_language(self.language)
        book.add_author(meta.author)

        set_cover = process_image(self.cover, 1400, 2000) if self.cover else None
        key_visual_bytes = visual_path.read_bytes() if visual_path else None
        alter_cover = cover_path.read_bytes() if cover_path else None
        if alter_cover:
            cover = process_image(alter_cover, 1400, 2000)
        else:
            cover = generate_cover(
                strip_emoji(title), strip_emoji(meta.author), site, key_visual_bytes
            )
        book.set_cover("image/cover.jpg", set_cover or cover)

        if meta.description:
            book.add_metadata("DC", "description", meta.description)

        book.add_metadata("DC", "source", meta.work_url)

        css = epub.EpubItem(
            uid="style_default",
            file_name="style/style.css",
            media_type="text/css",
            content=DEFAULT_CSS.encode("utf-8"),
        )
        book.add_item(css)

        file_by_episode: dict[str, Path] = {}
        for xhtml_path in xhtml_dir.glob("*.xhtml"):
            stem = xhtml_path.stem
            parts = stem.split("_", 1)
            episode_id = parts[1] if len(parts) == 2 else stem
            file_by_episode[episode_id] = xhtml_path

        epub_chapters: list[epub.EpubHtml] = []
        chapter_by_episode: dict[str, epub.EpubHtml] = {}
        missing: list[int] = []

        for entry in toc_entries:
            xhtml_path = file_by_episode.get(entry.episode_id)
            if xhtml_path is None:
                if not entry.locked:
                    missing.append(entry.index)
                continue

            chapter = epub.EpubHtml(
                uid=f"chapter_{entry.episode_id}",
                title=entry.title,
                file_name=f"text/{xhtml_path.name}",
                lang=self.language,
                content=xhtml_path.read_bytes(),
            )
            chapter.add_item(css)
            book.add_item(chapter)
            epub_chapters.append(chapter)
            chapter_by_episode[entry.episode_id] = chapter

        if not epub_chapters:
            raise FileNotFoundError(
                f"No matching xhtml files found in '{xhtml_dir}' "
                f"for work {meta.series_id}. Run 'fetch' first."
            )
        if missing:
            logger.warning(
                f"{parse_plural('entry', len(missing), 'TOC ')} have no matching xhtml file "
                f"(run 'fetch' to download them): [{','.join(get_spec(missing))}]"
            )

        entries = [
            (
                entry.category or (),
                epub.Link(
                    chapter_by_episode[entry.episode_id].file_name
                    + f"#toc-{entry.index:03d}",
                    entry.title,
                    chapter_by_episode[entry.episode_id].id,
                ),
            )
            for entry in toc_entries
            if entry.episode_id in chapter_by_episode
        ]
        book.toc = self._build_toc(entries)

        if image_dir.exists():
            for img_path in sorted(image_dir.glob("*")):
                content = process_image(img_path.read_bytes())
                epub_img = epub.EpubImage(
                    uid=f"img_{img_path.stem}",
                    file_name=f"image/{img_path.stem}.jpg",
                    media_type="image/jpeg",
                    content=content,
                )
                book.add_item(epub_img)

        colophon = epub.EpubHtml(
            uid="colophon",
            title="奥付",
            file_name="text/colophon.xhtml",
            lang=self.language,
        )
        colophon.content = generate_colophon(meta, self.clean)
        book.add_item(colophon)
        book.toc = book.toc + (epub.Link("text/colophon.xhtml", "奥付", "colophon"),)

        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        book.spine = ["cover", "nav"] + epub_chapters + [colophon]

        safe_title = safe_filename(title)
        out_filename = self.filename or f"{safe_title}.epub"
        out_path = self.out_dir / out_filename

        epub.write_epub(str(out_path), book)
        logger.info(f"EPUB written: {out_path}")
        return out_path

    def _get_cover(self, url: str) -> dict:
        for match, value in SITE_COLORS.items():
            if re.search(match, url, re.IGNORECASE):
                return value
        raise ValueError(f"Unknown url: {url!r}")

    def _build_toc(
        self, entries: list[tuple[tuple[str, ...], epub.Link]], depth: int = 0
    ) -> tuple:
        result = []
        i, n = 0, len(entries)
        while i < n:
            category, link = entries[i]
            if depth >= len(category):
                result.append(link)
                i += 1
                continue

            key = category[depth]
            group = []
            j = i
            while j < n:
                c2, l2 = entries[j]
                if depth < len(c2) and c2[depth] == key:
                    group.append((c2, l2))
                    j += 1
                else:
                    break
            children = self._build_toc(group, depth + 1)
            result.append((epub.Section(key), children))
            i = j
        return tuple(result)
