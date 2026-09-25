"""Режет длинный скриншот телефона на полосы и складывает их рядом: python tools/strips.py in.png out.png [h]."""
import sys
from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
h = int(sys.argv[3]) if len(sys.argv) > 3 else 1100
parts = [im.crop((0, y, im.width, min(im.height, y + h))) for y in range(0, im.height, h)]
G = Image.new("RGB", (len(parts) * (im.width + 10), h), "#444")
for i, p in enumerate(parts):
    G.paste(p, (i * (im.width + 10), 0))
G.save(sys.argv[2])
print(len(parts), "strips")
