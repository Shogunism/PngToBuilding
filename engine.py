from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal

import numpy as np
from PIL import Image, ImageColor, ImageOps


RoleName = Literal["Walls", "Roofs", "Windows", "Doors", "Openings", "Decorations", "background"]
TextureFamily = Literal["Glossy", "Matte", "Rough", "Fibrous", "Patterned"]

BACKGROUND_ROLE = "background"


DEFAULT_MATTER_PATH = Path(__file__).with_name("matterdatabase.json")
DEFAULT_BLOCKDATA_PATH = Path(__file__).resolve().parent / "PngToMinecraft" / "1.20.1" / "_blockdata.json"
DEFAULT_COLOR_RULES_PATH = Path(__file__).with_name("color_rules.json")


@dataclass(frozen=True)
class MatterDatabase:
    materials: list[str]
    colors: list[str]
    textures: list[str]
    roles: list[str]
    role_priority: tuple[str, ...] = ("Walls", "Roofs", "Windows", "Doors", "Openings", "Decorations", BACKGROUND_ROLE)
    block_role_rules: dict[str, list[str]] = field(default_factory=dict)
    forbidden_block_keywords: tuple[str, ...] = (
        "slab",
        "stair",
        "fence",
        "door",
        "trapdoor",
        "wall",
        "banner",
        "bed",
        "carpet",
        "sign",
        "skull",
        "head",
    )


@dataclass(frozen=True)
class ColorRules:
    color_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    white_min_brightness: float = 235.0
    white_max_saturation: float = 30.0
    black_max_brightness: float = 35.0
    gray_max_saturation: float = 20.0
    gray_min_brightness: float = 85.0
    brown_max_brightness: float = 120.0
    brown_hue_range: tuple[float, float] = (10.0, 50.0)


DEFAULT_COLOR_RULES = ColorRules(
    color_keywords={
        "white": ("white", "snow", "quartz", "bone", "ivory", "light"),
        "black": ("black", "coal", "obsidian", "soot", "ink", "charcoal"),
        "gray": ("gray", "grey", "silver", "light_gray", "light_grey", "stone", "iron"),
        "brown": ("brown", "wood", "oak", "spruce", "birch", "acacia", "jungle", "mangrove", "cherry", "mud", "terracotta"),
        "red": ("red", "crimson", "nether_wart", "ruby", "rose"),
        "orange": ("orange", "pumpkin", "copper", "terracotta", "sienna"),
        "yellow": ("yellow", "gold", "sand", "honey", "dandelion"),
        "green": ("green", "lime", "emerald", "leaf", "fern", "moss", "verdant"),
        "cyan": ("cyan", "light_blue", "aqua", "teal", "prismarine"),
        "blue": ("blue", "lapis", "azure", "sapphire", "navy"),
        "purple": ("purple", "magenta", "violet", "lavender", "amethyst"),
        "pink": ("pink", "rose", "peach", "fuchsia"),
    }
)


ACTIVE_COLOR_RULES = DEFAULT_COLOR_RULES


@dataclass(frozen=True)
class BlockCandidate:
    texture: str
    minecraft_name: str
    rgb: tuple[int, int, int]
    sides: tuple[str, ...]
    role_tags: tuple[str, ...] = ()
    material_family: str = ""
    texture_family: str = ""
    is_transparent: bool = False
    is_thin_shape: bool = False
    is_door_like: bool = False
    is_window_like: bool = False
    is_wall_like: bool = False
    is_roof_like: bool = False
    is_large_block: bool = True


@dataclass(frozen=True)
class LabelInfoEntry:
    rgb: tuple[int, int, int]
    role: RoleName
    material: str
    texture: str
    color: str = ""
    color_rgb: tuple[int, int, int] | None = None
    confidence: float = 1.0
    name: str = ""
    region_id: str = ""
    bbox: tuple[int, int, int, int] | None = None
    class_name: str = ""


@dataclass(frozen=True)
class PhysicalScale:
    width: int
    height: int
    depth: int = 1


@dataclass(frozen=True)
class FacadeCell:
    x: int
    y: int
    role: str
    material: str
    rgb: tuple[int, int, int]
    occupied: bool = True
    source_class: str = ""


@dataclass
class FacadePlan:
    width: int
    height: int
    scale: PhysicalScale
    cells: list[list[FacadeCell]]
    assignments: list[list[BlockCandidate | None]]
    source_kind: str = "internal"
    labelinfo_path: str = ""
    mask_path: str = ""
    exact_matches: int = 0
    nearest_matches: int = 0
    unmatched_pixels: int = 0


ROLE_HEIGHT_BANDS: dict[RoleName, tuple[float, float]] = {
    "Roofs": (0.00, 0.18),
    "Walls": (0.18, 0.72),
    "Windows": (0.28, 0.68),
    "Doors": (0.72, 1.00),
    "Openings": (0.25, 0.75),
    "Decorations": (0.00, 1.00),
}

ROLE_REQUIRED_KEYWORDS: dict[RoleName, tuple[str, ...]] = {
    "Roofs": ("roof", "tile", "terracotta", "brick", "concrete", "stone", "slate", "sandstone", "copper", "deepslate", "basalt", "quartz"),
    "Walls": ("stone", "brick", "concrete", "plaster", "mud", "rammed", "basalt", "granite", "diorite", "andesite", "sandstone", "slate", "marble", "cobble", "mortar", "terracotta", "quartz"),
    "Windows": ("glass", "stained_glass", "pane"),
    "Doors": ("door",),
    "Openings": (),
    "Decorations": ("brick", "terracotta", "tile", "pattern", "mosaic", "concrete", "wood", "bamboo", "stone", "quartz"),
    BACKGROUND_ROLE: (),
}

