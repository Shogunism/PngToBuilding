"""Plot all full Minecraft blocks on a hue/saturation/lightness plane.

The script uses the generated block data and palette information that comes from
hueblocks-derived blockset assets, then:
1. filters to full blocks,
2. classifies them into hue bands,
3. keeps low-saturation blocks in a neutral bucket,
4. sorts by saturation and lightness,
5. renders a PNG scatter plot, and optionally a CSV.
"""

from __future__ import annotations

import argparse
import colorsys
import csv
import json
import os
import re
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VERSION = "1.21.10"
DEFAULT_OUTPUT_IMAGE = os.path.join(SCRIPT_DIR, "AllBlockColorPlot.png")
DEFAULT_OUTPUT_CSV = os.path.join(SCRIPT_DIR, "AllBlockColorPlot.csv")
DEFAULT_NEUTRAL_SATURATION_THRESHOLD = 0.14
DEFAULT_BAND_WIDTH = 260
DEFAULT_BAND_HEIGHT = 660
DEFAULT_MARGIN_X = 28
DEFAULT_MARGIN_Y = 28
DEFAULT_HEADER_HEIGHT = 56
DEFAULT_FOOTER_HEIGHT = 48
DEFAULT_POINT_SIZE = 10

EXCLUDED_KEYWORDS = [
	"glass",
	"dead",
	"shulker_box",
	"coral_block",
	"snow",
	"tnt",
	"ice",
	"slab",
	"stair",
	"fence",
	"wall",
	"door",
	"bed",
	"carpet",
	"sign",
	"banner",
	"head",
	"skull",
]

HUE_BUCKETS = [
	("Red", 345, 15),
	("Orange", 15, 45),
	("Yellow", 45, 75),
	("Yellow-Green", 75, 105),
	("Green", 105, 135),
	("Spring Green", 135, 165),
	("Cyan", 165, 195),
	("Azure", 195, 225),
	("Blue", 225, 255),
	("Indigo", 255, 285),
	("Purple", 285, 315),
	("Magenta", 315, 345),
]


@dataclass(frozen=True)
class BlockEntry:
	name: str
	texture: str
	rgb: tuple[int, int, int]
	hue_deg: float
	saturation: float
	lightness: float
	bucket_index: int
	bucket_name: str
	is_neutral: bool


def normalize_minecraft_block_name(texture_name: str) -> str:
	"""Convert a texture filename into a more block-like display name."""

	block_name = os.path.splitext(texture_name)[0].upper()
	suffixes = [
		"_INVERTED_TOP",
		"_SIDE2",
		"_TOP",
		"_BOTTOM",
		"_SIDE",
		"_FRONT",
		"_BACK",
		"_END",
		"_MIDDLE",
		"_LEFT",
		"_RIGHT",
		"_LIT",
		"_UNLIT",
		"_NORTH",
		"_SOUTH",
		"_EAST",
		"_WEST",
		"_UP",
		"_DOWN",
	]

	changed = True
	while changed:
		changed = False
		for suffix in suffixes:
			if block_name.endswith(suffix):
				block_name = block_name[: -len(suffix)]
				changed = True
				break

	block_name = re.sub(r"_(\d+)$", "", block_name)
	return block_name


def discover_versions() -> list[str]:
	"""Find directories that contain block data."""

	candidate_roots = [
		SCRIPT_DIR,
		os.path.abspath(os.path.join(SCRIPT_DIR, "..", "hueblocks-master", "vueblocks", "data", "blocksets")),
	]

	versions: list[str] = []
	for root in candidate_roots:
		if not os.path.isdir(root):
			continue
		for name in os.listdir(root):
			version_dir = os.path.join(root, name)
			if os.path.isdir(version_dir) and os.path.isfile(os.path.join(version_dir, "_blockdata.json")):
				versions.append(name)

	return sorted(set(versions), reverse=True)


