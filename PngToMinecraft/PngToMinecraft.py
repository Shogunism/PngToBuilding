import json
import os
import re
import numpy as np
from PIL import Image
from pyncraft.minecraft import Minecraft
import csv

# ===== 設定 =====
SCRIPT_DIR = os.path.dirname(__file__)
LOCAL_VERSIONS_BASE = SCRIPT_DIR
LEGACY_HUEBLOCKS_BASE = os.path.join(os.path.dirname(__file__), "..", "hueblocks-master", "vueblocks")
DEFAULT_IMAGE_NAME = "image.png"
OUTPUT_IMAGE_PATH = "segmented_preview.png"
OUTPUT_CSV_PATH = "block_mapping.csv"
BACKGROUND_MAX_RGB = 30
BACKGROUND_MAX_STDDEV = 10.0
TRANSPARENT_ALPHA_THRESHOLD = 8

# ===== バージョン検出関数 =====

def detect_available_versions():
    """利用可能なMinecraftバージョンを検出"""
    versions = []
    if os.path.exists(LOCAL_VERSIONS_BASE):
        for item in os.listdir(LOCAL_VERSIONS_BASE):
            item_path = os.path.join(LOCAL_VERSIONS_BASE, item)
            if os.path.isdir(item_path):
                blockdata_path = os.path.join(item_path, "_blockdata.json")
                if os.path.isfile(blockdata_path):
                    versions.append(item)

    if not versions and os.path.exists(LEGACY_HUEBLOCKS_BASE):
        for item in os.listdir(LEGACY_HUEBLOCKS_BASE):
            item_path = os.path.join(LEGACY_HUEBLOCKS_BASE, item)
            if os.path.isdir(item_path):
                blockdata_path = os.path.join(item_path, "_blockdata.json")
                if os.path.isfile(blockdata_path):
                    versions.append(item)
    
    return sorted(versions, reverse=True)  # 新しいバージョンが先


def select_version():
    """ユーザーにバージョンを選択させる"""
    versions = detect_available_versions()
    
    if not versions:
        print(f"エラー: {LOCAL_VERSIONS_BASE} に blockdata.json が見つかりません")
        exit(1)
    
    if len(versions) == 1:
        print(f"使用バージョン: {versions[0]}\n")
        return versions[0]
    
    print("利用可能なバージョン:")
    for i, version in enumerate(versions, 1):
        print(f"  {i}. {version}")
    
    while True:
        try:
            choice = int(input("\nバージョンを選択してください (番号を入力): "))
            if 1 <= choice <= len(versions):
                selected = versions[choice - 1]
                print(f"選択バージョン: {selected}\n")
                return selected
            else:
                print(f"1～{len(versions)}の数値を入力してください")
        except ValueError:
            print("数値を入力してください")


def resolve_image_path(image_name):
    """PngToMinecraft直下を基準に画像パスを解決する"""
    if os.path.isabs(image_name):
        return image_name

    return os.path.join(SCRIPT_DIR, image_name)

# ===== ユーティリティ関数 =====

def normalize_minecraft_block_name(texture_name):
    """テクスチャ名からMinecraftで通るブロック名に寄せる"""
    block_name = os.path.splitext(texture_name)[0].upper()
    suffixes = [
        '_INVERTED_TOP', '_SIDE2', '_TOP', '_BOTTOM', '_SIDE', '_FRONT',
        '_BACK', '_END', '_MIDDLE', '_LEFT', '_RIGHT', '_LIT', '_UNLIT',
        '_NORTH', '_SOUTH', '_EAST', '_WEST', '_UP', '_DOWN'
    ]

    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if block_name.endswith(suffix):
                block_name = block_name[:-len(suffix)]
                changed = True
                break

    block_name = re.sub(r'_(\d+)$', '', block_name)
    return block_name


