from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BlockPlacement:
    x: int
    y: int
    z: int
    block_name: str


class FruitJuiceWorldWriter:
    def __init__(self) -> None:
        self._minecraft = self._load_minecraft()
        self._mc = self._minecraft.create()

    def _load_minecraft(self):
        for module_name in ("fruitjuice.minecraft", "pyncraft.minecraft"):
            try:
                module = __import__(module_name, fromlist=["Minecraft"])
                return module.Minecraft
            except Exception:
                continue
        raise RuntimeError("FruitJuice / pyncraft Minecraft API is not available")

    def player_position(self) -> tuple[int, int, int]:
        player = getattr(self._mc, "player", None)
        if player is None:
            return (0, 0, 0)
        tile_pos = player.getTilePos()
        return int(tile_pos.x), int(tile_pos.y), int(tile_pos.z)

    def set_block(self, x: int, y: int, z: int, block_name: str) -> None:
        try:
            self._mc.setBlock(x, y, z, block_name)
        except Exception:
            self._mc.set_block(x, y, z, block_name)

    def place_many(self, placements: list[BlockPlacement]) -> None:
        for placement in placements:
            self.set_block(placement.x, placement.y, placement.z, placement.block_name)
