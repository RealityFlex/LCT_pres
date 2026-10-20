"""Брендбук: декодер kiwi/.fig на синтетическом файле, токены JSON, роли цветов, перекраска шаблона."""
import io
import json
import os
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from app.brand.fig import brand_from_fig, load
from app.brand.model import BrandColor, BrandFont, assign_roles, pick_fonts
from app.brand.tokens import brand_from_tokens


# ------------------------------------------------------------------ мини-кодировщик kiwi (для теста)
def vu(n: int) -> bytes:
    out = b""
    while True:
        b = n & 127
        n >>= 7
        out += bytes([b | (128 if n else 0)])
        if not n:
            return out


def vi(n: int) -> bytes:
    return vu((n << 1) ^ (n >> 31) if n >= 0 else ((-n - 1) << 1) | 1)


def vf(x: float) -> bytes:
    if x == 0:
        return b"\x00"
    bits = struct.unpack("<I", struct.pack("<f", x))[0]
    bits = ((bits >> 23) | (bits << 9)) & 0xFFFFFFFF
    return struct.pack("<I", bits)


def s(x: str) -> bytes:
    return x.encode() + b"\x00"


BUILTIN = {"bool": -1, "byte": -2, "int": -3, "uint": -4, "float": -5, "string": -6}
# определения: имя, вид (0 enum, 1 struct, 2 message), поля [(имя, тип, массив)]
DEFS = [
    ("NodeType", 0, [("DOCUMENT", None, False), ("CANVAS", None, False), ("FRAME", None, False), ("VECTOR", None, False),
                     ("TEXT", None, False)]),
    ("StyleType", 0, [("NONE", None, False), ("FILL", None, False), ("TEXT", None, False)]),
    ("PaintType", 0, [("SOLID", None, False)]),
    ("WindingRule", 0, [("NONZERO", None, False), ("ODD", None, False)]),
    ("Color", 1, [("r", "float", False), ("g", "float", False), ("b", "float", False), ("a", "float", False)]),
    ("Vector", 1, [("x", "float", False), ("y", "float", False)]),
    ("GUID", 1, [("sessionID", "uint", False), ("localID", "uint", False)]),
    ("Paint", 2, [("type", "PaintType", False), ("color", "Color", False), ("visible", "bool", False)]),
    ("FontName", 1, [("family", "string", False), ("style", "string", False), ("postscript", "string", False)]),
    ("ParentIndex", 1, [("guid", "GUID", False), ("position", "string", False)]),
    ("Path", 2, [("windingRule", "WindingRule", False), ("commandsBlob", "uint", False)]),
    ("TextData", 2, [("characters", "string", False)]),
    ("NodeChange", 2, [("guid", "GUID", False), ("parentIndex", "ParentIndex", False), ("type", "NodeType", False),
                       ("name", "string", False), ("size", "Vector", False), ("fillPaints", "Paint", True),
                       ("styleType", "StyleType", False), ("fontName", "FontName", False), ("fontSize", "float", False),
                       ("fillGeometry", "Path", True), ("textData", "TextData", False), ("visible", "bool", False)]),
    ("Blob", 2, [("bytes", "byte", True)]),
    ("Message", 2, [("nodeChanges", "NodeChange", True), ("blobs", "Blob", True)]),
]
IDX = {d[0]: i for i, d in enumerate(DEFS)}


def schema_bytes() -> bytes:
    out = vu(len(DEFS))
    for name, kind, fields in DEFS:
        out += s(name) + bytes([kind]) + vu(len(fields))
        for v, (fname, ftype, arr) in enumerate(fields):
            t = 0 if ftype is None else BUILTIN.get(ftype, IDX.get(ftype))
            out += s(fname) + vi(t) + bytes([1 if arr else 0]) + vu(v if kind == 0 else v + 1)
    return out


def msg(name: str, fields: dict) -> bytes:
    d = DEFS[IDX[name]]
    out = b""
    for v, (fname, ftype, arr) in enumerate(d[2]):
        if fname not in fields:
            continue
        out += vu(v + 1) + field(ftype, arr, fields[fname])
    return out + b"\x00"


