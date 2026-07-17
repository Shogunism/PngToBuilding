from PIL import Image
import numpy as np

# サンプル画像を生成（カラーグラデーション）
width = 500
height = 300

# グラデーション画像を作成
img_array = np.zeros((height, width, 3), dtype=np.uint8)

# 赤～青へのグラデーション
for x in range(width):
    for y in range(height):
        r = int(255 * x / width)
        g = int(255 * y / height)
        b = int(255 * (1 - x / width))
        img_array[y, x] = [r, g, b]

img = Image.fromarray(img_array)
img.save("image.png")
print("サンプル画像 image.png を生成しました")
