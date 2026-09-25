"""Сетка миниатюр вариантов задачи + сводка аудита: python tools/grid.py <job_id> [prefix]."""
import glob
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2] / "data"
job = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else job
J = ROOT / "jobs" / job
for v in "ABC":
    files = sorted(glob.glob(str(J / v / "slides" / "*.png")))
    if not files:
        continue
    lay = json.loads((J / v / "layouts.json").read_text(encoding="utf-8"))
    ims = [Image.open(f).convert("RGB") for f in files]
    w = 480
    h = int(w * ims[0].height / ims[0].width)
    cols = 4
    rows = (len(ims) + cols - 1) // cols
    G = Image.new("RGB", (cols * (w + 8) + 8, rows * (h + 26) + 8), "#222")
    d = ImageDraw.Draw(G)
    for i, im in enumerate(ims):
        x = 8 + (i % cols) * (w + 8)
        y = 8 + (i // cols) * (h + 26)
        G.paste(im.resize((w, h)), (x, y + 18))
        L = lay[i] if i < len(lay) else {}
        d.text((x, y + 2), f"{i + 1} {L.get('recipe', '')} {L.get('canvas_id', '')}", fill="white")
    out = ROOT / "showcase" / f"{prefix}_{v}.jpg"
    G.save(out, quality=85)
    a = json.loads((J / v / "audit.json").read_text(encoding="utf-8"))
    print(v, len(ims), out.name)
    for it in a["issues"]:
        if it["severity"] != "info":
            print("   ", it["severity"], it["slide"], it["check"], it["message"][:90])
