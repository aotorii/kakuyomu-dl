import argparse
import logging
import re
import sys

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
    print(f"\nTotal: {len(entries)} chapter(s) ({free} free, {locked_count} locked)")


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
    print(f"  {len(entries)} chapter(s) found ({sum(1 for chapter in entries if chapter.locked)} locked).")

    old_apollo = cache.load(series_id)
    if old_apollo:
        result = cache.diff(old_apollo, apollo, series_id)
        if result.has_update:
            print(f"  {len(result.new_episode_ids)} new episode(s) since last fetch:")
            for title in result.new_episode_titles:
                print(f"    + {title}")
        else:
            print("  No new episodes since last fetch.")

    cache.save(apollo, series_id)

    if args.chapters:
        indices = parse_chapter_selection(args.chapters, len(entries))
        if not indices:
            print("[error] No valid chapters selected.", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching {len(indices)} chapter(s): {indices}")
    else:
        indices = None
        print(f"Fetching all {len(entries)} chapter(s).")

    raw_chapters = scraper.fetch_chapters(entries, indices=indices)

    parsed = parser.parse_many(raw_chapters)

    paths = writer.write_many(parsed)
    print(f"\nDone. {len(paths)} file(s) written to '{writer.out_dir}':")
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
    print(f"  {len(entries)} chapter(s) in TOC.")

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
        print(f"{len(result.new_unlocked)} new available episode(s) since last fetch:")
        for title in result.new_unlocked:
            print(f"  + {title}")
    if result.has_update:
        print(f"{len(result.new_episode_ids)} new episode(s) since last fetch:")
        for title, is_free in result.new_episode_titles:
            lock = " (locked)" if not is_free else ""
            print(f"  + {title}{lock}")
    else:
        print(f"Up to date. ({result.new_count} episode(s) total)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kakuyomu-dl",
        description="Download chapters from kakuyomu web novels",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Delay between HTTP requests",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    toc_p = subparsers.add_parser("toc", help="List all chapters for a novel")
    toc_p.add_argument(
        "series",
        help="Series ID or full kakuyomu URL",
    )
    toc_p.set_defaults(func=cmd_toc)

    fetch_p = subparsers.add_parser("fetch", help="Fetch chapter content")
    fetch_p.add_argument(
        "series",
        help="Series ID or full kakuyomu URL",
    )
    fetch_p.add_argument(
        "--chapters",
        metavar="SPEC",
        help=(
            "Select the chapters you want to fetch. "
            "Examples: '1-5' or '1,3-5,7'."
        ),
    )
    fetch_p.add_argument(
        "--out-dir",
        default=OUT_DIR / "{series_id}/xhtml",
        metavar="DIR",
        help="Directory to write XHTML files into",
    )
    fetch_p.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Skip chapters whose XHTML file already exists",
    )
    fetch_p.add_argument(
        "--epub",
        action="store_true",
        help="Build an EPUB immediately after fetching chapters",
    )
    fetch_p.add_argument(
        "--epub-out-dir",
        default=OUT_DIR / "{series_id}",
        metavar="DIR",
        help="Where to write the .epub file when using --epub",
    )
    fetch_p.set_defaults(func=cmd_fetch)

    epub_p = subparsers.add_parser(
        "epub",
        help="Build an EPUB from already-fetched XHTML files",
    )
    epub_p.add_argument(
        "series",
        help="Series ID or full kakuyomu URL",
    )
    epub_p.add_argument(
        "--xhtml-dir",
        default=OUT_DIR / "{series_id}/xhtml",
        metavar="DIR",
        help="Directory containing the .xhtml chapter files",
    )
    epub_p.add_argument(
        "--out-dir",
        default=OUT_DIR / "{series_id}",
        metavar="DIR",
        help="Where to write the .epub file",
    )
    epub_p.add_argument(
        "--filename",
        default="",
        metavar="NAME",
        help="Override the output filename",
    )
    epub_p.set_defaults(func=cmd_epub)

    check_p = subparsers.add_parser(
        "check",
        help="Check for new episodes",
    )
    check_p.add_argument(
        "series",
        help="Series ID or full kakuyomu URL",
    )
    check_p.set_defaults(func=cmd_check)

    return parser

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