def val(t: str, x) -> bytes:
    if t == "float":
        return vf(float(x))
    if t == "uint":
        return vu(x)
    if t == "string":
        return s(x)
    if t == "bool":
        return bytes([1 if x else 0])
    d = DEFS[IDX[t]]
    if d[1] == 0:
        return vu([f[0] for f in d[2]].index(x))
    if d[1] == 1:
        return b"".join(val(ft, x[fn]) for fn, ft, _ in d[2])
    return msg(t, x)


def field(t, arr, x) -> bytes:
    if arr:
        if t == "byte":
            return vu(len(x)) + x
        return vu(len(x)) + b"".join(val(t, e) for e in x)
    return val(t, x)


def g(i):
    return {"sessionID": 1, "localID": i}


def solid(r, gg, b):
    return [{"type": "SOLID", "color": {"r": r, "g": gg, "b": b, "a": 1.0}, "visible": True}]


def make_fig() -> bytes:
    square = b"\x01" + struct.pack("<ff", 0, 0) + b"\x02" + struct.pack("<ff", 40, 0) + b"\x02" + \
        struct.pack("<ff", 40, 40) + b"\x02" + struct.pack("<ff", 0, 40) + b"\x00"
    nodes = [
        {"guid": g(0), "type": "DOCUMENT", "name": "Document"},
        {"guid": g(1), "parentIndex": {"guid": g(0), "position": "a"}, "type": "CANVAS", "name": "Presentation"},
        {"guid": g(2), "parentIndex": {"guid": g(1), "position": "a"}, "type": "FRAME", "name": "Slide 1",
         "size": {"x": 1920, "y": 1080}, "fillPaints": solid(0.1, 0.1, 0.15), "visible": True},
        {"guid": g(3), "parentIndex": {"guid": g(1), "position": "b"}, "type": "FRAME", "name": "Brand/Primary",
         "styleType": "FILL", "fillPaints": solid(0.9, 0.1, 0.35), "size": {"x": 10, "y": 10}},
        {"guid": g(4), "parentIndex": {"guid": g(1), "position": "c"}, "type": "TEXT", "name": "Heading L",
         "styleType": "TEXT", "fontName": {"family": "Manrope", "style": "Bold", "postscript": ""}, "fontSize": 40},
        {"guid": g(5), "parentIndex": {"guid": g(1), "position": "d"}, "type": "FRAME", "name": "Logo",
         "size": {"x": 40, "y": 40}, "visible": True},
        {"guid": g(6), "parentIndex": {"guid": g(5), "position": "a"}, "type": "VECTOR", "name": "mark",
         "size": {"x": 40, "y": 40}, "fillPaints": solid(0.9, 0.1, 0.35), "visible": True,
         "fillGeometry": [{"windingRule": "NONZERO", "commandsBlob": 0}]},
        {"guid": g(7), "parentIndex": {"guid": g(2), "position": "a"}, "type": "TEXT", "name": "t",
         "fontName": {"family": "Manrope", "style": "Regular", "postscript": ""}, "fontSize": 18, "visible": True,
         "textData": {"characters": "Текст слайда о бренде"}, "fillPaints": solid(1, 1, 1)},
    ]
    data = msg("Message", {"nodeChanges": nodes, "blobs": [{"bytes": square}]})
    sch = zlib.compress(schema_bytes())[2:-4]                       # raw deflate, как у Figma
    body = zlib.compress(data)[2:-4]
    canvas = b"fig-kiwi" + struct.pack("<I", 101) + struct.pack("<I", len(sch)) + sch + struct.pack("<I", len(body)) + body
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("canvas.fig", canvas)
        z.writestr("meta.json", json.dumps({"file_name": "Test Brand"}))
    return buf.getvalue()


def test_fig_decoder_roundtrip():
    doc = load(make_fig(), "test.fig")
    assert doc.name == "Test Brand" and len(doc.nodes) == 8
    assert doc.nodes[3]["fillPaints"][0]["color"]["r"] == pytest.approx(0.9, abs=1e-6)


def test_brand_from_fig(tmp_path):
    kit = brand_from_fig(make_fig(), "test.fig", tmp_path)
    assert kit.palette["primary"] == "E51A59"       # 0,9 во float32 → 229
    assert kit.fonts["heading"] == "Manrope"
    assert kit.slides and kit.slides[0]["w"] == 1920 and kit.palette.get("bg_dark") == "1A1A26"
    assert kit.logos and Path(kit.logos[0].png).exists() and "<path" in Path(kit.logos[0].svg).read_text()


