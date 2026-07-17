"""Place Minecraft blocks in-world using the color plot ordering.

The script reuses the block classification from AllBlockColorPlot.py and lays
the blocks out as a circular ring near the player, with hue running around the
circumference and lightness stacked radially so sparse slices stay compact.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict

from pyncraft.minecraft import Minecraft

from AllBlockColorPlot import (
	BlockEntry,
	hue_bucket_for_deg,
	is_neutral,
	normalize_minecraft_block_name,
	load_palette_textures,
	rgb_to_hsl,
	resolve_version_dir,
	sort_entries,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VERSION = "1.21.10"
DEFAULT_BASE_Y_OFFSET = -1
DEFAULT_BAND_GAP = 0
DEFAULT_NEUTRAL_THRESHOLD = 0.14

EXCLUDED_KEYWORDS = [
	"pane",
	"fence",
	"wall",
	"door",
	"trapdoor",
	"slab",
	"stair",
	"carpet",
	"bed",
	"banner",
	"sign",
	"head",
	"skull",
	"torch",
	"candle",
	"lever",
	"button",
	"pressure_plate",
	"rail",
	"ladder",
	"vine",
	"sapling",
	"flower",
	"grass",
	"leaves",
	"moss",
	"fern",
	"mushroom",
	"coral",
	"seagrass",
	"kelp",
	"tall_grass",
	"pickles",
	"dripstone",
	"spore",
	"powder_snow",
	"light",
	"portal",
	"command",
	"structure",
	"barrier",
	"jigsaw",
	"debug",
	"end_gateway",
	"end_portal",
	"pink_petals",
	"spore_blossom",
	"decorated_pot",
	"item_frame",
	"glow_item_frame",
	"painting",
	"sign",
	"hanging_sign",
]


def load_placeable_blocks(version_dir, neutral_threshold=DEFAULT_NEUTRAL_THRESHOLD):
	blockdata_path = os.path.join(version_dir, "_blockdata.json")
	palette_path = os.path.join(version_dir, "_palettes.json")

	with open(blockdata_path, "r", encoding="utf-8") as handle:
		raw_data = json.load(handle)

	palette_textures = load_palette_textures(palette_path)
	blocks = raw_data[1:]
	entries = []

	for block in blocks:
		if not isinstance(block, dict):
			continue

		texture = str(block.get("texture", ""))
		if not texture:
			continue

		texture_lower = texture.lower()
		if any(keyword in texture_lower for keyword in EXCLUDED_KEYWORDS):
			continue

		if palette_textures is not None and texture not in palette_textures:
			continue

		sides = block.get("sides", [])
		if not isinstance(sides, list) or len(sides) < 4:
			continue

		rgb = block.get("rgb", [])
		if not isinstance(rgb, list) or len(rgb) != 3:
			continue

		try:
			rgb_tuple = tuple(int(channel) for channel in rgb)
		except (TypeError, ValueError):
			continue

		hue_deg, saturation, lightness = rgb_to_hsl(rgb_tuple)
		neutral = is_neutral(saturation, lightness, rgb_tuple, neutral_threshold)
		bucket_index, bucket_name = (-1, "Neutral") if neutral else hue_bucket_for_deg(hue_deg)

		entries.append(
			BlockEntry(
				name=normalize_minecraft_block_name(texture),
				texture=texture,
				rgb=rgb_tuple,
				hue_deg=hue_deg,
				saturation=saturation,
				lightness=lightness,
				bucket_index=bucket_index,
				bucket_name=bucket_name,
				is_neutral=neutral,
			)
		)

	return entries


def group_entries_by_bucket(entries):
	groups = defaultdict(list)
	order = []

	for entry in entries:
		if entry.is_neutral:
			bucket_name = "Neutral"
		else:
			bucket_name = entry.bucket_name

		if bucket_name not in groups:
			order.append(bucket_name)
		groups[bucket_name].append(entry)

	return order, groups


def choose_band_shape(count):
	if count <= 0:
		return 0, 0

	rows = max(1, int(count ** 0.5))
	cols = (count + rows - 1) // rows
	while (rows - 1) * cols >= count and rows > 1:
		rows -= 1
		cols = (count + rows - 1) // rows
	return cols, rows


def split_entries_into_columns(entries, column_count):
	if column_count <= 0:
		return []

	columns = []
	base_size = len(entries) // column_count
	remainder = len(entries) % column_count
	start = 0

	for column_index in range(column_count):
		column_size = base_size + (1 if column_index < remainder else 0)
		end = start + column_size
		columns.append(entries[start:end])
		start = end

	return columns


def place_ring_band(mc, center_x, center_y, center_z, entries, band_name, angle_start, angle_span, inner_radius):
	if not entries:
		return 0, 0

	band_width, band_height = choose_band_shape(len(entries))
	columns = split_entries_into_columns(entries, band_width)
	max_column_height = 0

	for column_index, column_entries in enumerate(columns):
		angle = angle_start + angle_span * ((column_index + 0.5) / band_width)
		for row_index, entry in enumerate(column_entries):
			radius = inner_radius + row_index + 0.5
			x = center_x + round(radius * math.cos(angle))
			z = center_z + round(radius * math.sin(angle))
			mc.setBlock(x, center_y, z, entry.name)
		if len(column_entries) > max_column_height:
			max_column_height = len(column_entries)

	mc.postToChat(f"Placed {band_name}: {len(entries)} blocks ({band_width}x{max_column_height})")
	return band_width, max_column_height


def sort_and_group(entries):
	sorted_entries = sort_entries(entries)
	bucket_order, groups = group_entries_by_bucket(sorted_entries)
	return sorted_entries, bucket_order, groups


def measure_bucket_layouts(bucket_order, groups):
	layouts = {}
	total_width = 0

	for bucket_name in bucket_order:
		band_entries = sort_entries(groups[bucket_name])
		band_width, band_height = choose_band_shape(len(band_entries))
		layouts[bucket_name] = (band_entries, band_width, band_height)
		total_width += band_width

	total_width += max(0, len(bucket_order) - 1) * DEFAULT_BAND_GAP
	return layouts, total_width


def main():
	version_dir = resolve_version_dir(DEFAULT_VERSION)
	entries = load_placeable_blocks(version_dir, neutral_threshold=DEFAULT_NEUTRAL_THRESHOLD)

	if not entries:
		raise RuntimeError(f"No blocks were loaded from {version_dir}")

	sorted_entries, bucket_order, groups = sort_and_group(entries)
	layouts, total_width = measure_bucket_layouts(bucket_order, groups)
	if total_width <= 0:
		raise RuntimeError("Could not determine ring width for the loaded blocks")
	ring_inner_radius = max(6.0, total_width / (2.0 * math.pi))

	mc = Minecraft.create()
	player_x, player_y, player_z = mc.player.getTilePos()
	base_x = player_x + 2
	base_y = player_y + DEFAULT_BASE_Y_OFFSET
	base_z = player_z + 2

	mc.postToChat(f"Plotting {len(sorted_entries)} blocks as a ring near x={base_x}, y={base_y}, z={base_z}")

	current_angle = -math.pi / 2.0

	for bucket_name in bucket_order:
		band_entries, band_width, band_height = layouts[bucket_name]
		angle_span = (2.0 * math.pi) * (band_width / total_width)
		place_ring_band(
			mc,
			base_x,
			base_y,
			base_z,
			band_entries,
			bucket_name,
			current_angle,
			angle_span,
			ring_inner_radius,
		)
		current_angle += angle_span + (2.0 * math.pi) * (DEFAULT_BAND_GAP / total_width)

	mc.postToChat("All block plot completed")


if __name__ == "__main__":
	main()
