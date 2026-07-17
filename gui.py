from __future__ import annotations

import json
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image

try:
    from .engine import (
        BlockCandidate,
        BuildingKnowledgeEngine,
        FacadeCell,
        FacadePlan,
        PhysicalScale,
        DEFAULT_COLOR_RULES_PATH,
        BACKGROUND_ROLE,
        build_facade_plan_from_gemini,
        is_air_role,
        is_glass_block_name,
        load_color_rules,
        load_block_catalog,
        load_matter_database,
        to_glass_variant,
        to_pane_variant,
        create_demo_plan,
        set_color_rules,
    )
    from .asset_search import resolve_best_asset
    from .schematic_utils import paste_schematic
    from .world import BlockPlacement, FruitJuiceWorldWriter
except ImportError:
    from engine import (  # type: ignore[no-redef]
        BlockCandidate,
        BuildingKnowledgeEngine,
        FacadeCell,
        FacadePlan,
        PhysicalScale,
        DEFAULT_COLOR_RULES_PATH,
        BACKGROUND_ROLE,
        build_facade_plan_from_gemini,
        is_air_role,
        is_glass_block_name,
        load_color_rules,
        load_block_catalog,
        load_matter_database,
        to_glass_variant,
        to_pane_variant,
        create_demo_plan,
        set_color_rules,
    )
    from asset_search import resolve_best_asset
    from schematic_utils import paste_schematic
    from world import BlockPlacement, FruitJuiceWorldWriter  # type: ignore[no-redef]


