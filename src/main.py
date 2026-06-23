import argparse
import json
import logging
import re
import sys
from pathlib import Path

import cache
from config import OUT_DIR, BookmarkUpdateConfig, EpubConfig, FetchConfig
from epub_builder import EpubBuilder
from parser import EpisodeParser
from scrapers import BaseScraper, KakuyomuScraper, NaroScraper
from scrapers.kakuyomu import TocEntry as KakuTocEntry
from utils import display_title, parse_plural, parse_series_id, print_meta
from writer import XhtmlWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRAPERS = {
    r"\d+": KakuyomuScraper,
    r"n\d{4}[a-z]{1,2}": NaroScraper,
}


def parse_episode_selection(spec: str, total: int) -> list[int]:
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
            f"[warning] Ignoring out-of-range episode indices: {invalid}",
            file=sys.stderr,
        )
    return valid


def get_scraper(series_id: str, delay: float) -> BaseScraper:
    for match, cls in SCRAPERS.items():
        if re.fullmatch(match, series_id, re.IGNORECASE):
            return cls(delay=delay)
    print(f"[error] Unsupported series ID: {series_id!r}.", file=sys.stderr)
    sys.exit(1)


def print_toc(entries: list[KakuTocEntry]) -> None:
    width = len(str(len(entries)))
    print()
    last_category = object()
    locked_count = 0
    for episode in entries:
        if episode.category != last_category:
            last_category = episode.category
            if episode.category:
                print(f"\n  [{episode.category}]")
        date = f"  ({episode.published_on})" if episode.published_on else ""
        lock = " (locked)" if episode.locked else ""
        print(f"  {str(episode.index).rjust(width)}  {episode.title}{date}{lock}")
        if episode.locked:
            locked_count += 1
    free = len(entries) - locked_count
    print(
        f"\nTotal: {parse_plural('episode', len(entries))} ({free} free, {locked_count} locked)"
    )


def fetch_config_init(config: FetchConfig, args: argparse.Namespace) -> FetchConfig:
    config.overwrite = not args.no_overwrite and config.overwrite
    config.build_epub = args.epub or config.build_epub
    config.clean_title = args.epub_clean or config.clean_title
    config.out_dir = Path(args.out_dir or config.out_dir)
    config.epub_out_dir = Path(args.epub_out_dir or config.epub_out_dir)
    return config


def epub_config_init(config: EpubConfig, args: argparse.Namespace) -> EpubConfig:
    config.xhtml_dir = Path(args.xhtml_dir or config.xhtml_dir)
    config.out_dir = Path(args.out_dir or config.out_dir)
    config.clean_title = args.clean or config.clean_title
    return config


def bookmark_config_init(config: BookmarkUpdateConfig) -> BookmarkUpdateConfig:
    config.xhtml_dir = Path(config.xhtml_dir)
    config.epub_dir = Path(config.epub_dir)
    return config


# Sub-commands