def resolve_version_dir(version: str | None) -> str:
	"""Resolve a version directory from the local workspace layout."""

	search_roots = [
		SCRIPT_DIR,
		os.path.abspath(os.path.join(SCRIPT_DIR, "..", "hueblocks-master", "vueblocks", "data", "blocksets")),
	]

	if version:
		for root in search_roots:
			candidate = os.path.join(root, version)
			if os.path.isfile(os.path.join(candidate, "_blockdata.json")):
				return candidate

		raise FileNotFoundError(f"blockdata.json not found for version '{version}'")

	if os.path.isfile(os.path.join(SCRIPT_DIR, DEFAULT_VERSION, "_blockdata.json")):
		return os.path.join(SCRIPT_DIR, DEFAULT_VERSION)

	versions = discover_versions()
	if not versions:
		raise FileNotFoundError("No version directories with _blockdata.json were found")

	return os.path.join(search_roots[0], versions[0])


def load_palette_textures(palette_path: str) -> set[str] | None:
	"""Load the texture whitelist from the generated palette data."""

	if not os.path.isfile(palette_path):
		return None

	with open(palette_path, "r", encoding="utf-8") as handle:
		data = json.load(handle)

	if not isinstance(data, list):
		return None

	for palette in data:
		if not isinstance(palette, dict):
			continue
		name = str(palette.get("name", "")).lower()
		textures = palette.get("textures", [])
		if "default" in name and isinstance(textures, list) and textures:
			return {str(texture) for texture in textures}

	for palette in data:
		if isinstance(palette, dict):
			textures = palette.get("textures", [])
			if isinstance(textures, list) and textures:
				return {str(texture) for texture in textures}

	return None


def rgb_to_hsl(rgb: Iterable[int]) -> tuple[float, float, float]:
	"""Convert RGB values in the 0..255 range into HSL values."""

	red, green, blue = [channel / 255.0 for channel in rgb]
	hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
	return hue * 360.0, saturation, lightness


def hue_bucket_for_deg(hue_deg: float) -> tuple[int, str]:
	hue_deg = hue_deg % 360.0
	for index, (name, start, end) in enumerate(HUE_BUCKETS):
		if start < end:
			if start <= hue_deg < end:
				return index, name
		elif hue_deg >= start or hue_deg < end:
			return index, name
	return 0, HUE_BUCKETS[0][0]


def is_neutral(saturation: float, lightness: float, rgb: tuple[int, int, int], threshold: float) -> bool:
	"""Decide whether a block should go to the neutral bucket."""

	if saturation <= threshold:
		return True

	return max(rgb) - min(rgb) <= 18 and (lightness <= 0.18 or lightness >= 0.82)


def load_blocks(version_dir: str, neutral_threshold: float) -> list[BlockEntry]:
	"""Load block data, filter full blocks, and classify them by color."""

	blockdata_path = os.path.join(version_dir, "_blockdata.json")
	palette_path = os.path.join(version_dir, "_palettes.json")

	if not os.path.isfile(blockdata_path):
		raise FileNotFoundError(f"Missing block data: {blockdata_path}")

	palette_textures = load_palette_textures(palette_path)

	with open(blockdata_path, "r", encoding="utf-8") as handle:
		raw_data = json.load(handle)

	if not isinstance(raw_data, list):
		raise ValueError("blockdata.json must contain a list")

	blocks = raw_data[1:]
	entries: list[BlockEntry] = []

	for block in blocks:
		if not isinstance(block, dict):
			continue

		texture = str(block.get("texture", ""))
		if not texture:
			continue

		texture_lower = texture.lower()
		if palette_textures is not None and texture not in palette_textures:
			continue

		if any(keyword in texture_lower for keyword in EXCLUDED_KEYWORDS):
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