def test_not_a_fig():
    from app.brand.fig import FigError
    with pytest.raises(FigError):
        load(b"PK\x03\x04garbage", "x.fig")


# ------------------------------------------------------------------ токены и роли
def test_tokens_w3c_and_refs():
    data = {"color": {"brand": {"primary": {"$type": "color", "$value": "#0057B8"},
                                "accent": {"$type": "color", "$value": "#FFD500"}},
                      "background": {"$type": "color", "$value": "{color.base.white}"},
                      "base": {"white": {"$type": "color", "$value": "#FFFFFF"}},
                      "text": {"$type": "color", "$value": "#111111"}},
            "font": {"heading": {"$type": "fontFamily", "$value": "Golos Text"},
                     "body": {"$type": "fontFamily", "$value": ["Inter", "sans-serif"]}}}
    kit = brand_from_tokens(json.dumps(data).encode(), "tokens.json")
    assert kit.palette["primary"] == "0057B8" and kit.palette["bg"] == "FFFFFF" and kit.palette["text"] == "111111"
    assert kit.fonts == {"heading": "Golos Text", "body": "Inter"}


def test_roles_saturated_primary_not_grey_blue():
    cs = [BrandColor(hex="889BAF", name="Muted Foreground", weight=500), BrandColor(hex="FF2768", weight=60),
          BrandColor(hex="FFFFFF", weight=6000), BrandColor(hex="1C232B", weight=900)]
    pal, _ = assign_roles(cs)
    assert pal["primary"] == "FF2768" and pal["bg"] == "FFFFFF" and pal["text"] == "1C232B"


def test_fonts_usage_beats_platform_styles():
    fonts = [BrandFont(family="Roboto", name="Title 1", size=28, weight=5) for _ in range(30)] + \
        [BrandFont(family="VK Sans Display", size=32, weight=200), BrandFont(family="VK Sans Text", size=15, weight=900)]
    f = pick_fonts(fonts)
    assert f["heading"].startswith("VK Sans") and f["body"] == "VK Sans Text"


# ------------------------------------------------------------------ реальные .fig (если положены рядом)
FIG_DIR = os.environ.get("LEKALO_FIG_SAMPLES", "")


@pytest.mark.skipif(not FIG_DIR or not Path(FIG_DIR).exists(), reason="LEKALO_FIG_SAMPLES не задан")
def test_real_fig_samples(tmp_path):
    for p in sorted(Path(FIG_DIR).rglob("*.fig")):
        kit = brand_from_fig(p.read_bytes(), p.name, tmp_path / p.stem)
        assert kit.palette.get("primary"), p.name
        assert kit.fonts.get("body"), p.name


# ------------------------------------------------------------------ примеры брендбука «Зерно» (examples/brand_zerno)
BRAND = Path(__file__).resolve().parents[2] / "examples" / "brand_zerno"


@pytest.mark.skipif(not (BRAND / "guideline.pdf").exists(), reason="примеры брендбука не собраны")
def test_zerno_formats_agree(tmp_path):
    from app.brand.images import brand_from_images
    from app.brand.pdf import brand_from_pdf
    tok = brand_from_tokens((BRAND / "tokens.json").read_bytes(), "tokens.json")
    pdf = brand_from_pdf((BRAND / "guideline.pdf").read_bytes(), "guideline.pdf", tmp_path / "pdf")
    img = brand_from_images([("brand_zerno.zip", (BRAND / "brand_zerno.zip").read_bytes())], tmp_path / "img")
    assert tok.palette["primary"] == pdf.palette["primary"] == "C8582A"
    assert tok.fonts == pdf.fonts == {"heading": "Manrope", "body": "Golos Text"}
    assert tok.spacing == {"margin": 72.0, "gap": 24.0, "radius": 12.0} and tok.logo_min_h == pdf.logo_min_h == 24.0
    assert pdf.logo_clear == 0.5 and pdf.logos and any("Охранное поле" in r for r in pdf.rules)
    assert any(lg.dark_bg for lg in img.logos) and any(not lg.dark_bg for lg in img.logos)