class PngToBuildingApp(tk.Tk):
    SCHEMATIC_ASSETS_ROOT = Path(__file__).resolve().parent / "assets"

    ROLE_LABELS = {
        "Roofs": "屋根",
        "Walls": "壁",
        "Windows": "窓",
        "Doors": "扉",
        "Openings": "開口",
        "Decorations": "装飾",
        BACKGROUND_ROLE: "背景",
    }
    ROLE_LABEL_TO_INTERNAL = {
        "屋根": "Roofs",
        "壁": "Walls",
        "窓": "Windows",
        "扉": "Doors",
        "開口": "Openings",
        "装飾": "Decorations",
        "背景": BACKGROUND_ROLE,
    }
    ROLE_CHOICES = ["屋根", "壁", "窓", "扉", "開口", "装飾", "背景"]
    ROLE_COLORS = {
        "Roofs": "#b08968",
        "Walls": "#7f8c8d",
        "Windows": "#4dabf7",
        "Doors": "#e76f51",
        "Openings": "#a8dadc",
        "Decorations": "#9d4edd",
        BACKGROUND_ROLE: "#d9d9d9",
    }
    OPENING_COLOR = "#ffffff"
    AIR_COLOR = "#d9d9d9"

    def __init__(self) -> None:
        super().__init__()
        self.title("PngToBuilding - 建築属性エディタ")
        self.geometry("1020x720")
        self.minsize(900, 640)

        self.image_path = tk.StringVar()
        self.labelinfo_path = tk.StringVar()
        self.mask_path = tk.StringVar()
        self.color_rules_path = tk.StringVar(value=str(DEFAULT_COLOR_RULES_PATH))
        self.matter_path = tk.StringVar(value=str(Path(__file__).with_name("matterdatabase.json")))
        self.blockdata_path = tk.StringVar(value=str(Path(__file__).resolve().parent / "PngToMinecraft" / "1.20.1" / "_blockdata.json"))
        self.scale_width = tk.StringVar(value="64")
        self.scale_height = tk.StringVar(value="48")
        self.scale_depth = tk.StringVar(value="8")
        self.status_text = tk.StringVar(value="準備完了")
        self._busy = False
        self._plan: FacadePlan | None = None
        self._engine: BuildingKnowledgeEngine | None = None
        self._candidate_lookup: dict[str, BlockCandidate] = {}
        self._selected_item: str | None = None
        self._role_combo: ttk.Combobox | None = None
        self._block_combo: ttk.Combobox | None = None

        self.edit_x = tk.StringVar(value="-")
        self.edit_y = tk.StringVar(value="-")
        self.edit_role = tk.StringVar(value=self._role_display("Walls"))
        self.edit_material = tk.StringVar(value="")
        self.edit_block = tk.StringVar(value="(自動)")
        self.filter_role = tk.StringVar(value="全て")
        self.paint_role = tk.StringVar(value=self._role_display("Walls"))
        self.paint_size = tk.StringVar(value="1")
        self._cell_rects: dict[tuple[int, int], int] = {}
        self._paint_dragging = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        header = ttk.Label(root, text="PngToBuilding", font=("Yu Gothic UI", 20, "bold"))
        header.pack(anchor="w")

        subtitle = ttk.Label(root, text="元画像とマスクを見比べながら、役割・材料・質感・ブロックを編集するGUI")
        subtitle.pack(anchor="w", pady=(2, 12))

        form = ttk.LabelFrame(root, text="入力", padding=12)
        form.pack(fill="x")

        self._path_row(form, "正面画像", self.image_path, self._pick_image, 0)
        self._path_row(form, "ラベル情報 JSON", self.labelinfo_path, self._pick_labelinfo, 1)
        self._path_row(form, "マスク画像", self.mask_path, self._pick_mask, 2)
        self._path_row(form, "色ルール JSON", self.color_rules_path, self._pick_color_rules, 3)
        self._path_row(form, "素材データベース", self.matter_path, self._pick_matter, 4)
        self._path_row(form, "ブロックカタログ", self.blockdata_path, self._pick_blockdata, 5)
        self._path_row(form, "物理幅", self.scale_width, None, 6)
        self._path_row(form, "物理高さ", self.scale_height, None, 7)
        self._path_row(form, "物理奥行き", self.scale_depth, None, 8)

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=12)

        ttk.Button(actions, text="解析", command=self._analyze).pack(side="left")
        ttk.Button(actions, text="Minecraftへ構築", command=self._build_facade).pack(side="left", padx=8)
        ttk.Button(actions, text="要約を出力", command=self._export_summary).pack(side="left", padx=8)

        review = ttk.LabelFrame(root, text="レビュー", padding=10)
        review.pack(fill="both", expand=True)

        controls = ttk.Frame(review)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="表示役割").pack(side="left")
        role_filter = ttk.Combobox(controls, textvariable=self.filter_role, values=["全て", *self.ROLE_CHOICES], state="readonly", width=14)
        role_filter.pack(side="left", padx=6)
        role_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_summary())
        ttk.Button(controls, text="更新", command=self._refresh_summary).pack(side="left", padx=6)
        ttk.Button(controls, text="編集を適用", command=self._apply_selected_edit).pack(side="right")
        ttk.Button(controls, text="開口にする", command=self._set_opening).pack(side="right", padx=6)
        ttk.Button(controls, text="自動選択", command=self._auto_pick_block).pack(side="right", padx=6)

        paintbar = ttk.Frame(review)
        paintbar.pack(fill="x", pady=(0, 8))
        ttk.Label(paintbar, text="塗り役割").pack(side="left")
        paint_role = ttk.Combobox(paintbar, textvariable=self.paint_role, values=self.ROLE_CHOICES, state="readonly", width=14)
        paint_role.pack(side="left", padx=6)
        paint_role.bind("<<ComboboxSelected>>", lambda _event: self._set_status(f"ブラシを {self.paint_role.get()} に設定しました"))
        ttk.Label(paintbar, text="ブラシサイズ").pack(side="left", padx=(12, 0))
        paint_size = ttk.Combobox(paintbar, textvariable=self.paint_size, values=["1", "2", "3", "4"], state="readonly", width=5)
        paint_size.pack(side="left", padx=6)
        ttk.Button(paintbar, text="選択セルを格子に置換", command=self._replace_grid_from_selection).pack(side="right")
        ttk.Button(paintbar, text="選択役割を反映", command=self._paint_selection_role).pack(side="right", padx=6)
        ttk.Button(paintbar, text="選択役割をブラシへ", command=self._copy_paint_role_to_selection).pack(side="right", padx=6)

        table_frame = ttk.Frame(review)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        paint_frame = ttk.LabelFrame(review, text="役割マスク編集", padding=8)
        paint_frame.pack(fill="both", expand=True, pady=(8, 0))

        canvas_frame = ttk.Frame(paint_frame)
        canvas_frame.pack(fill="both", expand=True)

        self.mask_canvas = tk.Canvas(canvas_frame, bg="#1f1f1f", highlightthickness=0)
        x_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.mask_canvas.xview)
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.mask_canvas.yview)
        self.mask_canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.mask_canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.mask_canvas.bind("<Button-1>", self._canvas_paint_begin)
        self.mask_canvas.bind("<B1-Motion>", self._canvas_paint_move)
        self.mask_canvas.bind("<ButtonRelease-1>", self._canvas_paint_end)
        self.mask_canvas.bind("<Button-3>", self._canvas_pick_role)

        self.summary = ttk.Treeview(table_frame, columns=("x", "y", "role", "material", "block"), show="headings", height=12)
        summary_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.summary.yview)
        self.summary.configure(yscrollcommand=summary_scroll.set)
        self.summary.bind("<<TreeviewSelect>>", self._on_summary_select)
        for column, label in (("x", "X"), ("y", "Y"), ("role", "役割"), ("material", "材料"), ("block", "ブロック")):
            self.summary.heading(column, text=label)
            self.summary.column(column, width=120 if column != "block" else 260, anchor="w")
        self.summary.grid(row=0, column=0, sticky="nsew")
        summary_scroll.grid(row=0, column=1, sticky="ns")

        editor = ttk.LabelFrame(review, text="選択セル編集", padding=8)
        editor.pack(fill="x", pady=(10, 0))
        self._editor_row(editor, "X", self.edit_x, 0)
        self._editor_row(editor, "Y", self.edit_y, 1)
        self._editor_row(editor, "役割", self.edit_role, 2, values=self.ROLE_CHOICES, readonly=True)
        self._editor_row(editor, "材料", self.edit_material, 3)
        self._editor_row(editor, "ブロック", self.edit_block, 4, values=["(自動)"])

        log_frame = ttk.LabelFrame(root, text="ログ", padding=8)
        log_frame.pack(fill="both", expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        status = ttk.Label(root, textvariable=self.status_text, relief="sunken", anchor="w")
        status.pack(fill="x", pady=(10, 0))

    def _path_row(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, picker, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        if picker is not None:
            ttk.Button(parent, text="参照", command=picker).grid(row=row, column=2, pady=4)
        parent.columnconfigure(1, weight=1)

    def _editor_row(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, row: int, values: list[str] | None = None, readonly: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        if values is None:
            entry = ttk.Entry(parent, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        else:
            combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly" if readonly else "normal")
            combo.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            if label == "役割":
                self._role_combo = combo
                combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_candidates())
            if label == "ブロック":
                self._block_combo = combo
        parent.columnconfigure(1, weight=1)

    def _role_display(self, role: str) -> str:
        return self.ROLE_LABELS.get(role, role)

    def _role_internal(self, label: str) -> str:
        return self.ROLE_LABEL_TO_INTERNAL.get(label, label)

    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("画像ファイル", "*.png;*.jpg;*.jpeg;*.webp"), ("すべてのファイル", "*.*")))
        if path:
            self.image_path.set(path)

    def _pick_labelinfo(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("JSONファイル", "*.json"), ("すべてのファイル", "*.*")))
        if path:
            self.labelinfo_path.set(path)

    def _pick_mask(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("画像ファイル", "*.png;*.jpg;*.jpeg;*.webp"), ("すべてのファイル", "*.*")))
        if path:
            self.mask_path.set(path)

    def _pick_color_rules(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("JSONファイル", "*.json"), ("すべてのファイル", "*.*")))
        if path:
            self.color_rules_path.set(path)

    def _pick_matter(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("JSONファイル", "*.json"), ("すべてのファイル", "*.*")))
        if path:
            self.matter_path.set(path)

    def _pick_blockdata(self) -> None:
        path = filedialog.askopenfilename(filetypes=(("JSONファイル", "*.json"), ("すべてのファイル", "*.*")))
        if path:
            self.blockdata_path.set(path)

    def _clear_summary(self) -> None:
        for item in self.summary.get_children():
            self.summary.delete(item)

    def _clear_canvas(self) -> None:
        self._cell_rects.clear()
        self.mask_canvas.delete("all")

    def _role_fill(self, role: str) -> str:
        if is_air_role(role):
            return self.AIR_COLOR
        return self.OPENING_COLOR if role == "Openings" else self.ROLE_COLORS.get(role, "#888888")

    def _brush_radius(self) -> int:
        try:
            return max(0, int(self.paint_size.get().strip()) - 1)
        except ValueError:
            return 0

    def _canvas_layout(self) -> tuple[int, int]:
        if self._plan is None:
            return 0, 0
        return self._plan.width, self._plan.height

    def _draw_canvas(self) -> None:
        if self._plan is None:
            self._clear_canvas()
            return

        self._clear_canvas()
        cell_size = 18
        pad = 2
        width = self._plan.width * cell_size
        height = self._plan.height * cell_size
        self.mask_canvas.configure(scrollregion=(0, 0, width, height))

        for y, row in enumerate(self._plan.cells):
            for x, cell in enumerate(row):
                candidate = self._plan.assignments[y][x]
                fill = self._role_fill(cell.role)
                if candidate is None and is_air_role(cell.role):
                    fill = self.AIR_COLOR
                elif candidate is None and cell.role == "Openings":
                    fill = self.OPENING_COLOR
                elif candidate is None and not is_air_role(cell.role):
                    fill = "#2f2f2f"

                x0 = x * cell_size + pad
                y0 = y * cell_size + pad
                x1 = x0 + cell_size - pad * 2
                y1 = y0 + cell_size - pad * 2
                rect = self.mask_canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="#101010")
                self._cell_rects[(x, y)] = rect

        self._highlight_selection()

    def _highlight_selection(self) -> None:
        for rect in self._cell_rects.values():
            self.mask_canvas.itemconfigure(rect, width=1)
        cell = self._current_cell()
        if cell is None:
            return
        rect = self._cell_rects.get((cell.x, cell.y))
        if rect is not None:
            self.mask_canvas.itemconfigure(rect, width=3, outline="#ffffff")

    def _cell_at_event(self, event: tk.Event) -> FacadeCell | None:
        if self._plan is None:
            return None
        cell_size = 18
        x = int(self.mask_canvas.canvasx(event.x) // cell_size)
        y = int(self.mask_canvas.canvasy(event.y) // cell_size)
        if x < 0 or y < 0 or x >= self._plan.width or y >= self._plan.height:
            return None
        return self._plan.cells[y][x]

    def _paint_cell_role(self, cell: FacadeCell, role: str) -> None:
        if self._plan is None:
            return

        role = self._role_internal(role)
        if role not in self.ROLE_LABELS:
            role = cell.role
        radius = self._brush_radius()
        for offset_y in range(-radius, radius + 1):
            for offset_x in range(-radius, radius + 1):
                target_x = cell.x + offset_x
                target_y = cell.y + offset_y
                if target_x < 0 or target_y < 0 or target_x >= self._plan.width or target_y >= self._plan.height:
                    continue

                target = self._plan.cells[target_y][target_x]
                updated = FacadeCell(
                    x=target.x,
                    y=target.y,
                    role=role,
                    material=target.material,
                    rgb=target.rgb,
                    occupied=not is_air_role(role),
                )
                self._plan.cells[target_y][target_x] = updated

                if updated.occupied and self._engine is not None:
                    assignment = self._engine.choose_block(updated)
                else:
                    assignment = None
                self._plan.assignments[target_y][target_x] = assignment

                self._update_row_for_cell(updated, assignment)

        self._draw_canvas()

    def _update_row_for_cell(self, cell: FacadeCell, assignment: BlockCandidate | None) -> None:
        for item in self.summary.get_children():
            values = self.summary.item(item, "values")
            if not values:
                continue
            if int(values[0]) == cell.x and int(values[1]) == cell.y:
                block_name = assignment.minecraft_name if assignment is not None else "(空)"
                self.summary.item(item, values=(cell.x, cell.y, self._role_display(cell.role), cell.material, block_name))
                break

    def _canvas_paint_begin(self, event: tk.Event) -> None:
        self._paint_dragging = True
        self._canvas_paint_move(event)

    def _canvas_paint_move(self, event: tk.Event) -> None:
        if not self._paint_dragging:
            return

        cell = self._cell_at_event(event)
        if cell is None:
            return

        self.edit_x.set(str(cell.x))
        self.edit_y.set(str(cell.y))
        self.edit_role.set(self.paint_role.get())
        self._paint_cell_role(cell, self.paint_role.get())

    def _canvas_paint_end(self, _event: tk.Event) -> None:
        self._paint_dragging = False

    def _canvas_pick_role(self, event: tk.Event) -> None:
        cell = self._cell_at_event(event)
        if cell is None:
            return

        self.edit_x.set(str(cell.x))
        self.edit_y.set(str(cell.y))
        self.edit_role.set(self._role_display(cell.role))
        self.edit_material.set(cell.material)
        self.paint_role.set(self._role_display(cell.role))
        self._highlight_selection()

    def _paint_selection_role(self) -> None:
        cell = self._current_cell()
        if cell is None:
            messagebox.showwarning("セル未選択", "先にセルを選択してください。")
            return
        self._paint_cell_role(cell, self.paint_role.get())

    def _copy_paint_role_to_selection(self) -> None:
        cell = self._current_cell()
        if cell is None:
            messagebox.showwarning("セル未選択", "先にセルを選択してください。")
            return
        self.paint_role.set(self._role_display(cell.role))

    def _replace_grid_from_selection(self) -> None:
        if self._plan is None:
            messagebox.showinfo("編集対象なし", "先に解析を実行してください。")
            return

        cell = self._current_cell()
        if cell is None:
            messagebox.showwarning("セル未選択", "レビュー表でセルを選択してください。")
            return

        radius = self._brush_radius()
        source_assignment = self._selected_assignment()
        if source_assignment is None and self._engine is not None and not is_air_role(cell.role):
            source_assignment = self._engine.choose_block(cell)

        for offset_y in range(-radius, radius + 1):
            for offset_x in range(-radius, radius + 1):
                target_x = cell.x + offset_x
                target_y = cell.y + offset_y
                if target_x < 0 or target_y < 0 or target_x >= self._plan.width or target_y >= self._plan.height:
                    continue

                target = self._plan.cells[target_y][target_x]
                updated = FacadeCell(
                    x=target.x,
                    y=target.y,
                    role=cell.role,
                    material=cell.material,
                    rgb=cell.rgb,
                    occupied=not is_air_role(cell.role),
                )
                self._plan.cells[target_y][target_x] = updated
                self._plan.assignments[target_y][target_x] = source_assignment if updated.occupied else None
                self._update_row_for_cell(updated, self._plan.assignments[target_y][target_x])

        self._refresh_summary()
        self._draw_canvas()
        self._set_status(f"格子を置換しました: 中心=({cell.x}, {cell.y})")
        self._append_log(f"格子置換: role={self._role_display(cell.role)}, material={cell.material}, block={self.edit_block.get()}, radius={radius}")

    def _refresh_summary(self) -> None:
        if self._plan is None:
            return

        filter_role = self.filter_role.get()
        self._clear_summary()
        for y, row in enumerate(self._plan.assignments):
            for x, candidate in enumerate(row):
                cell = self._plan.cells[y][x]
                if filter_role != "全て" and cell.role != self._role_internal(filter_role):
                    continue
                block_name = candidate.minecraft_name if candidate is not None else "(空)"
                self.summary.insert("", "end", values=(cell.x, cell.y, self._role_display(cell.role), cell.material, block_name))

    def _current_cell(self) -> FacadeCell | None:
        if self._plan is None:
            return None
        try:
            x = int(self.edit_x.get())
            y = int(self.edit_y.get())
        except ValueError:
            return None

        if y < 0 or y >= self._plan.height or x < 0 or x >= self._plan.width:
            return None
        return self._plan.cells[y][x]

    def _selected_assignment(self) -> BlockCandidate | None:
        if self._plan is None:
            return None
        label = self.edit_block.get().strip()
        if not label or label in {"(auto)", "(open)", "(自動)", "(空)"}:
            return None
        return self._candidate_lookup.get(label)

    def _refresh_candidates(self) -> None:
        if self._engine is None:
            return

        cell = self._current_cell()
        if cell is None:
            return

        role = self._role_internal(self.edit_role.get().strip()) or cell.role
        candidates = self._engine.restrict_palette(role)
        if not candidates:
            self._candidate_lookup = {}
            self.edit_block.set("(自動)")
            self._set_status(f"役割 {self._role_display(role)} に候補がありません")
            return

        ranked = sorted(candidates, key=lambda block: self._engine.candidate_score(cell, block))
        self._candidate_lookup = {f"{block.texture} | {block.minecraft_name}": block for block in ranked}
        values = ["(自動)", "(空)", *self._candidate_lookup.keys()]
        if self._block_combo is not None:
            self._block_combo.configure(values=values)
        if self.edit_block.get() not in values:
            self.edit_block.set("(自動)")

    def _on_summary_select(self, _event) -> None:
        selection = self.summary.selection()
        if not selection:
            return

        item = self.summary.item(selection[0], "values")
        if not item:
            return

        self._selected_item = selection[0]
        self.edit_x.set(str(item[0]))
        self.edit_y.set(str(item[1]))
        self.edit_role.set(str(item[2]))
        self.edit_material.set(str(item[3]))
        self._refresh_candidates()

    def _apply_selected_edit(self) -> None:
        if self._plan is None:
            messagebox.showinfo("編集対象なし", "先に解析を実行してください。")
            return

        cell = self._current_cell()
        if cell is None:
            messagebox.showwarning("セル未選択", "レビュー表で行を選択してください。")
            return

        role = self._role_internal(self.edit_role.get().strip()) or cell.role
        material = self.edit_material.get().strip() or cell.material
        new_cell = FacadeCell(x=cell.x, y=cell.y, role=role, material=material, rgb=cell.rgb, occupied=not is_air_role(role))
        self._plan.cells[cell.y][cell.x] = new_cell
        assignment = self._selected_assignment()
        if new_cell.occupied and assignment is None and self._engine is not None:
            assignment = self._engine.choose_block(new_cell)
            if assignment is not None:
                self.edit_block.set(f"{assignment.texture} | {assignment.minecraft_name}")
        self._plan.assignments[cell.y][cell.x] = assignment if new_cell.occupied else None
        self._refresh_summary()
        self._set_status(f"セル ({cell.x}, {cell.y}) を編集しました")
        self._append_log(f"セル ({cell.x}, {cell.y}) を編集 -> role={self._role_display(role)}, material={material}, block={self.edit_block.get()}")

    def _replace_grid_from_selection(self) -> None:
        if self._plan is None:
            messagebox.showinfo("編集対象なし", "先に解析を実行してください。")
            return

        cell = self._current_cell()
        if cell is None:
            messagebox.showwarning("セル未選択", "レビュー表でセルを選択してください。")
            return

        radius = self._brush_radius()
        source_assignment = self._selected_assignment()
        if source_assignment is None and self._engine is not None and not is_air_role(cell.role):
            source_assignment = self._engine.choose_block(cell)

        for offset_y in range(-radius, radius + 1):
            for offset_x in range(-radius, radius + 1):
                target_x = cell.x + offset_x
                target_y = cell.y + offset_y
                if target_x < 0 or target_y < 0 or target_x >= self._plan.width or target_y >= self._plan.height:
                    continue

                target = self._plan.cells[target_y][target_x]
                updated = FacadeCell(
                    x=target.x,
                    y=target.y,
                    role=cell.role,
                    material=cell.material,
                    rgb=cell.rgb,
                    occupied=not is_air_role(cell.role),
                )
                self._plan.cells[target_y][target_x] = updated
                self._plan.assignments[target_y][target_x] = source_assignment if updated.occupied else None
                self._update_row_for_cell(updated, self._plan.assignments[target_y][target_x])

        self._refresh_summary()
        self._draw_canvas()
        self._set_status(f"格子を置換しました: 中心=({cell.x}, {cell.y})")
        self._append_log(f"格子置換: role={cell.role}, material={cell.material}, block={self.edit_block.get()}, radius={radius}")

    def _set_opening(self) -> None:
        self.edit_role.set(self._role_display("Openings"))
        self.edit_block.set("(空)")
        self._apply_selected_edit()

    def _auto_pick_block(self) -> None:
        if self._engine is None:
            return

        cell = self._current_cell()
        if cell is None:
            return

        role = self._role_internal(self.edit_role.get().strip()) or cell.role
        temp_cell = FacadeCell(x=cell.x, y=cell.y, role=role, material=self.edit_material.get().strip() or cell.material, rgb=cell.rgb, occupied=not is_air_role(role))
        candidate = self._engine.choose_block(temp_cell)
        if candidate is None:
            self.edit_block.set("(空)")
        else:
            label = f"{candidate.texture} | {candidate.minecraft_name}"
            self._candidate_lookup[label] = candidate
            if self._block_combo is not None:
                values = list(self._block_combo.cget("values"))
                if label not in values:
                    self._block_combo.configure(values=[*values, label])
            self.edit_block.set(label)

    def _load_session(self, image_path: str, scale: PhysicalScale) -> tuple[FacadePlan, BuildingKnowledgeEngine]:
        database = load_matter_database(self.matter_path.get().strip())
        block_catalog = load_block_catalog(self.blockdata_path.get().strip(), ("slab", "stair", "fence", "wall", "trapdoor", "banner", "bed", "carpet", "sign", "skull", "head"))
        engine = BuildingKnowledgeEngine(database, block_catalog)
        plan = create_demo_plan(image_path, self.matter_path.get().strip(), self.blockdata_path.get().strip(), scale, lambda message: self.after(0, lambda text=message: self._append_log(text)))
        return plan, engine

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _parse_scale(self) -> tuple[int, int, int] | None:
        try:
            width = int(self.scale_width.get().strip())
            height = int(self.scale_height.get().strip())
            depth = int(self.scale_depth.get().strip())
        except ValueError:
            messagebox.showwarning("スケール不正", "物理幅・物理高さ・物理奥行きは整数で指定してください。")
            return None

        if width <= 0 or height <= 0 or depth <= 0:
            messagebox.showwarning("スケール不正", "物理幅・物理高さ・物理奥行きは 1 以上で指定してください。")
            return None

        return width, height, depth

    def _set_status(self, text: str) -> None:
        self.after(0, lambda: self.status_text.set(text))

    def _set_busy(self, busy: bool) -> None:
        def apply_state() -> None:
            self._busy = busy
        self.after(0, apply_state)

    def _run_background(self, task_name: str, worker) -> None:
        if self._busy:
            messagebox.showinfo("処理中", f"{task_name} はすでに実行中です。")
            return

        self._set_busy(True)
        self._set_status(f"{task_name} を開始しました...")
        self.after(0, self._clear_log)
        self.after(0, lambda: self._append_log(f"{task_name} を開始"))

        def runner() -> None:
            try:
                worker()
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror(f"{task_name} 失敗", str(exc)))
                self._set_status(f"{task_name} に失敗しました")
            finally:
                self._set_busy(False)

        threading.Thread(target=runner, daemon=True).start()

    def _analyze(self) -> None:
        image_path = self.image_path.get().strip()
        if not image_path:
            messagebox.showwarning("入力不足", "まず正面画像を選択してください。")
            return

        scale = self._parse_scale()
        if scale is None:
            return

        def worker() -> None:
            physical_scale = PhysicalScale(width=scale[0], height=scale[1], depth=scale[2])
            progress = lambda message: self.after(0, lambda text=message: self._append_log(text))
            set_color_rules(load_color_rules(self.color_rules_path.get().strip()))
            database = load_matter_database(self.matter_path.get().strip())
            block_catalog = load_block_catalog(self.blockdata_path.get().strip(), ("slab", "stair", "fence", "wall", "trapdoor", "banner", "bed", "carpet", "sign", "skull", "head"))
            engine = BuildingKnowledgeEngine(database, block_catalog)
            labelinfo_path = self.labelinfo_path.get().strip()
            mask_path = self.mask_path.get().strip()

            if labelinfo_path and mask_path:
                facade_image = Image.open(image_path)
                plan = build_facade_plan_from_gemini(
                    facade_image,
                    block_catalog,
                    physical_scale,
                    database,
                    labelinfo_path,
                    mask_path,
                    lambda message: self.after(0, lambda text=message: self._append_log(text)),
                )
            else:
                plan = create_demo_plan(image_path, self.matter_path.get().strip(), self.blockdata_path.get().strip(), physical_scale, progress)

            rows: list[tuple[int, int, str, str, str]] = []
            for y, row in enumerate(plan.assignments):
                for x, candidate in enumerate(row):
                    cell = plan.cells[y][x]
                    block_name = candidate.minecraft_name if candidate is not None else "(空)"
                    rows.append((cell.x, cell.y, self._role_display(cell.role), cell.material, block_name))

            def apply_result() -> None:
                self._plan = plan
                self._engine = engine
                self._candidate_lookup = {}
                self._clear_summary()
                for row in rows:
                    self.summary.insert("", "end", values=row)
                self._refresh_summary()
                self._selected_item = None
                source_text = "Gemini取り込み" if plan.source_kind == "gemini" else "内部解析"
                self.status_text.set(f"解析完了: {plan.width} x {plan.height}, {len(rows)} セルを確認 ({source_text})")
                if plan.source_kind == "gemini":
                    self._append_log(
                        f"Geminiラベル取り込み: 完全一致={plan.exact_matches}, 近傍一致={plan.nearest_matches}, 未一致={plan.unmatched_pixels}"
                    )
                self._append_log(f"レビュー表に {len(rows)} セルを表示しました")
                self._draw_canvas()

            self.after(0, apply_result)

        self._run_background("解析", worker)

    def _export_summary(self) -> None:
        rows = [self.summary.item(item, "values") for item in self.summary.get_children()]
        if not rows:
            messagebox.showinfo("出力なし", "先に解析を実行してください。")
            return

        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=(("JSONファイル", "*.json"),))
        if not path:
            return

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)

        self.status_text.set(f"要約を出力しました: {path}")

    def _build_facade(self) -> None:
        if self._plan is None:
            messagebox.showinfo("未編集", "先に解析し、必要な編集を行ってから構築してください。")
            return

        def worker() -> None:
            self._set_status("Minecraft に接続中...")
            writer = FruitJuiceWorldWriter()
            origin_x, origin_y, origin_z = writer.player_position()
            placements: list[BlockPlacement] = []
            schematic_jobs: list[tuple[str, tuple[int, int, int], Path]] = []
            handled_classes: set[str] = set()

            for source_class in sorted({cell.source_class for row in self._plan.cells for cell in row if cell.source_class}):
                asset_path = resolve_best_asset(source_class, self.SCHEMATIC_ASSETS_ROOT)
                if asset_path is None:
                    continue

                class_cells = [
                    (x, y)
                    for y, row in enumerate(self._plan.cells)
                    for x, cell in enumerate(row)
                    if cell.source_class == source_class
                ]
                if not class_cells:
                    continue

                anchor_x, anchor_y = min(class_cells, key=lambda item: (item[1], item[0]))
                schematic_jobs.append(
                    (
                        source_class,
                        (
                            origin_x + (self._plan.width - 1 - anchor_x),
                            origin_y + (self._plan.height - 1 - anchor_y),
                            origin_z + 1,
                        ),
                        asset_path,
                    )
                )
                handled_classes.add(source_class)

            def resolve_block_name(candidate: BlockCandidate, world_x: int) -> str:
                block_name = candidate.minecraft_name
                if not is_glass_block_name(block_name):
                    return block_name
                if world_x % 2 == 0:
                    return to_pane_variant(block_name)
                return to_glass_variant(block_name)

            for source_class, anchor, asset_path in schematic_jobs:
                placed = paste_schematic(writer, asset_path, anchor)
                self.after(0, lambda placed=placed, source_class=source_class, asset_path=asset_path: self._append_log(f"{source_class} を schematic で配置: {asset_path.name} ({placed} blocks)"))

            for y, row in enumerate(self._plan.assignments):
                for x, candidate in enumerate(row):
                    if candidate is None:
                        continue
                    cell = self._plan.cells[y][x]
                    if cell.source_class in handled_classes:
                        continue
                    world_x = origin_x + (self._plan.width - 1 - x)
                    world_y = origin_y + (self._plan.height - 1 - y)
                    block_name = resolve_block_name(candidate, world_x)
                    if self._plan.scale.depth > 1 and self._plan.cells[y][x].role == "Walls":
                        for layer in range(self._plan.scale.depth):
                            placements.append(BlockPlacement(world_x, world_y, origin_z + layer, block_name))
                    else:
                        placements.append(BlockPlacement(world_x, world_y, origin_z + 1, block_name))

            self._set_status(f"{len(placements)} 個のブロックを配置中...")
            self.after(0, lambda: self._append_log(f"{len(placements)} 個のブロックをワールドへ配置します"))
            writer.place_many(placements)
            self.after(0, lambda: self.status_text.set("Minecraft への配置が完了しました"))

        self._run_background("構築", worker)


def run() -> None:
    app = PngToBuildingApp()
    app.mainloop()