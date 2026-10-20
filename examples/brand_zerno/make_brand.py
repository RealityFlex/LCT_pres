"""Пример брендбука вымышленной сети кофеен «Зерно» в четырёх форматах — для проверки приёма брендбуков.

  logos/            — логотип: SVG, PNG для светлого фона, PNG для тёмного фона, знак отдельно
  slides/           — три примера слайдов в фирменном стиле (PNG 1920×1080)
  tokens.json       — дизайн-токены W3C: цвета, шрифты, отступы, скругления, правила логотипа
  guideline.pdf     — PDF-гайдлайн на 5 страниц: логотип, палитра (HEX/RGB/CMYK), шрифты, правила, слайды
  brand_zerno.zip   — архив logos/ + slides/ («папка с логотипами и примерами слайдов»)
  zerno.fig         — не создаётся: формат .fig пишет только Figma (для проверки — любые файлы Community)

Запуск: python examples/brand_zerno/make_brand.py  (PDF печатает Microsoft Edge в headless-режиме)
"""
import base64
import json
import math
import shutil
import subprocess
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
FONTS = OUT.parents[1] / "data" / "fonts"
PAL = {
    "primary": ("C8582A", "Обжарка", "основной: логотип, акценты, главная серия диаграмм"),
    "secondary": ("2F7A55", "Лист", "второй: сравнение, вторая серия"),
    "accent": ("E8A33D", "Мёд", "акцент: одна точка внимания на слайде"),
    "dark": ("2B1A14", "Эспрессо", "тёмный фон обложки и разделов"),
    "text": ("1F1A17", "Текст", "основной текст"),
    "muted": ("7B6F66", "Пенка", "подписи, оси, второстепенный текст"),
    "background": ("FFFFFF", "Белый", "фон контентных слайдов"),
    "surface": ("F6EFE7", "Сливки", "подложки карточек"),
}
HEADING, BODY = "Manrope", "Golos Text"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    files = {"heading": "Manrope-Bold.ttf", "body": "Golos_Text-Regular.ttf", "body_bold": "Golos_Text-Bold.ttf"}
    return ImageFont.truetype(str(FONTS / files[name]), size)


def rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def cmyk(h: str) -> str:
    r, g, b = (x / 255 for x in rgb(h))
    k = 1 - max(r, g, b)
    if k >= 1:
        return "0 0 0 100"
    c, m, y = ((1 - x - k) / (1 - k) for x in (r, g, b))
    return " ".join(str(round(v * 100)) for v in (c, m, y, k))


# ------------------------------------------------------------------ логотип
def bean(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color: tuple, cut: tuple) -> None:
    """Зерно: эллипс под углом 30° и S-образный разрез."""
    pts = []
    for i in range(120):
        t = 2 * math.pi * i / 120
        x, y = 0.62 * s * math.cos(t), 0.86 * s * math.sin(t)
        a = math.radians(30)
        pts.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    draw.polygon(pts, fill=color)
    line = []
    for i in range(41):
        u = -0.78 + 1.56 * i / 40
        x, y = 0.16 * s * math.sin(u * math.pi * 1.1), u * s
        a = math.radians(30)
        line.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    draw.line(line, fill=cut, width=max(2, int(s * 0.11)), joint="curve")


def logo(path: Path, word_color: str, mark_only: bool = False) -> None:
    W, H = (400, 400) if mark_only else (1200, 360)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = 150 if mark_only else 135
    cx = W / 2 if mark_only else 180
    bean(d, cx, H / 2, s, rgb(PAL["primary"][0]) + (255,), (0, 0, 0, 0))
    if not mark_only:
        f = font("heading", 190)
        d.text((330, H / 2), "ЗЕРНО", font=f, fill=rgb(word_color) + (255,), anchor="lm")
    # «прорезь» в зерне — прозрачная
    im.save(path)


def logo_svg(path: Path) -> None:
    p = PAL["primary"][0]
    path.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 360" width="1200" height="360">
  <g transform="translate(180 180) rotate(30)">
    <ellipse rx="84" ry="116" fill="#{p}"/>
    <path d="M -10 -105 C 30 -50, -30 50, 10 105" fill="none" stroke="#FFFFFF" stroke-width="15" stroke-linecap="round"/>
  </g>
  <text x="330" y="245" font-family="{HEADING}, Arial, sans-serif" font-weight="700" font-size="190" fill="#{PAL['text'][0]}">ЗЕРНО</text>