def sort_entries(entries: list[BlockEntry]) -> list[BlockEntry]:
	"""Sort by hue bucket, then saturation, then lightness."""

	def sort_key(entry: BlockEntry) -> tuple:
		if entry.is_neutral:
			return (len(HUE_BUCKETS), 0.0, entry.lightness, entry.hue_deg, entry.name.lower(), entry.texture.lower())
		return (entry.bucket_index, entry.saturation, entry.lightness, entry.hue_deg, entry.name.lower(), entry.texture.lower())

	return sorted(entries, key=sort_key)


def draw_grid(draw: ImageDraw.ImageDraw, left: int, top: int, width: int, height: int) -> None:
	"""Render a lightweight saturation/lightness grid."""

	grid_color = (225, 229, 235)
	axis_color = (176, 184, 194)

	for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
		x = left + round(width * fraction)
		y = top + round(height * (1.0 - fraction))
		draw.line((x, top, x, top + height), fill=grid_color)
		draw.line((left, y, left + width, y), fill=grid_color)

	draw.rectangle((left, top, left + width, top + height), outline=axis_color, width=2)


def contrast_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
	"""Return black or white depending on background brightness."""

	luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
	return (20, 20, 20) if luminance > 0.62 else (250, 250, 250)


def draw_bucket(
	canvas: Image.Image,
	entries: list[BlockEntry],
	title: str,
	band_left: int,
	band_top: int,
	band_width: int,
	band_height: int,
	point_size: int,
) -> None:
	"""Draw one hue bucket or the neutral bucket."""

	draw = ImageDraw.Draw(canvas)
	padding = 18
	plot_left = band_left + padding
	plot_top = band_top + padding + 6
	plot_width = band_width - padding * 2
	plot_height = band_height - padding * 2 - 12

	draw.rounded_rectangle(
		(band_left + 3, band_top + 3, band_left + band_width - 3, band_top + band_height - 3),
		radius=16,
		fill=(248, 249, 251),
		outline=(216, 220, 228),
		width=2,
	)
	draw_grid(draw, plot_left, plot_top, plot_width, plot_height)

	font = ImageFont.load_default()
	title_bbox = draw.textbbox((0, 0), title, font=font)
	title_width = title_bbox[2] - title_bbox[0]
	draw.text((band_left + (band_width - title_width) / 2, band_top + 5), title, fill=(35, 41, 49), font=font)

	count_label = f"{len(entries)} blocks"
	count_bbox = draw.textbbox((0, 0), count_label, font=font)
	count_width = count_bbox[2] - count_bbox[0]
	draw.text(
		(band_left + (band_width - count_width) / 2, band_top + band_height - 15),
		count_label,
		fill=(84, 92, 104),
		font=font,
	)

	if not entries:
		return

	for entry in entries:
		if entry.is_neutral:
			x_pos = plot_left + plot_width * 0.5
			y_pos = plot_top + (1.0 - entry.lightness) * plot_height
		else:
			x_pos = plot_left + entry.saturation * plot_width
			y_pos = plot_top + (1.0 - entry.lightness) * plot_height

		radius = point_size / 2
		outline = contrast_color(entry.rgb)
		draw.ellipse(
			(x_pos - radius, y_pos - radius, x_pos + radius, y_pos + radius),
			fill=entry.rgb,
			outline=outline,
			width=1,
		)


def save_csv(entries: list[BlockEntry], csv_path: str) -> None:
	"""Save the sorted classification to CSV."""

	with open(csv_path, "w", newline="", encoding="utf-8") as handle:
		writer = csv.writer(handle)
		writer.writerow(["order", "bucket", "texture", "name", "rgb", "hue_deg", "saturation", "lightness", "neutral"])
		for index, entry in enumerate(entries, 1):
			writer.writerow(
				[
					index,
					entry.bucket_name,
					entry.texture,
					entry.name,
					f"{entry.rgb[0]},{entry.rgb[1]},{entry.rgb[2]}",
					f"{entry.hue_deg:.2f}",
					f"{entry.saturation:.4f}",
					f"{entry.lightness:.4f}",
					"yes" if entry.is_neutral else "no",
				]
			)


