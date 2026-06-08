import logging
import re
import uuid
from pathlib import Path

from ebooklib import epub

from paths import OUT_DIR
from scraper import TocEntry, WorkMeta
from utils import clean_title, generate_cover, parse_plural

logger = logging.getLogger(__name__)

DEFAULT_CSS = """\
@charset "UTF-8";

html {
  font-size: 100%;
}

body.p-text {
  font-family: "Yu Mincho", "MS Mincho", serif;
  font-size: 1em;
  line-height: 1.8;
  color: #1a1a1a;
  background-color: #fdfbf7;
  margin: 0;
  padding: 0;
  -webkit-text-size-adjust: 100%;
  orphans: 2;
  widows: 2;
}

div.main {
  max-width: 36em;
  margin: 3em auto;
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
  font-size: 1.15em;
  font-weight: bold;
  line-height: 1.5;
  margin: 0 0 2em 0;
  padding-bottom: 0.5em;
  border-bottom: 1px solid #c8b89a;
  letter-spacing: 0.05em;
}

p {
  margin: 0;
  padding: 0;
  text-indent: 1em;
  word-break: break-all;
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
  display: block;
  margin: 0 auto;
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
        xhtml_dir: str | Path = OUT_DIR / "{series_id}/xhtml",
        out_dir: str | Path = OUT_DIR / "{series_id}",
        filename: str | None = None,
        clean_title: bool = False,
        language: str = "ja",
    ):
        self.xhtml_dir = Path(str(xhtml_dir).format(series_id=series_id))
        self.out_dir = Path(str(out_dir).format(series_id=series_id))
        self.filename = filename
        self.clean = clean_title
        self.language = language

    def build(self, meta: WorkMeta, toc_entries: list[TocEntry]) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)

        book = epub.EpubBook()
        title = clean_title(meta.title, self.clean)
        book.set_identifier(f"kakuyomu-{meta.series_id}-{uuid.uuid4().hex[:8]}")
        book.set_title(title)
        book.set_language(self.language)
        book.add_author(meta.author)

        cover = generate_cover(title, meta.author)
        book.set_cover("image/cover.jpg", cover)

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
        for xhtml_path in self.xhtml_dir.glob("*.xhtml"):
            stem = xhtml_path.stem
            parts = stem.split("_", 1)
            episode_id = parts[1] if len(parts) == 2 else stem
            file_by_episode[episode_id] = xhtml_path

        epub_chapters: list[epub.EpubHtml] = []
        chapter_by_episode: dict[str, epub.EpubHtml] = {}
        missing: list[str] = []

        for entry in toc_entries:
            xhtml_path = file_by_episode.get(entry.episode_id)
            if xhtml_path is None:
                missing.append(f"[{entry.index}] {entry.title} ({entry.episode_id})")
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
                f"No matching xhtml files found in '{self.xhtml_dir}' "
                f"for work {meta.series_id}. Run 'fetch' first."
            )
        if missing:
            logger.warning(
                f"{parse_plural('entry', len(missing), 'TOC ')} have no matching xhtml file "
                f"(run fetch to download them):\n  " + "\n  ".join(missing)
            )

        any_category = any(e.category for e in toc_entries)

        if not any_category:
            book.toc = tuple(
                epub.Link(
                    chapter_by_episode[e.episode_id].file_name + f"#toc-{e.index:03d}",
                    e.title,
                    chapter_by_episode[e.episode_id].id,
                )
                for e in toc_entries
                if e.episode_id in chapter_by_episode
            )
        else:
            toc_nested = []
            current_section: str | None = None
            current_links: list[epub.Link] = []

            def flush_section():
                if current_section is not None and current_links:
                    toc_nested.append((
                        epub.Section(current_section),
                        tuple(current_links),
                    ))

            for entry in toc_entries:
                if entry.episode_id not in chapter_by_episode:
                    continue
                ch = chapter_by_episode[entry.episode_id]
                link = epub.Link(
                    ch.file_name + f"#toc-{entry.index:03d}", entry.title, ch.id
                )

                if entry.category != current_section:
                    flush_section()
                    current_section = entry.category
                    current_links = [link]
                else:
                    current_links.append(link)

            flush_section()
            book.toc = tuple(toc_nested)

        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        book.spine = ["cover", "nav"] + epub_chapters

        safe_title = _safe_filename(title)
        out_filename = self.filename or f"{safe_title}.epub"
        out_path = self.out_dir / out_filename

        epub.write_epub(str(out_path), book)
        logger.info(f"EPUB written: {out_path}")
        return out_path


def _safe_filename(title: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title)
    safe = safe.strip().replace(" ", "_")
    return safe or "novel"
