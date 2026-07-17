# PngToMinecraft

このツールは PNG 画像を Minecraft ブロックに変換します。

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

`PngToMinecraft` 直下に `1.20.1/` や `1.21.10/` のようなバージョンフォルダを置いてください。

1. `image.png` をこのフォルダに配置
2. スクリプトを実行:
```bash
python PngToMinecraft.py
```
	- 起動後に「どの画像を使用しますか？」と聞かれるので、`PngToMinecraft` 直下の画像名を入力します
3. 高さ（縦の分割数）を入力
4. 必要なら細かさ倍率を入力（`2` にすると2倍細かく分割）
5. `segmented_preview.png` で結果を確認
6. `block_mapping.csv` で対応ブロックを確認
7. Minecraftに配置するか選択

## 出力ファイル

- `segmented_preview.png` - セグメント分割後の画像プレビュー
- `block_mapping.csv` - 各セグメントのブロック対応表

## 注意

- `image.png` は同じディレクトリに配置してください
- Minecraftに配置する場合は fruitjuice を起動してください
- フルブロックのみが配置対象です（ハーフブロック、フェンスなどは除外）
- `grass` / `dead` / `shulker_box` 系のブロックは一旦除外しています