</svg>
''', encoding="utf-8")


# ------------------------------------------------------------------ примеры слайдов
def slide(path: Path, kind: str) -> None:
    W, H = 1920, 1080
    dark = kind in ("cover", "closing")
    im = Image.new("RGB", (W, H), rgb(PAL["dark"][0] if dark else PAL["background"][0]))
    d = ImageDraw.Draw(im)
    m = 120
    lg = Image.open(OUT / "logos" / ("zerno_logo_white.png" if dark else "zerno_logo.png"))
    lg.thumbnail((300, 90))
    im.paste(lg, (W - m - lg.width, 70), lg)
    fg = (255, 255, 255) if dark else rgb(PAL["text"][0])
    if kind == "cover":
        d.text((m, 380), "Итоги 2025 года", font=font("heading", 110), fill=fg)
        d.rectangle((m, 540, m + 120, 552), fill=rgb(PAL["accent"][0]))
        d.text((m, 600), "Сеть кофеен «Зерно» · совет директоров", font=font("body", 46), fill=rgb("D9CFC7"))
        bean(d, 1500, 640, 260, rgb(PAL["primary"][0]), rgb(PAL["dark"][0]))
    elif kind == "chart":
        d.text((m, 110), "ДАННЫЕ · ПРОДАЖИ", font=font("body_bold", 30), fill=rgb(PAL["primary"][0]))
        d.text((m, 160), "Выручка растёт на 19% в год", font=font("heading", 76), fill=fg)
        vals = [42, 48, 55, 61, 66, 74, 81, 88, 98]
        x0, y0, bw, gap = m, 900, 120, 46
        for i, v in enumerate(vals):
            h = v * 5.2
            col = PAL["primary"][0] if i == len(vals) - 1 else "E9C9B9"
            d.rounded_rectangle((x0 + i * (bw + gap), y0 - h, x0 + i * (bw + gap) + bw, y0), radius=10, fill=rgb(col))
        d.line((m, y0, m + 9 * (bw + gap), y0), fill=rgb(PAL["muted"][0]), width=3)
        d.rounded_rectangle((1600 - 20, 330, W - m, 620), radius=24, fill=rgb(PAL["surface"][0]))
        d.text((1600, 360), "+19%", font=font("heading", 96), fill=rgb(PAL["primary"][0]))
        d.text((1600, 500), "год к году", font=font("body", 40), fill=rgb(PAL["muted"][0]))
        d.text((m, 960), "Источник: учётная система «Зерно», 2023–2025", font=font("body", 28), fill=rgb(PAL["muted"][0]))
    else:
        d.text((m, 380), "Спасибо!", font=font("heading", 120), fill=fg)
        d.rectangle((m, 550, m + 120, 562), fill=rgb(PAL["accent"][0]))
        d.text((m, 610), "Вопросы и обсуждение", font=font("body", 48), fill=rgb("D9CFC7"))
    im.save(path)


# ------------------------------------------------------------------ токены
def tokens() -> dict:
    col = {k: {"$type": "color", "$value": "#" + v[0], "$description": f"{v[1]} — {v[2]}"} for k, v in PAL.items()}
    return {
        "$description": "Дизайн-токены сети кофеен «Зерно» (W3C Design Tokens)",
        "color": {"brand": {"primary": col["primary"], "secondary": col["secondary"], "accent": col["accent"]},
                  "background": col["background"], "surface": col["surface"], "dark": col["dark"],
                  "text": col["text"], "muted": col["muted"]},
        "font": {"heading": {"$type": "fontFamily", "$value": [HEADING, "Arial", "sans-serif"]},
                 "body": {"$type": "fontFamily", "$value": [BODY, "Arial", "sans-serif"]}},
        "typography": {
            "title": {"$type": "typography", "$value": {"fontFamily": "{font.heading}", "fontSize": "40px", "fontWeight": 700}},
            "body": {"$type": "typography", "$value": {"fontFamily": "{font.body}", "fontSize": "16px", "fontWeight": 400}}},
        "spacing": {"margin": {"$type": "dimension", "$value": "72px", "$description": "поля слайда 960×540"},
                    "gap": {"$type": "dimension", "$value": "24px", "$description": "зазор между блоками"}},
        "radius": {"card": {"$type": "dimension", "$value": "12px"}},
        "logo": {"minHeight": {"$type": "dimension", "$value": "24px", "$description": "минимальная высота логотипа на слайде 960×540"},
                 "clearSpace": {"$type": "number", "$value": 0.5, "$description": "охранное поле — половина высоты логотипа"}},
    }


# ------------------------------------------------------------------ PDF-гайдлайн
def data_uri(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def guideline_html() -> str:
    sw = "".join(f'''<div class="sw"><div class="chip" style="background:#{v[0]}"></div><b>{v[1]}</b>
      <div>HEX #{v[0]}</div><div>RGB {" ".join(map(str, rgb(v[0])))}</div><div>CMYK {cmyk(v[0])}</div><i>{v[2]}</i></div>'''
                 for v in PAL.values())
    page = 'style="page-break-after:always"'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Зерно — брендбук</title><style>