def build_plot(entries: list[BlockEntry], output_path: str, point_size: int) -> None:
	"""Build and save the full color plot image."""

	hue_entries = [entry for entry in entries if not entry.is_neutral]
	neutral_entries = [entry for entry in entries if entry.is_neutral]

	grouped: list[tuple[str, list[BlockEntry]]] = []
	for bucket_index, (name, _, _) in enumerate(HUE_BUCKETS):
		bucket_entries = [entry for entry in hue_entries if entry.bucket_index == bucket_index]
		grouped.append((name, bucket_entries))
	grouped.append(("Neutral", neutral_entries))

	band_count = len(grouped)
	width = DEFAULT_MARGIN_X * 2 + band_count * DEFAULT_BAND_WIDTH
	height = DEFAULT_MARGIN_Y * 2 + DEFAULT_HEADER_HEIGHT + DEFAULT_BAND_HEIGHT + DEFAULT_FOOTER_HEIGHT

	canvas = Image.new("RGB", (width, height), (255, 255, 255))
	draw = ImageDraw.Draw(canvas)
	font = ImageFont.load_default()

	title = "Minecraft Full Block Color Map"
	subtitle = "x = saturation, y = lightness, hue slices from left to right"
	title_bbox = draw.textbbox((0, 0), title, font=font)
	subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font)
	draw.text(((width - (title_bbox[2] - title_bbox[0])) / 2, 6), title, fill=(26, 29, 35), font=font)
	draw.text(((width - (subtitle_bbox[2] - subtitle_bbox[0])) / 2, 22), subtitle, fill=(86, 94, 106), font=font)

	for index, (bucket_name, bucket_entries) in enumerate(grouped):
		band_left = DEFAULT_MARGIN_X + index * DEFAULT_BAND_WIDTH
		band_top = DEFAULT_MARGIN_Y + DEFAULT_HEADER_HEIGHT
		if bucket_name == "Neutral":
			title_text = "Neutral / Low Saturation"
		else:
			title_text = bucket_name
		draw_bucket(
			canvas=canvas,
			entries=sort_entries(bucket_entries),
			title=title_text,
			band_left=band_left,
			band_top=band_top,
			band_width=DEFAULT_BAND_WIDTH,
			band_height=DEFAULT_BAND_HEIGHT,
			point_size=point_size,
		)

	canvas.save(output_path)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Plot Minecraft full blocks by hue, saturation, and lightness")
	parser.add_argument("--version", default=DEFAULT_VERSION, help="Minecraft version directory to use")
	parser.add_argument("--output", default=DEFAULT_OUTPUT_IMAGE, help="Output PNG path")
	parser.add_argument("--csv", default=DEFAULT_OUTPUT_CSV, help="Output CSV path")
	parser.add_argument(
		"--neutral-threshold",
		type=float,
		default=DEFAULT_NEUTRAL_SATURATION_THRESHOLD,
		help="Saturation threshold below which blocks are treated as neutral",
	)
	parser.add_argument("--point-size", type=int, default=DEFAULT_POINT_SIZE, help="Diameter of each plotted block")
	parser.add_argument("--no-csv", action="store_true", help="Skip writing the CSV output")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	version_dir = resolve_version_dir(args.version)
	entries = load_blocks(version_dir, args.neutral_threshold)

	if not entries:
		raise RuntimeError(f"No blocks were loaded from {version_dir}")

	sorted_entries = sort_entries(entries)
	build_plot(sorted_entries, args.output, args.point_size)

	if not args.no_csv:
		save_csv(sorted_entries, args.csv)

	print(f"Loaded {len(sorted_entries)} full blocks from {version_dir}")
	print(f"Saved plot to {args.output}")
	if not args.no_csv:
		print(f"Saved CSV to {args.csv}")


if __name__ == "__main__":
	main()
