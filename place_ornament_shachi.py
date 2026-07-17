from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from asset_search import resolve_best_asset
from schematic_utils import load_schematic, paste_schematic as paste_schematic_blocks
from world import FruitJuiceWorldWriter


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_PATH = SCRIPT_DIR.parent.parent / "shachihouse.json"
DEFAULT_ASSETS_ROOT = SCRIPT_DIR / "assets"


def normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def find_target_label(labels: list[dict], target_name: str | None = None) -> dict | None:
    candidates = [label for label in labels if isinstance(label, dict)]
    if target_name:
        normalized_target = normalize_text(target_name)
        preferred = [label for label in candidates if normalize_text(label.get("class")) == normalized_target]
        if preferred:
            return preferred[0]

        preferred = [label for label in candidates if normalized_target in normalize_text(label.get("class"))]
        if preferred:
            preferred.sort(key=lambda label: (0 if label.get("archit_design") else 1, len(str(label.get("class", ""))), str(label.get("class", ""))))
            return preferred[0]

    preferred = [label for label in candidates if normalize_text(label.get("class")) == "ornamentshachi"]
    if preferred:
        return preferred[0]

    preferred = [label for label in candidates if "shachi" in normalize_text(label.get("class"))]
    if preferred:
        preferred.sort(key=lambda label: (0 if label.get("archit_design") else 1, len(str(label.get("class", ""))), str(label.get("class", ""))))
        return preferred[0]

    return None


def choose_asset_path(json_path: Path | None, assets_root: Path, target_name: str | None = None) -> tuple[str, Path]:
    if target_name:
        query = target_name
        asset_path = resolve_best_asset(query, assets_root)
        if asset_path is None:
            raise RuntimeError(f"{query} に対応する .schem アセットが見つかりませんでした")
        return query, asset_path

    if json_path is None:
        raise RuntimeError("--name か --json のどちらかを指定してください")

    with open(json_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    labels = raw.get("labels", []) if isinstance(raw, dict) else []
    label = find_target_label(labels if isinstance(labels, list) else [])
    if label is None:
        raise RuntimeError("ornament_shachi に対応するラベルが見つかりませんでした")

    query = str(label.get("class") or "ornament_shachi")
    asset_path = resolve_best_asset(query, assets_root)
    if asset_path is None:
        raise RuntimeError(f"{query} に対応する .schem アセットが見つかりませんでした")
    return query, asset_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-place a named .schem structure from the assets folder")
    parser.add_argument("--name", default=None, help="Name of the schematic/class to resolve, such as ornament_shachi")
    parser.add_argument("--json", default=str(DEFAULT_JSON_PATH), help="Optional path to a label JSON file; used when --name is omitted")
    parser.add_argument("--assets", default=str(DEFAULT_ASSETS_ROOT), help="Directory that contains .schem files")
    parser.add_argument("--anchor-x", type=int, default=None, help="Anchor X coordinate; defaults to player position")
    parser.add_argument("--anchor-y", type=int, default=None, help="Anchor Y coordinate; defaults to player position")
    parser.add_argument("--anchor-z", type=int, default=None, help="Anchor Z coordinate; defaults to player position")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved placement details without writing blocks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_path = Path(args.json) if args.json else None
    assets_root = Path(args.assets)

    query_name, asset_path = choose_asset_path(json_path, assets_root, args.name)
    width, height, length, offset, placements = load_schematic(asset_path)

    if args.dry_run:
        print(f"label={query_name}")
        print(f"schematic={asset_path}")
        print(f"size={width}x{height}x{length} offset={offset}")
        print(f"blocks={len(placements)}")
        return

    writer = FruitJuiceWorldWriter()
    player_x, player_y, player_z = writer.player_position()
    anchor = (
        player_x if args.anchor_x is None else args.anchor_x,
        player_y if args.anchor_y is None else args.anchor_y,
        player_z if args.anchor_z is None else args.anchor_z,
    )

    placed = paste_schematic_blocks(writer, asset_path, anchor)
    print(f"Placed {placed} blocks from {asset_path.name} at anchor={anchor}")


if __name__ == "__main__":
    main()