import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from paths import OUT_DIR

logger = logging.getLogger(__name__)

CACHE_FILENAME = "toc_cache.json"

_KEEP_PREFIXES = (
    "Work:",
    "Episode:",
    "Chapter:",
    "TableOfContentsChapter:",
    "ROOT_QUERY",
)

@dataclass
class UpdateResult:
    has_update: bool
    new_episode_ids: list[str]
    new_episode_titles: list[str]
    old_count: int
    new_count: int

def cache_path(series_id: str, base_dir: str | Path = OUT_DIR) -> Path:
    return Path(base_dir) / series_id / CACHE_FILENAME


def save(apollo_state: dict, series_id: str, base_dir: str | Path = OUT_DIR) -> Path:
    filtered = _filter_apollo(apollo_state, series_id)
    path = cache_path(series_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"TOC cache saved: {path}")
    return path


def load(series_id: str, base_dir: str | Path = OUT_DIR) -> dict | None:
    path = cache_path(series_id, base_dir)
    if not path.exists():
        return None
    logger.info(f"TOC cache loaded: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def diff(old_state: dict, new_state: dict, series_id: str) -> UpdateResult:
    old_episodes = _episode_list(old_state, series_id)
    new_episodes = _episode_list(new_state, series_id)

    old_ids = {ep_id for ep_id, _ in old_episodes}
    added = [(ep_id, title) for ep_id, title in new_episodes if ep_id not in old_ids]

    return UpdateResult(
        has_update=bool(added),
        new_episode_ids=[ep_id for ep_id, _ in added],
        new_episode_titles=[title for _, title in added],
        old_count=len(old_episodes),
        new_count=len(new_episodes),
    )

def _get_author_ref(apollo: dict, series_id: str) -> str | None:
    work_node = apollo.get(f"Work:{series_id}", {})
    return work_node.get("author", {}).get("__ref")


def _filter_apollo(apollo: dict, series_id: str) -> dict:
    author_ref = _get_author_ref(apollo, series_id)

    kept = {}
    for key, value in apollo.items():
        if key.startswith(_KEEP_PREFIXES):
            kept[key] = value
        elif author_ref and key == author_ref:
            kept[key] = value

    return kept


def _episode_list(apollo: dict, series_id: str) -> list[tuple[str, str]]:
    work_node = apollo.get(f"Work:{series_id}", {})
    result: list[tuple[str, str]] = []

    for toc_ref in work_node.get("tableOfContentsV2", []):
        toc_node = apollo.get(toc_ref.get("__ref", ""), {})
        for ep_ref in toc_node.get("episodeUnions", []):
            ep_node = apollo.get(ep_ref.get("__ref", ""), {})
            ep_id = ep_node.get("id", "")
            title = ep_node.get("title", ep_id)
            if ep_id:
                result.append((ep_id, title))

    return result