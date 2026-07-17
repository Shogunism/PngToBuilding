from __future__ import annotations

import re
from pathlib import Path

import nbtlib


def normalize_block_name(raw_name: str) -> str:
    block_name = raw_name.split("[", 1)[0]
    if ":" in block_name:
        block_name = block_name.split(":", 1)[1]
    block_name = re.sub(r"[^a-z0-9]+", "_", block_name.casefold()).strip("_")
    return block_name.upper()


def load_schematic(path: str | Path) -> tuple[int, int, int, tuple[int, int, int], list[tuple[int, int, int, str]]]:
    root = nbtlib.load(Path(path))["Schematic"]
    width = int(root["Width"])
    height = int(root["Height"])
    length = int(root["Length"])
    offset = tuple(int(value) for value in root["Offset"])
    blocks = root["Blocks"]
    palette = {int(index): str(name) for name, index in blocks["Palette"].items()}
    data = [int(value) for value in blocks["Data"]]

    placements: list[tuple[int, int, int, str]] = []
    for y in range(height):
        for z in range(length):
            for x in range(width):
                index = x + z * width + y * width * length
                palette_index = data[index]
                block_name = palette.get(palette_index, "minecraft:air")
                if block_name == "minecraft:air":
                    continue
                placements.append((x, y, z, normalize_block_name(block_name)))

    return width, height, length, offset, placements


def paste_schematic(writer, schem_path: str | Path, anchor: tuple[int, int, int]) -> int:
    _, _, _, offset, placements = load_schematic(schem_path)
    anchor_x, anchor_y, anchor_z = anchor
    count = 0

    for local_x, local_y, local_z, block_name in placements:
        writer.set_block(anchor_x + local_x + offset[0], anchor_y + local_y + offset[1], anchor_z + local_z + offset[2], block_name)
        count += 1

    return count