def load_blockdata(blockdata_path):
    """blockdata.jsonを読み込み、フルブロックのみを抽出"""
    if not os.path.exists(blockdata_path):
        print(f"エラー: {blockdata_path} が見つかりません")
        print(f"確認したパス: {os.path.abspath(blockdata_path)}")
        exit(1)

    with open(blockdata_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 最初の要素はタイムスタンプなのでスキップ
    blocks = [block for block in data[1:]]

    # 今回は除外する系統
    exclude_keywords = ['dead', 'shulker_box', 'coral_block','snow', 'tnt','ice','slab', 'stair', 'fence', 'wall', 'door', 'bed', 'carpet', 'sign', 'banner', 'head', 'skull']

    # フルブロックのみを抽出（sidesが4つ以上のもの）
    full_blocks = []
    for block in blocks:
        sides = block.get('sides', [])
        texture_name = block['texture'].lower()

        if any(keyword in texture_name for keyword in exclude_keywords):
            continue

        if len(sides) >= 4:
            texture_name = block['texture']
            block['minecraft_name'] = normalize_minecraft_block_name(texture_name)
            full_blocks.append(block)

    print(f"読み込まれたブロック: {len(blocks)}個")
    print(f"フルブロック: {len(full_blocks)}個\n")

    return full_blocks


def rgb_distance_squared(color1, color2):
    """RGB2乗距離を計算"""
    r_diff = color1[0] - color2[0]
    g_diff = color1[1] - color2[1]
    b_diff = color1[2] - color2[2]
    return r_diff**2 + g_diff**2 + b_diff**2


def find_closest_block(avg_color, blocks):
    """平均色に最も近いブロックを見つける"""
    min_distance = float('inf')
    closest_block = None
    
    for block in blocks:
        rgb = block['rgb']
        distance = rgb_distance_squared(avg_color, rgb)
        
        if distance < min_distance:
            min_distance = distance
            closest_block = block
    
    return closest_block


def is_pane_block_name(block_name):
    return 'PANE' in block_name.upper()


def resolve_pane_block_name(block_name, block_mapping, row_idx, col_idx):
    """隣接ブロックに応じた板ガラスの接続状態を付与する。"""
    connected = {
        'east': False,
        'west': False,
        'north': False,
        'south': False,
    }

    rows = len(block_mapping)
    cols = len(block_mapping[row_idx]) if rows else 0

    if col_idx + 1 < cols and block_mapping[row_idx][col_idx + 1] is not None:
        connected['east'] = True
    if col_idx - 1 >= 0 and block_mapping[row_idx][col_idx - 1] is not None:
        connected['west'] = True
    if row_idx - 1 >= 0 and col_idx < len(block_mapping[row_idx - 1]) and block_mapping[row_idx - 1][col_idx] is not None:
        connected['north'] = True
    if row_idx + 1 < rows and col_idx < len(block_mapping[row_idx + 1]) and block_mapping[row_idx + 1][col_idx] is not None:
        connected['south'] = True

    state = ",".join(f"{direction}={'true' if value else 'false'}" for direction, value in connected.items())
    return f"{block_name.lower()}[{state}]"


def is_background_segment(segment):
    """背景や透明部分かどうかを判定する。"""
    if segment.shape[-1] == 4:
        alpha = segment[:, :, 3]
        if float(np.mean(alpha)) <= TRANSPARENT_ALPHA_THRESHOLD:
            return True

    rgb = segment[:, :, :3].astype(np.float32)
    avg_rgb = np.mean(rgb, axis=(0, 1))
    if np.max(avg_rgb) <= BACKGROUND_MAX_RGB and float(np.std(rgb)) <= BACKGROUND_MAX_STDDEV:
        return True

    return False


def segment_image(image_path, segment_height, detail_multiplier):
    """
    画像を正方形セグメントに分割
    segment_height: 縦分割数
    """
    img = Image.open(image_path).convert('RGBA')
    img_array = np.array(img)

    height, width = img_array.shape[:2]

    # セグメントのサイズを計算（正方形化）
    effective_rows = max(1, segment_height * detail_multiplier)
    segment_size = max(1, min(width, height) // effective_rows)

    # 画像全体を元の縦横比のままリサイズする
    grid_rows = effective_rows
    target_height = grid_rows * segment_size
    scale = target_height / height
    target_width = max(1, int(round(width * scale)))
    grid_cols = max(1, int(np.ceil(target_width / segment_size)))

    img_resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    img_array = np.array(img_resized)
    
    print(f"元の画像: {width}x{height}px")
    print(f"セグメントサイズ: {segment_size}x{segment_size}px")
    print(f"セグメント数: {grid_rows}x{grid_cols} ({grid_rows * grid_cols}個)")
    
    segments = []
    segment_colors = []
    
    # 画像を上から順に分割
    for y in range(grid_rows):
        row = []
        row_colors = []
        
        for x in range(grid_cols):
            # セグメント領域を抽出
            x_start = x * segment_size
            y_start = y * segment_size
            x_end = min(x_start + segment_size, target_width)
            y_end = min(y_start + segment_size, target_height)

            if x_start >= target_width or y_start >= target_height:
                continue
            
            segment = img_array[y_start:y_end, x_start:x_end]

            if is_background_segment(segment):
                avg_color = None
            else:
                # 平均色を計算
                avg_color = np.mean(segment[:, :, :3], axis=(0, 1)).astype(int)
                avg_color = tuple(avg_color)
            
            row.append(segment)
            row_colors.append(avg_color)
        
        segments.append(row)
        segment_colors.append(row_colors)
    
    return segments, segment_colors, segment_size


def create_preview_image(segments, segment_size):
    """セグメント分割結果をプレビュー画像として保存"""
    height = len(segments)
    width = len(segments[0]) if height > 0 else 0
    
    preview = Image.new('RGB', (width * segment_size, height * segment_size))
    
    for y in range(height):
        for x in range(width):
            segment = segments[y][x]
            img_segment = Image.fromarray(segment.astype('uint8'))
            preview.paste(img_segment, (x * segment_size, y * segment_size))
    
    preview.save(OUTPUT_IMAGE_PATH)
    print(f"プレビュー画像を保存: {OUTPUT_IMAGE_PATH}")


def place_blocks_in_minecraft(segment_colors, block_mapping):
    """Minecraftにブロックを配置"""
    try:
        mc = Minecraft.create()
        x, y, z = mc.player.getTilePos()
        
        print(f"プレイヤー位置: ({x}, {y}, {z})")
        
        count = 0
        # 縦を下から上へ、横を左から右へ配置
        for row_idx, row in enumerate(segment_colors):
            for col_idx, color in enumerate(row):
                block = block_mapping[row_idx][col_idx]
                if block is None:
                    continue

                block_name = block['minecraft_name']
                if is_pane_block_name(block_name):
                    block_name = resolve_pane_block_name(block_name, block_mapping, row_idx, col_idx)
                
                # Y軸を上へ（ブロック追加）
                place_y = y - row_idx
                place_x = x + col_idx
                place_z = z
                
                try:
                    mc.setBlock(place_x, place_y, place_z, block_name)
                    count += 1
                except Exception as e:
                    print(f"警告: ブロック {block_name} の配置に失敗しました: {e}")
                    try:
                        mc.setBlock(place_x, place_y, place_z, "STONE")
                        count += 1
                    except Exception as fallback_error:
                        print(f"警告: 代替ブロックも配置できませんでした: {fallback_error}")
        
        print(f"合計 {count} ブロックを配置しました")
        
    except Exception as e:
        print(f"Minecraftへの配置に失敗しました: {e}")
        print("fruitjuieceが起動していることを確認してください")


def save_mapping_csv(segment_colors, block_mapping):
    """ブロックマッピングをCSVに保存"""
    with open(OUTPUT_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Y(高さ)', 'X(横)', 'RGB', 'テクスチャ名', 'Minecraftブロック名'])
        
        for row_idx, row in enumerate(segment_colors):
            for col_idx, color in enumerate(row):
                block = block_mapping[row_idx][col_idx]
                if block is None:
                    writer.writerow([
                        row_idx,
                        col_idx,
                        "air",
                        "(background)",
                        "(air)",
                    ])
                    continue

                writer.writerow([
                    row_idx, 
                    col_idx, 
                    str(color), 
                    block['texture'],
                    block['minecraft_name']
                ])
    
    print(f"ブロックマッピングをCSVに保存: {OUTPUT_CSV_PATH}")


# ===== メイン処理 =====

def main():
    print("=== PngToMinecraft ===\n")

    image_name = input(f"どの画像を使用しますか？ (PngToMinecraft直下, 省略で {DEFAULT_IMAGE_NAME}): ").strip()
    if not image_name:
        image_name = DEFAULT_IMAGE_NAME

    image_path = resolve_image_path(image_name)
    print(f"画像ファイル: {image_name}")
    print(f"確認したパス: {os.path.abspath(image_path)}\n")
    
    # バージョンを選択
    selected_version = select_version()
    blockdata_path = os.path.join(LOCAL_VERSIONS_BASE, selected_version, "_blockdata.json")
    if not os.path.isfile(blockdata_path):
        blockdata_path = os.path.join(LEGACY_HUEBLOCKS_BASE, selected_version, "_blockdata.json")
    
    print(f"blockdata.json パス: {blockdata_path}")
    print(f"確認したパス: {os.path.abspath(blockdata_path)}\n")
    
    # blockdata.jsonを読み込み
    blocks = load_blockdata(blockdata_path)
    
    # 画像を読み込み
    if not os.path.exists(image_path):
        print(f"エラー: {image_name} が見つかりません")
        return
    
    # ユーザーから高さを入力
    while True:
        try:
            segment_height = int(input(f"\n画像を何段に分割しますか? (1-100): "))
            if 1 <= segment_height <= 100:
                break
            else:
                print("1～100の数値を入力してください")
        except ValueError:
            print("数値を入力してください")

    # さらに細かく分割したい場合の倍率
    while True:
        try:
            detail_multiplier = int(input("細かさ倍率を入力してください (1=そのまま, 2=2倍細かい, 3=3倍細かい): "))
            if 1 <= detail_multiplier <= 10:
                break
            else:
                print("1～10の数値を入力してください")
        except ValueError:
            print("数値を入力してください")
    
    print(f"\n分割開始（高さ: {segment_height}, 細かさ倍率: {detail_multiplier}）...\n")
    
    # 画像をセグメント分割
    segments, segment_colors, segment_size = segment_image(image_path, segment_height, detail_multiplier)
    
    # プレビュー画像を作成
    create_preview_image(segments, segment_size)
    
    # ブロックマッピングを実行
    print("\nブロックマッピング中...\n")
    block_mapping = []
    
    for row_idx, row in enumerate(segment_colors):
        mapping_row = []
        for col_idx, color in enumerate(row):
            if color is None:
                mapping_row.append(None)
                continue

            closest_block = find_closest_block(color, blocks)
            mapping_row.append(closest_block)
        block_mapping.append(mapping_row)
    
    # CSVに保存
    save_mapping_csv(segment_colors, block_mapping)
    
    # Minecraftに配置するか確認
    place_in_game = input("\nMinecraftに配置しますか? (y/n): ").lower()
    if place_in_game == 'y':
        place_blocks_in_minecraft(segment_colors, block_mapping)
    else:
        print("Minecraftへの配置をスキップしました")
    
    print("\n完了!")


if __name__ == "__main__":
    main()