@page {{ size: A4 landscape; margin: 0 }}
body {{ margin: 0; font-family: "{BODY}", Arial, sans-serif; color: #{PAL["text"][0]} }}
section {{ width: 297mm; height: 210mm; box-sizing: border-box; padding: 18mm 20mm; position: relative }}
h1, h2 {{ font-family: "{HEADING}", Arial, sans-serif; margin: 0 0 8mm }} h1 {{ font-size: 40pt }} h2 {{ font-size: 26pt }}
.dark {{ background: #{PAL["dark"][0]}; color: #fff }}
.sw {{ display: inline-block; width: 60mm; margin: 0 6mm 8mm 0; font-size: 10pt; vertical-align: top }}
.chip {{ height: 22mm; border-radius: 3mm; border: 1px solid #ddd; margin-bottom: 2mm }}
.rule {{ font-size: 13pt; margin: 3mm 0 }} .slides img {{ width: 120mm; margin: 0 4mm 4mm 0; border: 1px solid #ddd }}
</style></head><body>
<section class="dark" {page}><img src="{data_uri(OUT / "logos" / "zerno_logo_white.png")}" style="width:110mm;margin-top:30mm">
<h1 style="margin-top:20mm">Брендбук сети кофеен «Зерно»</h1><p style="font-size:16pt">Логотип, цвета, шрифты и правила для презентаций · версия 2025</p></section>
<section {page}><h2>Логотип</h2><img src="{data_uri(OUT / "logos" / "zerno_logo.png")}" style="width:130mm">
<p class="rule">Охранное поле — не меньше половины высоты логотипа со всех сторон.</p>
<p class="rule">Минимальный размер логотипа — 24 px по высоте на слайде 960×540 (12 мм в печати).</p>
<p class="rule">Нельзя менять цвета логотипа, растягивать его, поворачивать и ставить на пёстрый фон.</p>
<p class="rule">На тёмном фоне используйте белую версию логотипа.</p></section>
<section {page}><h2>Фирменные цвета</h2>{sw}</section>
<section {page}><h2>Шрифты</h2>
<p style="font-family:'{HEADING}';font-size:30pt;font-weight:700">Шрифт заголовков: {HEADING} Bold</p>
<p style="font-size:18pt">Шрифт основного текста: {BODY} Regular</p>
<p class="rule">Заголовок слайда — вывод, а не название темы. Не более двух строк.</p>
<p class="rule">Не используйте больше двух шрифтов на одном слайде.</p>
<p class="rule">Минимальный кегль текста на слайде — 12 pt.</p></section>
<section><h2>Примеры слайдов</h2><div class="slides">
<img src="{data_uri(OUT / "slides" / "01_cover.png")}"><img src="{data_uri(OUT / "slides" / "02_chart.png")}">
<img src="{data_uri(OUT / "slides" / "03_closing.png")}"></div>
<p class="rule">Диаграммы: главная серия — цвет «Обжарка», остальные — приглушённые оттенки; подписи осей — цвет «Пенка».</p></section>
</body></html>'''


def main():
    (OUT / "logos").mkdir(exist_ok=True)
    (OUT / "slides").mkdir(exist_ok=True)
    logo(OUT / "logos" / "zerno_logo.png", PAL["text"][0])
    logo(OUT / "logos" / "zerno_logo_white.png", "FFFFFF")
    logo(OUT / "logos" / "zerno_mark.png", "FFFFFF", mark_only=True)
    logo_svg(OUT / "logos" / "zerno_logo.svg")
    for i, k in enumerate(("cover", "chart", "closing"), 1):
        slide(OUT / "slides" / f"0{i}_{k}.png", k)
    (OUT / "tokens.json").write_text(json.dumps(tokens(), ensure_ascii=False, indent=2), encoding="utf-8")
    html = OUT / "guideline.html"
    html.write_text(guideline_html(), encoding="utf-8")
    edge = shutil.which("msedge") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT / 'guideline.pdf'}", html.resolve().as_uri()], check=True, timeout=120)
    html.unlink()
    with zipfile.ZipFile(OUT / "brand_zerno.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((OUT / "logos").iterdir()) + sorted((OUT / "slides").iterdir()):
            z.write(p, f"{p.parent.name}/{p.name}")
    print("готово:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