def cmd_toc(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    scraper = KakuyomuScraper(delay=args.delay)
    entries = scraper.fetch_toc(series_id)
    print_toc(entries)


def cmd_fetch(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    config = fetch_config_init(FetchConfig(), args)
    # scraper = KakuyomuScraper(delay=args.delay)
    scraper = get_scraper(series_id, args.delay)
    parser = EpisodeParser()
    xhtml_dir = config.out_dir / series_id / "xhtml"
    writer = XhtmlWriter(
        series_id=series_id, out_dir=xhtml_dir, overwrite=config.overwrite
    )

    print("Fetching work metadata and table of contents…")
    meta, entries, apollo = scraper.fetch_meta_and_toc(series_id)
    print_meta(meta)

    old_apollo = cache.load(series_id)
    if old_apollo:
        result = cache.diff(old_apollo, apollo, series_id)
        if result.has_new_unlocked:
            print(
                f"{parse_plural('episode', len(result.new_unlocked), 'new available ')} since last fetch:"
            )
            for title in result.new_unlocked:
                print(f"  + {title}")
        if result.has_update:
            print(
                f"{parse_plural('episode', len(result.new_episode_ids), 'new ')} since last fetch:"
            )
            for title, is_free in result.new_episode_titles:
                lock = " (locked)" if not is_free else ""
                print(f"  + {title}{lock}")
        else:
            print("No new episodes since last fetch.")

    cache.save(apollo, series_id)

    if args.episodes:
        indices = parse_episode_selection(args.episodes, len(entries))
        if not indices:
            print("[error] No valid episodes selected.", file=sys.stderr)
            sys.exit(1)
        to_fetch = len(indices)
        print(f"Fetching {parse_plural('episode', to_fetch)}: {indices}")
    else:
        indices = None
        to_fetch = len(entries)
        print(f"Fetching all {parse_plural('episode', to_fetch)}…")

    if not config.overwrite:
        written_indices = [
            int(xhtml.stem.split("_")[0])
            for xhtml in (xhtml_dir.glob("*.xhtml") if xhtml_dir.exists() else [])
        ]
        entries_indices = [entry.index for entry in entries]
        indices = (
            [index for index in indices if index not in written_indices]
            if indices is not None
            else [index for index in entries_indices if index not in written_indices]
        )

    if indices == []:
        print(f"Done. All xhtml files already exist, 0 files written to '{xhtml_dir}'.")
    else:
        raw_episodes = scraper.fetch_episodes(entries, indices=indices)
        parsed = parser.parse_many(raw_episodes)
        paths = writer.write_many(parsed)
        exist = (
            f"Skipped {parse_plural('file', to_fetch - len(paths) - sum(1 for episode in entries if episode.locked), 'existing xhtml ')}, "
            if indices
            else ""
        )
        print(
            f"Done. {exist}{parse_plural('file', len(paths))} written to '{xhtml_dir}'."
        )

    if config.build_epub:
        print("Building EPUB…")
        builder = EpubBuilder(
            series_id=series_id,
            xhtml_dir=xhtml_dir,
            out_dir=config.epub_out_dir,
            clean_title=config.clean_title,
        )
        builder.build(meta, entries)
        print(f"Done. EPUB written to: {config.epub_out_dir}")


def cmd_epub(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    scraper = KakuyomuScraper(delay=args.delay)
    apollo = cache.load(series_id)
    config = epub_config_init(EpubConfig(), args)
    xhtml_dir = config.xhtml_dir / series_id / "xhtml"
    filename = args.filename or None

    print("Fetching work metadata and table of contents…")
    if not apollo:
        raise FileNotFoundError(
            f"No matching toc cache found in '{OUT_DIR / series_id}' "
            f"for work {series_id}. Run 'fetch' first."
        )
    meta = scraper.parse_work_meta(apollo, series_id)
    entries = scraper.parse_toc(apollo, series_id)
    print(f"  {'Title':<12}{meta.title}")
    print(f"  {'Author':<12}{meta.author}")
    print(f"  {'Status':<12}{meta.status.capitalize()}")
    print(
        f"  {parse_plural('episode', len(entries) - sum(1 for episode in entries if episode.locked), 'available ')} in TOC."
    )

    print("\nBuilding EPUB…")
    builder = EpubBuilder(
        series_id=series_id,
        xhtml_dir=xhtml_dir,
        out_dir=config.out_dir,
        filename=filename,
        clean_title=config.clean_title,
    )
    builder.build(meta, entries)
    print(f"Done. EPUB written to: {config.out_dir}")


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
    if result.meta_updated:
        print(
            "The workmeta (title, tags, description, etc.) may has been edited since last fetch. Use 'fetch' to update the meta."
        )
    if result.has_new_unlocked:
        print(
            f"{parse_plural('episode', len(result.new_unlocked), 'new available ')} since last fetch:"
        )
        for title in result.new_unlocked:
            print(f"  + {title}")
    if result.has_update:
        print(
            f"{parse_plural('episode', len(result.new_episode_ids), 'new ')} since last fetch:"
        )
        for title, is_free in result.new_episode_titles:
            lock = " (locked)" if not is_free else ""
            print(f"  + {title}{lock}")
    else:
        print(f"Up to date. ({parse_plural('episode', result.new_count)} total)")


def cmd_bookmark(args: argparse.Namespace) -> None:
    FILE = OUT_DIR / "bookmarks.json"
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
                "title": meta.title,
                "author": meta.author,
                "series_id": series_id,
                "status": meta.status.capitalize(),
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

    if args.update:
        config = bookmark_config_init(BookmarkUpdateConfig())
        if config.skip_completed:
            print(
                "Will skip completed series. Use 'check' to check if there is any update for them. You can edit the config file to change the setting."
            )
            bookmarks = [
                series for series in bookmarks if series["status"] != "Completed"
            ]
        for i, series in enumerate(bookmarks):
            title = f"#{i + 1:02d} {series['title']}"
            print(f"\n{display_title(title)}\n")
            series_id = series["series_id"]
            fetch_args = argparse.Namespace(
                series=series_id,
                delay=args.delay,
                episodes=None,
                out_dir=config.xhtml_dir,
                no_overwrite=not config.overwrite,
                epub=True,
                epub_out_dir=config.epub_dir,
                epub_clean=config.clean_title,
            )
            cmd_fetch(fetch_args)
        return

    if args.check:
        for i, series in enumerate(bookmarks):
            title = f"#{i + 1:02d} {series['title']}"
            print(f"\n{display_title(title)}\n")
            series_id = series["series_id"]
            check_args = argparse.Namespace(series=series_id, delay=args.delay)
            cmd_check(check_args)
        return

    print(f"{len(bookmarks)} series found on the bookmark list:")
    for i, series in enumerate(bookmarks):
        print(f"\n#{i + 1:02d}")
        print(f"  {'Title:':<12}{series['title']}")
        print(f"  {'Author:':<12}{series['author']}")
        print(f"  {'Series id:':<12}{series['series_id']}")
        print(f"  {'Status:':<12}{series['status']}")


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
        help="delay between http requests",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    toc_p = subparsers.add_parser("toc", help="list all episodes for a novel")
    toc_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    toc_p.set_defaults(func=cmd_toc)

    fetch_p = subparsers.add_parser("fetch", help="fetch episode content")
    fetch_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    fetch_p.add_argument(
        "--episodes",
        metavar="SPEC",
        help=("select the episodes you want to fetch, examples: '1-7' or '1,3-5,7'"),
    )
    fetch_p.add_argument(
        "--out-dir",
        metavar="DIR",
        help="directory to write xhtml files into",
    )
    fetch_p.add_argument(
        "--no-overwrite",
        action="store_true",
        help="skip episodes whose xhtml file already exists",
    )
    fetch_p.add_argument(
        "--epub",
        action="store_true",
        help="build an epub immediately after fetching episodes",
    )
    fetch_p.add_argument(
        "--epub-out-dir",
        metavar="DIR",
        help="where to write the epub file when using --epub",
    )
    fetch_p.add_argument(
        "--epub-clean",
        action="store_true",
        help="remove possible sale promotion in the novel title when using --epub",
    )
    fetch_p.set_defaults(func=cmd_fetch)

    epub_p = subparsers.add_parser(
        "epub",
        help="build an epub from already fetched xhtml files",
    )
    epub_p.add_argument(
        "series",
        help="series ID or full kakuyomu url",
    )
    epub_p.add_argument(
        "--xhtml-dir",
        metavar="DIR",
        help="directory containing the xhtml episode files",
    )
    epub_p.add_argument(
        "--out-dir",
        metavar="DIR",
        help="where to write the epub file",
    )
    epub_p.add_argument(
        "--filename",
        default="",
        metavar="NAME",
        help="override the output filename",
    )
    epub_p.add_argument(
        "--clean",
        action="store_true",
        help="remove possible sale promotion in the novel title",
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

    bookmark_p = subparsers.add_parser("bookmark", help="list your bookmarks")

    group = bookmark_p.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="check update for all the series on the bookmark list",
    )
    group.add_argument(
        "--update",
        action="store_true",
        help="update all the series on the bookmark list",
    )
    group.add_argument(
        "--delete",
        nargs="+",
        metavar="SERIES",
        help="delete series from your bookmark list",
    )
    group.add_argument(
        "--add", nargs="+", metavar="SERIES", help="add series to your bookmark list"
    )

    bookmark_p.set_defaults(func=cmd_bookmark)

    debug_p = subparsers.add_parser("debug", help="vanilla")
    debug_p.add_argument(
        "series",
        help="series ID or full url",
    )
    debug_p.set_defaults(func=cmd_debug)

    return parser


def cmd_debug(args: argparse.Namespace) -> None:
    series_id = parse_series_id(args.series)
    scraper = get_scraper(series_id, args.delay)
    print(scraper.fetch_work_meta(series_id))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