ROLE_FORBIDDEN_KEYWORDS: dict[RoleName, tuple[str, ...]] = {
    "Roofs": ("glass", "door", "trapdoor", "fence", "wall", "sign", "bed", "banner", "head", "skull"),
    "Walls": ("glass", "pane", "door", "trapdoor", "fence", "wall", "sign", "bed", "banner", "head", "skull"),
    "Windows": ("slab", "stair", "fence", "wall", "door", "trapdoor", "sign", "bed", "banner", "head", "skull"),
    "Doors": ("slab", "stair", "fence", "wall", "sign", "bed", "banner", "head", "skull"),
    "Openings": (),
    "Decorations": ("slab", "stair", "fence", "wall", "door", "trapdoor", "sign", "bed", "banner", "head", "skull"),
    BACKGROUND_ROLE: (),
}

TRANSPARENT_KEYWORDS = ("glass", "stained_glass", "pane", "ice", "water")
THIN_SHAPE_KEYWORDS = ("slab", "stair", "fence", "wall", "trapdoor", "sign", "bed", "banner", "head", "skull", "carpet")
WINDOW_KEYWORDS = ("glass", "stained_glass", "pane")
DOOR_KEYWORDS = ("door",)
ROOF_KEYWORDS = ("roof", "tile", "terracotta", "brick", "concrete", "stone", "slate", "sandstone", "copper", "deepslate", "basalt")
WALL_KEYWORDS = ("stone", "brick", "concrete", "plaster", "mud", "rammed", "basalt", "granite", "diorite", "andesite", "sandstone", "slate", "marble", "cobble", "mortar", "terracotta")
DECOR_KEYWORDS = ("pattern", "mosaic", "facing", "trim", "accent", "wood", "bamboo", "glass", "stone", "terracotta")
GLOBAL_FORBIDDEN_KEYWORDS = (
    "tnt",
    "command",
    "barrier",
    "jigsaw",
    "debug",
    "ore",
    "portal",
    "end_portal",
    "end_gateway",
    "structure_block",
    "structure_void",
)

ROLE_SYNONYMS: dict[str, RoleName] = {
    "window": "Windows",
    "windows": "Windows",
    "pane": "Windows",
    "door": "Doors",
    "doors": "Doors",
    "opening": "Openings",
    "openings": "Openings",
    "roof": "Roofs",
    "roofs": "Roofs",
    "wall": "Walls",
    "walls": "Walls",
    "decoration": "Decorations",
    "decorations": "Decorations",
    "background": BACKGROUND_ROLE,
}


def load_matter_database(path: os.PathLike[str] | str = DEFAULT_MATTER_PATH) -> MatterDatabase:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    return MatterDatabase(
        materials=list(raw.get("materials", [])),
        colors=list(raw.get("colors", [])),
        textures=list(raw.get("textures", [])),
        roles=list(raw.get("roles", [])),
        role_priority=tuple(raw.get("role_priority", ["Walls", "Roofs", "Windows", "Doors", "Openings", "Decorations"])),
        block_role_rules={str(key): list(value) for key, value in raw.get("block_role_rules", {}).items()},
        forbidden_block_keywords=tuple(raw.get(
            "forbidden_block_keywords",
            ["slab", "stair", "fence", "door", "trapdoor", "wall", "banner", "bed", "carpet", "sign", "skull", "head"],
        )),
    )


def _normalize_keyword_map(raw_map: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw_map, dict):
        return dict(DEFAULT_COLOR_RULES.color_keywords)

    normalized: dict[str, tuple[str, ...]] = {}
    for family, values in raw_map.items():
        if isinstance(values, (list, tuple)):
            normalized[str(family)] = tuple(str(value).strip().lower() for value in values if str(value).strip())
    return normalized or dict(DEFAULT_COLOR_RULES.color_keywords)


