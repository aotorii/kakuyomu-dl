import argparse
import logging
import re
import sys
import os
import json
import inflect
from pathlib import Path

from scraper import KakuyomuScraper, TocEntry, Chapter
from parser import ChapterParser
from writer import XhtmlWriter
from epub_builder import EpubBuilder
from paths import OUT_DIR
import cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://kakuyomu.jp/works/"


def parse_series_id(value: str) -> str:
    value = value.strip().rstrip("/")
    match = re.search(r"kakuyomu\.jp/works/(\d+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", value):
        return value
    print(f"[error] Could not parse a series ID from: {value!r}", file=sys.stderr)
    sys.exit(1)


def parse_chapter_selection(spec: str, total: int) -> list[int]:
    indices: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            indices.update(range(int(start), int(end) + 1))
        else:
            indices.add(int(part))

    valid = sorted(i for i in indices if 1 <= i <= total)
    invalid = sorted(i for i in indices if i < 1 or i > total)
    if invalid:
        print(
            f"[warning] Ignoring out-of-range chapter indices: {invalid}",
            file=sys.stderr,
        )
    return valid

def parse_plural(noun: str, num: int, prefix: str = "") -> str:
    P = inflect.engine()
    return f"{num} {prefix}{P.plural_noun(noun, num)}"

def print_toc(entries: list[TocEntry]) -> None:
    width = len(str(len(entries)))
    print()
    last_category = object()
    locked_count = 0
    for chapter in entries:
        if chapter.category != last_category:
            last_category = chapter.category
            if chapter.category:
                print(f"\n  [{chapter.category}]")
        date = f"  ({chapter.published_on})" if chapter.published_on else ""
        lock = " (locked)" if chapter.locked else ""
        print(f"  {str(chapter.index).rjust(width)}  {chapter.title}{date}{lock}")
        if chapter.locked:
            locked_count += 1
    free = len(entries) - locked_count
    print(f"\nTotal: {parse_plural('chapter', len(entries))} ({free} free, {locked_count} locked)")


def print_chapter_preview(chapter: Chapter) -> None:
    prose = [p.text for p in chapter.raw_paragraphs if not p.is_blank and p.text]
    print(f"\n{'=' * 60}")
    print(f"Chapter {chapter.index}: {chapter.title}")
    if chapter.category:
        print(f"Category:   {chapter.category}")
    print(f"Episode ID: {chapter.episode_id}")
    print(f"Paragraphs: {len(prose)}")
    print("-" * 60)
    for p in prose[:5]:
        print(f"  {p[:120].replace(chr(10), ' ')}")
    if len(prose) > 5:
        print(f"  ... ({len(prose) - 5} more paragraph(s))")


# Sub-commands

