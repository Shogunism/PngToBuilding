from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class AssetMatch:
    path: Path
    level: int
    normalized_name: str


def normalize_asset_name(value: str) -> str:
    text = Path(str(value)).stem.casefold()
    return "".join(ch for ch in text if ch.isalnum())


def split_asset_tokens(value: str) -> list[str]:
    text = Path(str(value)).stem.casefold().replace("-", "_")
    return [token for token in text.split("_") if token]


def iter_asset_files(assets_root: str | Path, suffixes: Iterable[str] = (".schem",)) -> list[Path]:
    root = Path(assets_root)
    if not root.exists():
        return []

    wanted_suffixes = tuple(suffix.lower() for suffix in suffixes)
    matches: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in wanted_suffixes:
            matches.append(path)
    return matches


def match_asset_candidates(class_name: str, assets_root: str | Path, suffixes: Iterable[str] = (".schem",)) -> list[AssetMatch]:
    query = normalize_asset_name(class_name)
    if not query:
        return []

    query_tokens = split_asset_tokens(class_name)

    candidates: list[AssetMatch] = []
    for path in iter_asset_files(assets_root, suffixes):
        normalized_name = normalize_asset_name(path.name)
        if not normalized_name:
            continue

        if normalized_name == query:
            level = 0
        elif query in normalized_name or normalized_name in query:
            level = 1
        else:
            continue

        candidates.append(AssetMatch(path=path, level=level, normalized_name=normalized_name))

    def candidate_rank(item: AssetMatch) -> tuple[int, int, int, int, str, str]:
        token_count = len(split_asset_tokens(item.path.name))
        exact_token_hits = 0
        if query_tokens:
            candidate_tokens = split_asset_tokens(item.path.name)
            exact_token_hits = sum(1 for token in query_tokens if token in candidate_tokens)

        return (
            item.level,
            0 if exact_token_hits else 1,
            -exact_token_hits,
            token_count,
            len(item.normalized_name),
            str(item.path),
        )

    candidates.sort(key=candidate_rank)
    return candidates


def resolve_best_asset(
    class_name: str,
    assets_root: str | Path,
    suffixes: Iterable[str] = (".schem",),
    chooser: Callable[[list[Path]], Path | None] | None = None,
) -> Path | None:
    candidates = match_asset_candidates(class_name, assets_root, suffixes)
    if not candidates:
        return None

    best_candidate = candidates[0]
    best_level = best_candidate.level
    best_candidates = [candidate.path for candidate in candidates if candidate.level == best_level]
    if len(best_candidates) == 1:
        return best_candidates[0]

    if chooser is not None:
        chosen = chooser(best_candidates)
        if chosen is not None and chosen in best_candidates:
            return chosen

    return best_candidates[0]