def load_color_rules(path: os.PathLike[str] | str = DEFAULT_COLOR_RULES_PATH) -> ColorRules:
    rule_path = Path(path)
    if not rule_path.exists():
        return DEFAULT_COLOR_RULES

    with open(rule_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    thresholds = raw.get("thresholds", {}) if isinstance(raw, dict) else {}
    return ColorRules(
        color_keywords=_normalize_keyword_map(raw.get("color_keywords") if isinstance(raw, dict) else None),
        white_min_brightness=float(thresholds.get("white_min_brightness", DEFAULT_COLOR_RULES.white_min_brightness)),
        white_max_saturation=float(thresholds.get("white_max_saturation", DEFAULT_COLOR_RULES.white_max_saturation)),
        black_max_brightness=float(thresholds.get("black_max_brightness", DEFAULT_COLOR_RULES.black_max_brightness)),
        gray_max_saturation=float(thresholds.get("gray_max_saturation", DEFAULT_COLOR_RULES.gray_max_saturation)),
        gray_min_brightness=float(thresholds.get("gray_min_brightness", DEFAULT_COLOR_RULES.gray_min_brightness)),
        brown_max_brightness=float(thresholds.get("brown_max_brightness", DEFAULT_COLOR_RULES.brown_max_brightness)),
        brown_hue_range=(
            float(thresholds.get("brown_hue_min", DEFAULT_COLOR_RULES.brown_hue_range[0])),
            float(thresholds.get("brown_hue_max", DEFAULT_COLOR_RULES.brown_hue_range[1])),
        ),
    )


def set_color_rules(rules: ColorRules | None) -> None:
    global ACTIVE_COLOR_RULES
    ACTIVE_COLOR_RULES = rules or DEFAULT_COLOR_RULES


def normalize_minecraft_block_name(texture_name: str) -> str:
    block_name = Path(texture_name).stem.upper()
    suffixes = (
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
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if block_name.endswith(suffix):
                block_name = block_name[: -len(suffix)]
                changed = True
                break
    return block_name


def _clamp_byte(value: object) -> int:
    return max(0, min(255, int(value)))


def parse_rgb_value(value: object) -> tuple[int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (_clamp_byte(value[0]), _clamp_byte(value[1]), _clamp_byte(value[2]))
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        if {"r", "g", "b"}.issubset(value.keys()):
            try:
                return (_clamp_byte(value["r"]), _clamp_byte(value["g"]), _clamp_byte(value["b"]))
            except (TypeError, ValueError):
                return None

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
            except ValueError:
                return None
        pieces = [piece.strip() for piece in text.split(",")]
        if len(pieces) == 3:
            try:
                return (int(pieces[0]), int(pieces[1]), int(pieces[2]))
            except ValueError:
                return None

    return None


def parse_color_hint(value: object) -> tuple[str, tuple[int, int, int] | None]:
    if value is None:
        return "", None

    rgb_value = parse_rgb_value(value)
    if rgb_value is not None:
        if isinstance(value, str):
            return value.strip(), rgb_value
        return "", rgb_value

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "", None
        try:
            return text, tuple(int(v) for v in ImageColor.getrgb(text))
        except Exception:
            return text, None

    return str(value).strip(), None


def parse_bbox_value(value: object) -> tuple[int, int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        keys = ("x1", "y1", "x2", "y2")
        if all(key in value for key in keys):
            try:
                return (int(value["x1"]), int(value["y1"]), int(value["x2"]), int(value["y2"]))
            except (TypeError, ValueError):
                return None

    return None


def normalize_role_name(value: object) -> RoleName:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ROLE_SYNONYMS:
            return ROLE_SYNONYMS[lowered]
        for role in ("Walls", "Roofs", "Windows", "Doors", "Openings", "Decorations", BACKGROUND_ROLE):
            if lowered == role.lower():
                return role  # type: ignore[return-value]
    return "Walls"


def is_air_role(role: object) -> bool:
    return isinstance(role, str) and role in {"Openings", BACKGROUND_ROLE}


def is_glass_block_name(block_name: str) -> bool:
    lowered = block_name.lower()
    return "glass" in lowered or lowered.endswith("_pane")


def to_glass_variant(block_name: str) -> str:
    upper = block_name.upper()
    if upper.endswith("_PANE"):
        return upper[:-5]
    if upper == "GLASS_PANE":
        return "GLASS"
    return upper.replace("STAINED_GLASS_PANE", "STAINED_GLASS").replace("GLASS_PANE", "GLASS")


def to_pane_variant(block_name: str) -> str:
    upper = block_name.upper()
    if upper.endswith("_PANE"):
        return upper
    if upper == "GLASS":
        return "GLASS_PANE"
    if upper == "STAINED_GLASS":
        return "STAINED_GLASS_PANE"
    if upper.endswith("STAINED_GLASS"):
        return upper.replace("STAINED_GLASS", "STAINED_GLASS_PANE")
    if upper.endswith("GLASS"):
        return upper.replace("GLASS", "GLASS_PANE")
    return upper


def _pick_string(entry: dict, keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = entry.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return default


def _pick_float(entry: dict, keys: tuple[str, ...], default: float = 1.0) -> float:
    for key in keys:
        value = entry.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def load_labelinfo(labelinfo_path: os.PathLike[str] | str) -> list[LabelInfoEntry]:
    with open(labelinfo_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if isinstance(raw, list):
        entries_raw = raw
    elif isinstance(raw, dict):
        entries_raw = []
        for candidate_key in ("labels", "items", "entries", "palette", "colors"):
            candidate = raw.get(candidate_key)
            if isinstance(candidate, list):
                entries_raw = candidate
                break
        if not entries_raw:
            entries_raw = [raw]
    else:
        entries_raw = []

    entries: list[LabelInfoEntry] = []
    for item in entries_raw:
        if not isinstance(item, dict):
            continue

        mask_rgb = parse_rgb_value(
            item.get("rgb")
            or item.get("mask_color")
            or item.get("mask_rgb")
            or item.get("segment_color")
            or item.get("value")
            or item.get("hex")
            or item.get("color_hex")
        )
        color_text, color_rgb = parse_color_hint(item.get("color") or item.get("appearance_color") or item.get("color_attr") or item.get("dominant_color"))
        if mask_rgb is None:
            mask_rgb = color_rgb
        if mask_rgb is None:
            continue

        entries.append(
            LabelInfoEntry(
                class_name=_pick_string(item, ("class", "class_name", "label_class", "semantic_class", "category"), default=""),
                rgb=mask_rgb,
                role=normalize_role_name(item.get("role") or item.get("semantic_role") or item.get("label") or item.get("category")),
                material=_pick_string(item, ("material", "material_name", "materialType", "subtype", "kind"), default=""),
                texture=_pick_string(item, ("texture", "texture_name", "textureFamily", "style", "surface"), default=""),
                color=color_text,
                color_rgb=color_rgb,
                confidence=_pick_float(item, ("confidence", "score", "probability", "weight"), default=1.0),
                name=_pick_string(item, ("name", "label_name", "id", "region", "title"), default=""),
                region_id=_pick_string(item, ("region_id", "segment_id", "group", "cluster"), default=""),
                bbox=parse_bbox_value(item.get("bbox") or item.get("box") or item.get("rect") or item.get("bounds")),
            )
        )

    return entries


def build_labelinfo_lookup(entries: list[LabelInfoEntry]) -> dict[tuple[int, int, int], LabelInfoEntry]:
    lookup: dict[tuple[int, int, int], LabelInfoEntry] = {}
    for entry in entries:
        existing = lookup.get(entry.rgb)
        if existing is None or entry.confidence >= existing.confidence:
            lookup[entry.rgb] = entry
    return lookup


def nearest_labelinfo_entry(
    rgb: tuple[int, int, int],
    lookup: dict[tuple[int, int, int], LabelInfoEntry],
    tolerance: int = 24,
) -> LabelInfoEntry | None:
    if rgb in lookup:
        return lookup[rgb]

    best_entry: LabelInfoEntry | None = None
    best_distance = tolerance * tolerance
    for candidate in lookup.values():
        distance = rgb_distance_squared(rgb, candidate.rgb)
        if distance <= best_distance:
            best_distance = distance
            best_entry = candidate
    return best_entry


def label_group_key(entry: LabelInfoEntry) -> object:
    if entry.color_rgb is not None:
        color_key: object = entry.color_rgb
    elif entry.color:
        color_key = entry.color.lower()
    elif entry.name:
        color_key = entry.name.lower()
    elif entry.region_id:
        color_key = entry.region_id.lower()
    else:
        color_key = entry.rgb
    return (entry.role, color_key)




def normalize_color_family_text(text: str, rules: ColorRules | None = None) -> str:
    lowered = text.strip().lower().replace(" ", "_")
    color_rules = rules or ACTIVE_COLOR_RULES
    for family, keywords in color_rules.color_keywords.items():
        if any(keyword in lowered for keyword in keywords):
            return family
    return ""


def rgb_to_color_family(rgb: tuple[int, int, int], rules: ColorRules | None = None) -> str:
    color_rules = rules or ACTIVE_COLOR_RULES
    red, green, blue = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    brightness = (red + green + blue) / 3.0
    max_channel = max(red, green, blue)
    min_channel = min(red, green, blue)
    saturation = max_channel - min_channel

    if brightness >= color_rules.white_min_brightness and saturation <= color_rules.white_max_saturation:
        return "white"
    if brightness <= color_rules.black_max_brightness:
        return "black"
    if saturation <= color_rules.gray_max_saturation:
        return "gray" if brightness >= color_rules.gray_min_brightness else "brown"

    if max_channel == red:
        hue = ((green - blue) / max(saturation, 1)) % 6
        hue_deg = 60 * hue
    elif max_channel == green:
        hue = ((blue - red) / max(saturation, 1)) + 2
        hue_deg = 60 * hue
    else:
        hue = ((red - green) / max(saturation, 1)) + 4
        hue_deg = 60 * hue

    if hue_deg < 0:
        hue_deg += 360

    if brightness < color_rules.brown_max_brightness and color_rules.brown_hue_range[0] <= hue_deg <= color_rules.brown_hue_range[1]:
        return "brown"
    if hue_deg < 15 or hue_deg >= 345:
        return "red"
    if hue_deg < 40:
        return "orange"
    if hue_deg < 70:
        return "yellow"
    if hue_deg < 155:
        return "green"
    if hue_deg < 205:
        return "cyan"
    if hue_deg < 255:
        return "blue"
    if hue_deg < 330:
        return "purple"
    return "pink"


def block_color_family(block: BlockCandidate, rules: ColorRules | None = None) -> str:
    family = normalize_color_family_text(block.texture, rules)
    if family:
        return family
    return rgb_to_color_family(block.rgb, rules)


def resolve_region_color_family(entry: LabelInfoEntry, representative_rgb: tuple[int, int, int], rules: ColorRules | None = None) -> str:
    color_rules = rules or ACTIVE_COLOR_RULES
    color_hint = entry.color_rgb if entry.color_rgb is not None else entry.color
    if isinstance(color_hint, tuple):
        return rgb_to_color_family(color_hint, color_rules)
    if isinstance(color_hint, str):
        family = normalize_color_family_text(color_hint, color_rules)
        if family:
            return family
    return rgb_to_color_family(representative_rgb, color_rules)


def choose_region_block(
    engine: BuildingKnowledgeEngine,
    role: str,
    representative_rgb: tuple[int, int, int],
    material: str,
    texture: str,
    color_family: str,
    rules: ColorRules | None = None,
) -> BlockCandidate | None:
    color_rules = rules or ACTIVE_COLOR_RULES
    candidates = engine.restrict_palette(role)
    if not candidates:
        return None

    role_name = role if role in ROLE_HEIGHT_BANDS else "Walls"
    target_material_family = categorize_material_family(material or texture)
    target_texture_family = categorize_material_family(texture or material)

    color_filtered = [block for block in candidates if block_color_family(block, color_rules) == color_family]
    if color_filtered:
        candidates = color_filtered

    material_filtered = [block for block in candidates if block.material_family == target_material_family or block.texture_family == target_material_family]
    if material_filtered:
        candidates = material_filtered

    texture_filtered = [block for block in candidates if block.texture_family == target_texture_family or block.material_family == target_texture_family]
    if texture_filtered:
        candidates = texture_filtered

    probe = FacadeCell(x=0, y=0, role=role_name, material=material or texture or color_family, rgb=representative_rgb, occupied=role_name != "Openings")
    return min(candidates, key=lambda block: engine.candidate_score(probe, block))


def choose_label_block(engine: BuildingKnowledgeEngine, entry: LabelInfoEntry) -> BlockCandidate | None:
    representative_rgb = entry.color_rgb or entry.rgb
    color_family = resolve_region_color_family(entry, representative_rgb, engine.color_rules)
    return choose_region_block(
        engine=engine,
        role=entry.role,
        representative_rgb=representative_rgb,
        material=entry.material,
        texture=entry.texture or entry.color,
        color_family=color_family,
        rules=engine.color_rules,
    )


def _clamp_byte(value: int) -> int:
    return max(0, min(255, int(value)))


def parse_rgb_value(value: object) -> tuple[int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (_clamp_byte(value[0]), _clamp_byte(value[1]), _clamp_byte(value[2]))
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        if {"r", "g", "b"}.issubset(value.keys()):
            try:
                return (_clamp_byte(value["r"]), _clamp_byte(value["g"]), _clamp_byte(value["b"]))
            except (TypeError, ValueError):
                return None

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
            except ValueError:
                return None

        pieces = [piece.strip() for piece in text.split(",")]
        if len(pieces) == 3:
            try:
                return (int(pieces[0]), int(pieces[1]), int(pieces[2]))
            except ValueError:
                return None

    return None


def parse_bbox_value(value: object) -> tuple[int, int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        keys = ("x1", "y1", "x2", "y2")
        if all(key in value for key in keys):
            try:
                return (int(value["x1"]), int(value["y1"]), int(value["x2"]), int(value["y2"]))
            except (TypeError, ValueError):
                return None

    return None


def normalize_role_name(value: object) -> RoleName:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ROLE_SYNONYMS:
            return ROLE_SYNONYMS[lowered]
        for role in ("Walls", "Roofs", "Windows", "Doors", "Openings", "Decorations"):
            if lowered == role.lower():
                return role  # type: ignore[return-value]
    return "Walls"


def _pick_string(entry: dict, keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = entry.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return default


def _pick_float(entry: dict, keys: tuple[str, ...], default: float = 1.0) -> float:
    for key in keys:
        value = entry.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def load_labelinfo(labelinfo_path: os.PathLike[str] | str) -> list[LabelInfoEntry]:
    with open(labelinfo_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if isinstance(raw, list):
        entries_raw = raw
    elif isinstance(raw, dict):
        for candidate_key in ("labels", "items", "entries", "palette", "colors"):
            candidate = raw.get(candidate_key)
            if isinstance(candidate, list):
                entries_raw = candidate
                break
        else:
            entries_raw = [raw]
    else:
        entries_raw = []

    entries: list[LabelInfoEntry] = []
    for item in entries_raw:
        if not isinstance(item, dict):
            continue

        rgb = parse_rgb_value(
            item.get("rgb")
            or item.get("color")
            or item.get("mask_color")
            or item.get("value")
            or item.get("hex")
            or item.get("color_hex")
        )
        if rgb is None:
            continue

        background = _pick_string(item, ("background", "background_role", "bg", "backdrop"), default="")
        if background.lower() == "air":
            role = BACKGROUND_ROLE
        else:
            role = normalize_role_name(item.get("role") or item.get("semantic_role") or item.get("label") or item.get("category"))
        material = _pick_string(item, ("material", "material_name", "materialType", "subtype", "kind"), default="")
        texture = _pick_string(item, ("texture", "texture_name", "textureFamily", "style", "surface"), default="")
        confidence = _pick_float(item, ("confidence", "score", "probability", "weight"), default=1.0)
        name = _pick_string(item, ("name", "label_name", "id", "region", "title"), default="")
        bbox = parse_bbox_value(item.get("bbox") or item.get("box") or item.get("rect") or item.get("bounds"))

        entries.append(
            LabelInfoEntry(
                class_name=_pick_string(item, ("class", "class_name", "label_class", "semantic_class", "category"), default=""),
                rgb=rgb,
                role=role,
                material=material,
                texture=texture,
                confidence=confidence,
                name=name,
                region_id=_pick_string(item, ("region_id", "segment_id", "group", "cluster"), default=""),
                bbox=bbox,
            )
        )

    return entries


def build_labelinfo_lookup(entries: list[LabelInfoEntry]) -> dict[tuple[int, int, int], LabelInfoEntry]:
    lookup: dict[tuple[int, int, int], LabelInfoEntry] = {}
    for entry in entries:
        existing = lookup.get(entry.rgb)
        if existing is None or entry.confidence >= existing.confidence:
            lookup[entry.rgb] = entry
    return lookup


def nearest_labelinfo_entry(
    rgb: tuple[int, int, int],
    lookup: dict[tuple[int, int, int], LabelInfoEntry],
    tolerance: int = 24,
) -> LabelInfoEntry | None:
    if rgb in lookup:
        return lookup[rgb]

    best_entry: LabelInfoEntry | None = None
    best_distance = tolerance * tolerance
    for candidate in lookup.values():
        distance = rgb_distance_squared(rgb, candidate.rgb)
        if distance <= best_distance:
            best_distance = distance
            best_entry = candidate
    return best_entry


def infer_block_traits(texture_name: str) -> dict[str, bool]:
    name = texture_name.lower()
    return {
        "is_transparent": any(keyword in name for keyword in TRANSPARENT_KEYWORDS),
        "is_thin_shape": any(keyword in name for keyword in THIN_SHAPE_KEYWORDS),
        "is_door_like": any(keyword in name for keyword in DOOR_KEYWORDS),
        "is_window_like": any(keyword in name for keyword in WINDOW_KEYWORDS),
        "is_wall_like": any(keyword in name for keyword in WALL_KEYWORDS),
        "is_roof_like": any(keyword in name for keyword in ROOF_KEYWORDS),
        "is_large_block": not any(keyword in name for keyword in THIN_SHAPE_KEYWORDS),
    }


def is_role_allowed(texture_name: str, role: RoleName) -> bool:
    lower = texture_name.lower()
    required = ROLE_REQUIRED_KEYWORDS[role]
    forbidden = ROLE_FORBIDDEN_KEYWORDS[role]

    if role in {"Openings", BACKGROUND_ROLE}:
        return False

    if any(keyword in lower for keyword in forbidden):
        return False

    if role == "Windows":
        return any(keyword in lower for keyword in required) and any(keyword in lower for keyword in TRANSPARENT_KEYWORDS)

    if role == "Doors":
        return any(keyword in lower for keyword in required)

    if role == "Walls":
        return any(keyword in lower for keyword in required) and not any(keyword in lower for keyword in WINDOW_KEYWORDS)

    if role == "Roofs":
        return any(keyword in lower for keyword in required)

    if role == "Decorations":
        return any(keyword in lower for keyword in required)

    return False


def preferred_texture_families(role: RoleName, material: str) -> tuple[str, ...]:
    material_family = categorize_material_family(material)
    if role == "Windows":
        return ("Glossy",)
    if role == "Doors":
        return ("Fibrous", "Matte")
    if role == "Walls":
        return ("Rough", "Matte")
    if role == "Roofs":
        return ("Patterned", "Rough", "Matte")
    if role == "Decorations":
        return ("Patterned", "Fibrous", "Glossy", material_family)
    return (material_family,)


def rgb_distance_squared(color1: tuple[int, int, int], color2: Iterable[int]) -> int:
    r2, g2, b2 = color2
    dr = int(color1[0]) - int(r2)
    dg = int(color1[1]) - int(g2)
    db = int(color1[2]) - int(b2)
    return dr * dr + dg * dg + db * db


def load_block_catalog(
    blockdata_path: os.PathLike[str] | str = DEFAULT_BLOCKDATA_PATH,
    forbidden_keywords: Iterable[str] = (),
) -> list[BlockCandidate]:
    with open(blockdata_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    entries = raw[1:] if raw and isinstance(raw, list) else []
    forbidden = tuple({*(keyword.lower() for keyword in GLOBAL_FORBIDDEN_KEYWORDS), *(keyword.lower() for keyword in forbidden_keywords)})
    catalog: list[BlockCandidate] = []

    for entry in entries:
        texture = str(entry.get("texture", ""))
        if not texture:
            continue

        texture_lower = texture.lower()
        if any(keyword in texture_lower for keyword in forbidden):
            continue

        sides = tuple(str(side) for side in entry.get("sides", []))
        special_shape_texture = any(keyword in texture_lower for keyword in WINDOW_KEYWORDS + DOOR_KEYWORDS)
        if len(sides) < 4 and not special_shape_texture:
            continue

        rgb = tuple(int(v) for v in entry.get("rgb", (0, 0, 0)))
        catalog.append(
            BlockCandidate(
                texture=texture,
                minecraft_name=normalize_minecraft_block_name(texture),
                rgb=rgb,  # type: ignore[arg-type]
                sides=sides,
                material_family=infer_material_family_from_texture(texture),
                texture_family=infer_texture_family_from_texture(texture),
                **infer_block_traits(texture),
            )
        )

    return catalog


def infer_material_family_from_texture(texture_name: str) -> str:
    name = texture_name.lower()
    if any(keyword in name for keyword in ("glass", "ice", "water", "sea_lantern", "glowstone")):
        return "Glossy"
    if any(keyword in name for keyword in ("wood", "planks", "log", "bamboo", "paper", "wool", "carpet", "hay", "thatch")):
        return "Fibrous"
    if any(keyword in name for keyword in ("tile", "terracotta", "brick", "pattern", "mosaic", "concrete")):
        return "Patterned"
    if any(keyword in name for keyword in ("stone", "basalt", "deepslate", "granite", "diorite", "andesite", "cobble", "sandstone", "slate", "marble")):
        return "Rough"
    return "Matte"


def infer_texture_family_from_texture(texture_name: str) -> TextureFamily:
    name = texture_name.lower()
    if any(keyword in name for keyword in ("glass", "ice", "sea_lantern", "glowstone", "sea")):
        return "Glossy"
    if any(keyword in name for keyword in ("wood", "log", "plank", "bamboo", "paper", "wool", "hay", "thatch")):
        return "Fibrous"
    if any(keyword in name for keyword in ("brick", "terracotta", "tile", "pattern", "mosaic", "concrete")):
        return "Patterned"
    if any(keyword in name for keyword in ("stone", "cobble", "basalt", "deepslate", "granite", "diorite", "andesite", "sandstone")):
        return "Rough"
    return "Matte"


def categorize_material_family(material: str) -> TextureFamily:
    name = material.lower()
    if any(keyword in name for keyword in ("glass", "acrylic", "polycarbonate", "stained glass")):
        return "Glossy"
    if any(keyword in name for keyword in ("wood", "bamboo", "paper", "fabric", "fiber", "thatch", "straw", "reed")):
        return "Fibrous"
    if any(keyword in name for keyword in ("roof tile", "tile", "terracotta", "pattern", "mortar", "terrazzo", "coral", "shell", "washi")):
        return "Patterned"
    if any(keyword in name for keyword in ("cobblestone", "stone", "basalt", "granite", "limestone", "sandstone", "slate", "marble", "brick", "earth", "mud", "rammed")):
        return "Rough"
    return "Matte"


class BuildingKnowledgeEngine:
    def __init__(self, database: MatterDatabase, block_catalog: list[BlockCandidate], color_rules: ColorRules | None = None):
        self.database = database
        self.block_catalog = block_catalog
        self.color_rules = color_rules or ACTIVE_COLOR_RULES

    def restrict_palette(self, role: str) -> list[BlockCandidate]:
        candidates: list[BlockCandidate] = []
        for block in self.block_catalog:
            if not is_role_allowed(block.texture, role):
                continue
            candidates.append(block)
        return candidates

    def exact_name_color_match(self, material: str, color_name: str, candidates: list[BlockCandidate]) -> BlockCandidate | None:
        material_lower = material.lower()
        color_lower = color_name.lower()
        for block in candidates:
            texture_lower = block.texture.lower()
            if material_lower in texture_lower and color_lower in texture_lower:
                return block
        return None

    def candidate_score(self, cell: FacadeCell, block: BlockCandidate) -> int:
        score = rgb_distance_squared(cell.rgb, block.rgb)
        preferred_families = preferred_texture_families(cell.role, cell.material)
        if block.texture_family not in preferred_families and block.material_family not in preferred_families:
            score += 25_000
        if cell.role == "Windows" and not block.is_transparent:
            score += 100_000
        if cell.role == "Doors" and not block.is_door_like:
            score += 100_000
        if cell.role == "Walls" and not block.is_large_block:
            score += 100_000
        if cell.role == "Roofs" and not block.is_large_block:
            score += 100_000
        if cell.role == "Openings":
            score += 200_000
        return score

    def choose_block(self, cell: FacadeCell) -> BlockCandidate | None:
        if is_air_role(cell.role):
            return None

        candidates = self.restrict_palette(cell.role)
        if candidates:
            exact = self.exact_name_color_match(cell.material, " ".join(self.database.colors), candidates)
            if exact is not None:
                return exact

            texture_family = categorize_material_family(cell.material)
            family_matches = [block for block in candidates if block.texture_family == texture_family or block.material_family == texture_family]
            if family_matches:
                return min(family_matches, key=lambda block: self.candidate_score(cell, block))

            return min(candidates, key=lambda block: self.candidate_score(cell, block))

        return None

    def build_facade_plan(self, role_mask: np.ndarray, material_mask: np.ndarray, rgb_image: np.ndarray, scale: PhysicalScale) -> FacadePlan:
        if role_mask.shape[:2] != material_mask.shape[:2] or role_mask.shape[:2] != rgb_image.shape[:2]:
            raise ValueError("role_mask, material_mask, and rgb_image must share the same height and width")

        height, width = role_mask.shape[:2]
        cells: list[list[FacadeCell]] = []
        assignments: list[list[BlockCandidate | None]] = []

        for y in range(height):
            cell_row: list[FacadeCell] = []
            assignment_row: list[BlockCandidate | None] = []
            for x in range(width):
                role = str(role_mask[y, x])
                material = str(material_mask[y, x])
                rgb = tuple(int(v) for v in rgb_image[y, x])
                cell = FacadeCell(x=x, y=y, role=role, material=material, rgb=rgb, occupied=not is_air_role(role), source_class="")
                cell_row.append(cell)
                assignment_row.append(self.choose_block(cell) if cell.occupied else None)
            cells.append(cell_row)
            assignments.append(assignment_row)

        return FacadePlan(width=width, height=height, scale=scale, cells=cells, assignments=assignments)


def build_facade_plan_from_gemini(
    image: Image.Image,
    block_catalog: list[BlockCandidate],
    scale: PhysicalScale,
    database: MatterDatabase | None,
    labelinfo_path: os.PathLike[str] | str,
    mask_path: os.PathLike[str] | str,
    progress_callback: Callable[[str], None] | None = None,
) -> FacadePlan:
    label_entries = load_labelinfo(labelinfo_path)
    label_lookup = build_labelinfo_lookup(label_entries)
    mask_image = Image.open(mask_path).convert("RGB")

    source_image = ImageOps.pad(
        image.convert("RGBA"),
        (scale.width, scale.height),
        method=Image.Resampling.NEAREST,
        color=(0, 0, 0, 0),
    )
    if mask_image.size != source_image.size:
        original_size = mask_image.size
        mask_image = mask_image.resize(source_image.size, Image.Resampling.NEAREST)
        if progress_callback is not None:
            progress_callback(
                f"Resized Gemini mask from {original_size[0]} x {original_size[1]} to {source_image.width} x {source_image.height} to match the orthographic frame"
            )

    width, height = source_image.size

    engine = BuildingKnowledgeEngine(database or load_matter_database(), block_catalog)
    source_rgb_array = np.array(source_image.convert("RGB"))
    fallback_material_mask = infer_simple_material_mask(source_rgb_array, scale)
    region_groups: dict[object, dict[str, object]] = {}
    cells: list[list[FacadeCell]] = []
    assignments: list[list[BlockCandidate | None]] = []
    exact_matches = 0
    nearest_matches = 0
    unmatched_pixels = 0

    total_pixels = width * height
    progress_step = max(1, total_pixels // 64)
    processed = 0

    for y in range(height):
        for x in range(width):
            processed += 1
            if progress_callback is not None and (processed == 1 or processed % progress_step == 0 or processed == total_pixels):
                progress_callback(f"Importing Gemini facade: {processed}/{total_pixels}")

            source_pixel = source_image.getpixel((x, y))
            source_rgb = (int(source_pixel[0]), int(source_pixel[1]), int(source_pixel[2]))
            alpha = int(source_pixel[3]) if len(source_pixel) >= 4 else 255
            if alpha == 0:
                group_key = ("openings", x, y)
                region_groups[group_key] = {
                    "role": "Openings",
                    "material": "air",
                    "texture": "void",
                    "color_family": "",
                    "pixels": [(x, y, (0, 0, 0))],
                    "candidate": None,
                    "unmatched": True,
                }
                unmatched_pixels += 1
                continue

            mask_pixel = mask_image.getpixel((x, y))
            mask_rgb = (int(mask_pixel[0]), int(mask_pixel[1]), int(mask_pixel[2]))
            label_entry = nearest_labelinfo_entry(mask_rgb, label_lookup)
            if label_entry is None:
                unmatched_pixels += 1
                role = "Walls"
                material = str(fallback_material_mask[y, x])
                texture = material
                color_family = rgb_to_color_family(source_rgb)
                group_key = (role, color_family, mask_rgb)
            else:
                role = label_entry.role
                if is_air_role(role):
                    group_key = (role, x, y)
                    region_groups[group_key] = {
                        "role": role,
                        "material": "air",
                        "texture": "void",
                        "color_family": "",
                        "pixels": [(x, y, source_rgb)],
                        "candidate": None,
                        "unmatched": False,
                    }
                    continue
                material = label_entry.material or str(fallback_material_mask[y, x])
                texture = label_entry.texture or label_entry.color or material
                if mask_rgb == label_entry.rgb:
                    exact_matches += 1
                else:
                    nearest_matches += 1
                color_family = resolve_region_color_family(label_entry, label_entry.color_rgb or source_rgb)
                group_key = label_group_key(label_entry)

            bucket = region_groups.get(group_key)
            if bucket is None:
                region_groups[group_key] = {
                    "role": role,
                    "material": material,
                    "texture": texture,
                    "color_family": color_family,
                    "pixels": [(x, y, source_rgb)],
                    "candidate": None,
                    "source_class": label_entry.class_name if label_entry is not None else "",
                    "unmatched": label_entry is None,
                }
            else:
                bucket_pixels = bucket.setdefault("pixels", [])
                bucket_pixels.append((x, y, source_rgb))
                if label_entry is not None:
                    bucket["material"] = bucket.get("material") or material
                    bucket["texture"] = bucket.get("texture") or texture
                    bucket["color_family"] = bucket.get("color_family") or color_family
                    bucket["source_class"] = bucket.get("source_class") or label_entry.class_name

    for bucket in region_groups.values():
        pixels = bucket.get("pixels", [])
        if not pixels:
            bucket["representative_rgb"] = (0, 0, 0)
        else:
            sum_r = sum(pixel[2][0] for pixel in pixels)
            sum_g = sum(pixel[2][1] for pixel in pixels)
            sum_b = sum(pixel[2][2] for pixel in pixels)
            count = len(pixels)
            bucket["representative_rgb"] = (
                int(round(sum_r / count)),
                int(round(sum_g / count)),
                int(round(sum_b / count)),
            )

        role = str(bucket.get("role", "Walls"))
        if not is_air_role(role):
            bucket["candidate"] = choose_region_block(
                engine=engine,
                role=role,
                representative_rgb=bucket["representative_rgb"],
                material=str(bucket.get("material", "")),
                texture=str(bucket.get("texture", "")),
                color_family=str(bucket.get("color_family", "")),
            )

    cells = [[None for _ in range(width)] for _ in range(height)]  # type: ignore[list-item]
    assignments = [[None for _ in range(width)] for _ in range(height)]
    for bucket in region_groups.values():
        role = str(bucket.get("role", "Walls"))
        material = str(bucket.get("material", ""))
        candidate = bucket.get("candidate") if not is_air_role(role) else None
        source_class = str(bucket.get("source_class", ""))
        for x, y, source_rgb in bucket.get("pixels", []):
            cell = FacadeCell(
                x=x,
                y=y,
                role=role,
                material=material,
                rgb=source_rgb,
                occupied=not is_air_role(role),
                source_class=source_class,
            )
            cells[y][x] = cell
            assignments[y][x] = candidate if not is_air_role(role) else None

    for y in range(height):
        for x in range(width):
            if cells[y][x] is None:
                cells[y][x] = FacadeCell(x=x, y=y, role="Walls", material="Concrete", rgb=(255, 255, 255), occupied=True)

    return FacadePlan(
        width=width,
        height=height,
        scale=scale,
        cells=cells,
        assignments=assignments,
        source_kind="gemini",
        labelinfo_path=str(labelinfo_path),
        mask_path=str(mask_path),
        exact_matches=exact_matches,
        nearest_matches=nearest_matches,
        unmatched_pixels=unmatched_pixels,
    )


def load_orthographic_image(image_path: os.PathLike[str] | str, scale: PhysicalScale) -> np.ndarray:
    image = Image.open(image_path).convert("RGB")
    normalized = ImageOps.pad(image, (scale.width, scale.height), method=Image.Resampling.NEAREST, color=(255, 255, 255))
    return np.array(normalized)


def infer_simple_role_mask(rgb_image: np.ndarray, scale: PhysicalScale) -> np.ndarray:
    brightness = rgb_image.mean(axis=2)
    mask = np.full(brightness.shape, "Walls", dtype=object)

    height, width = brightness.shape[:2]
    roof_end = max(1, int(round(height * ROLE_HEIGHT_BANDS["Roofs"][1])))
    window_start = max(roof_end, int(round(height * ROLE_HEIGHT_BANDS["Windows"][0])))
    window_end = max(window_start + 1, int(round(height * ROLE_HEIGHT_BANDS["Windows"][1])))
    door_start = max(window_end, int(round(height * ROLE_HEIGHT_BANDS["Doors"][0])))
    center_left = int(round(width * 0.35))
    center_right = int(round(width * 0.65))

    for y in range(height):
        row_brightness = float(brightness[y].mean())
        if y < roof_end:
            mask[y, :] = "Roofs"
            continue
        if window_start <= y < window_end and row_brightness >= 120:
            mask[y, :] = "Windows"
            continue
        if y >= door_start:
            mask[y, :] = "Doors"
            mask[y, :center_left] = "Walls"
            mask[y, center_right:] = "Walls"
            if row_brightness > 220:
                mask[y, :] = "Openings"
            continue
        if row_brightness > 235:
            mask[y, :] = "Openings"
        elif 0.45 <= (y / max(height - 1, 1)) <= 0.62 and row_brightness >= 150:
            mask[y, :] = "Decorations"
    return mask


def infer_simple_material_mask(rgb_image: np.ndarray, scale: PhysicalScale) -> np.ndarray:
    brightness = rgb_image.mean(axis=2)
    mask = np.full(brightness.shape, "Concrete", dtype=object)
    mask[brightness > 220] = "Glass"
    mask[brightness < 75] = "Basalt"
    mask[(brightness >= 75) & (brightness < 160)] = "Brick"
    mask[brightness >= 160] = "Plaster"
    return mask


def space_carve_views(front: np.ndarray, back: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    if front.shape != back.shape or front.shape != left.shape or front.shape != right.shape:
        raise ValueError("All view masks must have the same shape")
    return np.logical_and.reduce((front.astype(bool), back.astype(bool), left.astype(bool), right.astype(bool)))


def facade_to_projection_mask(plan: FacadePlan) -> np.ndarray:
    mask = np.zeros((plan.height, plan.width), dtype=bool)
    for y, row in enumerate(plan.assignments):
        for x, candidate in enumerate(row):
            mask[y, x] = candidate is not None
    return mask


def create_demo_plan(
    image_path: os.PathLike[str] | str,
    matter_path: os.PathLike[str] | str = DEFAULT_MATTER_PATH,
    blockdata_path: os.PathLike[str] | str = DEFAULT_BLOCKDATA_PATH,
    scale: PhysicalScale | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> FacadePlan:
    scale = scale or PhysicalScale(width=64, height=48, depth=1)
    if progress_callback is not None:
        progress_callback(f"Loading matter database: {matter_path}")
    database = load_matter_database(matter_path)
    if progress_callback is not None:
        progress_callback(f"Loading block catalog: {blockdata_path}")
    block_catalog = load_block_catalog(blockdata_path, ("slab", "stair", "fence", "wall", "trapdoor", "banner", "bed", "carpet", "sign", "skull", "head"))
    engine = BuildingKnowledgeEngine(database, block_catalog)
    if progress_callback is not None:
        role_counts = {role: sum(1 for block in block_catalog if is_role_allowed(block.texture, role)) for role in ROLE_HEIGHT_BANDS}
        progress_callback(
            "Role candidates: "
            + ", ".join(f"{role}={count}" for role, count in role_counts.items())
        )
    if progress_callback is not None:
        progress_callback(f"Normalizing image to frame {scale.width} x {scale.height}")
    rgb_image = load_orthographic_image(image_path, scale)
    if progress_callback is not None:
        progress_callback("Inferring role bands and materials")
    role_mask = infer_simple_role_mask(rgb_image, scale)
    material_mask = infer_simple_material_mask(rgb_image, scale)
    if progress_callback is not None:
        progress_callback("Building facade plan with strict role filtering")
    return engine.build_facade_plan(role_mask, material_mask, rgb_image, scale)