def cmd_toc(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    scraper = KakuyomuScraper(delay=args.delay)
    entries = scraper.fetch_toc(series_id)
    print_toc(entries)


def cmd_fetch(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    scraper = KakuyomuScraper(delay=args.delay)
    parser = ChapterParser()
    writer = XhtmlWriter(series_id=series_id, out_dir=args.out_dir, overwrite=not args.no_overwrite)

    print("Fetching work metadata and table of contents…")
    meta, entries, apollo = scraper.fetch_meta_and_toc(series_id)
    print(f"  Title:  {meta.title}")
    print(f"  Author: {meta.author}")
    print(f"  {parse_plural('chapter', len(entries))} found ({sum(1 for chapter in entries if chapter.locked)} locked).\n")

    old_apollo = cache.load(series_id)
    if old_apollo:
        result = cache.diff(old_apollo, apollo, series_id)
        if result.has_new_unlocked:
            print(f"{parse_plural('episode', len(result.new_unlocked), 'new available ')} since last fetch:")
            for title in result.new_unlocked:
                print(f"  + {title}")
        if result.has_update:
            print(f"  {parse_plural('episode', len(result.new_episode_ids), 'new ')} since last fetch:")
            for title, is_free in result.new_episode_titles:
                lock = " (locked)" if not is_free else ""
                print(f"  + {title}{lock}")
        else:
            print("No new episodes since last fetch.\n")

    cache.save(apollo, series_id)

    if args.chapters:
        indices = parse_chapter_selection(args.chapters, len(entries))
        if not indices:
            print("[error] No valid chapters selected.", file=sys.stderr)
            sys.exit(1)
        print(f"\nFetching {parse_plural('chapter', len(indices))}: {indices}")
    else:
        indices = None
        print(f"\nFetching all {parse_plural('chapter', len(entries))}")

    if args.no_overwrite:
        out_dir = Path(str(args.out_dir).format(series_id=series_id))
        written_indices = [
            int(xhtml.stem.split("_")[0])
            for xhtml in (out_dir.glob("*.xhtml")
            if out_dir.exists() else [])
        ]
        # print(written_indices)
        # return
        entries_indices = [entry.index for entry in entries]
        indices = (
            [index for index in indices if index not in written_indices]
            if indices is not None
            else [index for index in entries_indices if index not in written_indices]
        )

    if indices == []:
        print(f"\nDone. 0 files written to '{writer.out_dir}'.")
        return

    raw_chapters = scraper.fetch_chapters(entries, indices=indices)
    parsed = parser.parse_many(raw_chapters)
    paths = writer.write_many(parsed)
    suffix = ':' if paths else '.'
    print(f"\nDone. {parse_plural('file', len(paths))} written to '{writer.out_dir}'{suffix}")
    for p in paths:
        print(f"  {p}")

    if args.epub:
        print("\nBuilding EPUB…")
        builder = EpubBuilder(series_id=series_id, xhtml_dir=writer.out_dir, out_dir=args.epub_out_dir)
        epub_path = builder.build(meta, entries)
        print(f"EPUB written: {epub_path}")


def cmd_epub(args: argparse.Namespace) -> None:
    """Build an EPUB from already-fetched XHTML files."""
    series_id = parse_series_id(args.series)
    scraper = KakuyomuScraper(delay=args.delay)

    print("Fetching work metadata and table of contents…")
    meta, entries, _ = scraper.fetch_meta_and_toc(series_id)
    print(f"  Title:  {meta.title}")
    print(f"  Author: {meta.author}")
    print(f"  {parse_plural('chapter', len(entries))} in TOC.")

    print("Building EPUB…")
    builder = EpubBuilder(
        series_id=series_id,
        xhtml_dir=str(args.xhtml_dir).format(series_id=series_id),
        out_dir=args.out_dir,
        filename=args.filename or None,
    )
    epub_path = builder.build(meta, entries)
    print(f"Done. EPUB written: {epub_path}")


def cmd_check(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)

    old_apollo = cache.load(series_id)
    if not old_apollo:
        print(f"No cache found for {series_id}. Run 'fetch' first to create one.")
        return

    print("Fetching latest TOC…")
    scraper = KakuyomuScraper(delay=args.delay)
    _, _, new_apollo = scraper.fetch_meta_and_toc(series_id)

    result = cache.diff(old_apollo, new_apollo, series_id)
    if result.has_new_unlocked:
        print(f"{parse_plural('episode', len(result.new_unlocked), 'new available ')} since last fetch:")
        for title in result.new_unlocked:
            print(f"  + {title}")
    if result.has_update:
        print(f"{parse_plural('episode', len(result.new_episode_ids), 'new ')} since last fetch:")
        for title, is_free in result.new_episode_titles:
            lock = " (locked)" if not is_free else ""
            print(f"  + {title}{lock}")
    else:
        print(f"Up to date. ({parse_plural('episode', result.new_count)} total)")

def cmd_bookmark(args: argparse.Namespace) -> None:
    FILE = OUT_DIR / "bookmark.json"
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            bookmarks = json.load(f)
    except FileNotFoundError:
        bookmarks = []
    
    if args.add:
        for series in args.add:
            series_id = parse_series_id(series)
            scraper = KakuyomuScraper(delay=args.delay)
            meta = scraper.fetch_work_meta(series_id)
            if series_id in [dict["series_id"] for dict in bookmarks]:
                print(f"This series is already on your bookmark list: {meta.title}")
                continue
            bookmark = {
                "id": len(bookmarks) + 1,
                "title": meta.title,
                "author": meta.author,
                "series_id": series_id
            }
            bookmarks.append(bookmark)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(bookmarks, f, ensure_ascii=False, indent=4)
        return

    if not bookmarks:
        print("No series found on the bookmark list.")
        return

    if args.delete:
        series_id = [parse_series_id(series) for series in args.delete]
        bookmarks = [dict for dict in bookmarks if dict["series_id"] not in series_id]
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(bookmarks, f, ensure_ascii=False, indent=4)
        return

    if args.fetch:
        for series in bookmarks:
            print(f"\n#{series['id']:02d} {series['title']}\n")
            series_id=series['series_id']
            fetch_args = argparse.Namespace(
                series=series_id,
                delay=args.delay,
                chapters=None,
                out_dir=OUT_DIR/"{series_id}/xhtml",
                ruby="strip",
                no_overwrite=True,
                epub=False,
                epub_out_dir=OUT_DIR/"{series_id}",
            )
            cmd_fetch(fetch_args)
        return
    
    if args.epub:
        for series in bookmarks:
            print(f"\n#{series['id']:02d} {series['title']}\n")
            series_id=series['series_id']
            epub_args = argparse.Namespace(
                series=series_id,
                delay=args.delay,
                xhtml_dir=OUT_DIR/"{series_id}/xhtml",
                out_dir=OUT_DIR/"{series_id}",
                filename=""
            )
            cmd_epub(epub_args)
        return
    
    if args.check:
        for series in bookmarks:
            print(f"\n#{series['id']:02d} {series['title']}\n")
            series_id=series['series_id']
            check_args = argparse.Namespace(
                series=series_id,
                delay=args.delay                
            )
            cmd_check(check_args)
        return

    print(f"{len(bookmarks)} series found on bookmark list:")
    for series in bookmarks:
        print(f"\n#{series['id']:02d}")
        print(f"  Title:  {series['title']}")
        print(f"  Author:  {series['author']}")
        print(f"  series_id:  {series['series_id']}")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kakuyomu-dl",
        description="A downloader to download chapters from kakuyomu web novels.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="delay between HTTP requests",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    toc_p = subparsers.add_parser("toc", help="list all chapters for a novel")
    toc_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    toc_p.set_defaults(func=cmd_toc)

    fetch_p = subparsers.add_parser("fetch", help="fetch chapter content")
    fetch_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    fetch_p.add_argument(
        "--chapters",
        metavar="SPEC",
        help=(
            "select the chapters you want to fetch, "
            "examples: '1-7' or '1,3-5,7'"
        ),
    )
    fetch_p.add_argument(
        "--out-dir",
        default=OUT_DIR / "{series_id}/xhtml",
        metavar="DIR",
        help="directory to write XHTML files into",
    )
    fetch_p.add_argument(
        "--no-overwrite",
        action="store_true",
        help="skip chapters whose XHTML file already exists",
    )
    fetch_p.add_argument(
        "--epub",
        action="store_true",
        help="build an epub immediately after fetching chapters",
    )
    fetch_p.add_argument(
        "--epub-out-dir",
        default=OUT_DIR / "{series_id}",
        metavar="DIR",
        help="where to write the .epub file when using --epub",
    )
    fetch_p.set_defaults(func=cmd_fetch)

    epub_p = subparsers.add_parser(
        "epub",
        help="build an epub from already-fetched xhtml files",
    )
    epub_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    epub_p.add_argument(
        "--xhtml-dir",
        default=OUT_DIR / "{series_id}/xhtml",
        metavar="DIR",
        help="directory containing the .xhtml chapter files",
    )
    epub_p.add_argument(
        "--out-dir",
        default=OUT_DIR / "{series_id}",
        metavar="DIR",
        help="where to write the .epub file",
    )
    epub_p.add_argument(
        "--filename",
        default="",
        metavar="NAME",
        help="override the output filename",
    )
    epub_p.set_defaults(func=cmd_epub)

    check_p = subparsers.add_parser(
        "check",
        help="check for new episodes",
    )
    check_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    check_p.set_defaults(func=cmd_check)

    bookmark_p = subparsers.add_parser(
        "bookmark",
        help="show your bookmark list"
    )

    group = bookmark_p.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="check update for all the series on the bookmark list"
    )
    group.add_argument(
        "--fetch",
        action="store_true",
        help="fetch all the series on the bookmark list"
    )
    group.add_argument(
        "--epub",
        action="store_true",
        help="build epubs for all the series on the bookmark list"
    )
    group.add_argument(
        "--delete",
        nargs="+",
        metavar="SERIES",
        help="delete series from your bookmark list"
    )
    group.add_argument(
        "--add",
        nargs="+",
        metavar="SERIES",
        help="add series to your bookmark list"
    )


    bookmark_p.set_defaults(func=cmd_bookmark)

    return parser

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
