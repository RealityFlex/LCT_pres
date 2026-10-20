"""Сборка сводного PDF документации: README + ARCHITECTURE + MODELS + AUDIT → docs/Lekalo_Documentation.pdf.

Markdown → HTML (markdown-it-py, CommonMark + таблицы) → печать в PDF через Microsoft Edge (Playwright, Chromium)
→ номера страниц и метаданные (PyMuPDF). Оформление: обложка «Лекало», Segoe UI, фиолетовые заголовки, оглавление
в закладках PDF.

Запуск из корня репозитория:
    python docs/build_pdf.py            # пересобрать docs/Lekalo_Documentation.pdf
    python docs/build_pdf.py --html     # дополнительно сохранить промежуточный HTML рядом с PDF
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

import pymupdf
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "Lekalo_Documentation.pdf"
REPO = "https://github.com/RealityFlex/LCT_pres/blob/main/"

# (ключ, файл, название на обложке) — порядок частей в PDF
PARTS = [
    ("readme", ROOT / "README.md", "Развёртывание и использование", "README.md"),
    ("arch", DOCS / "ARCHITECTURE.md", "Архитектура", "docs/ARCHITECTURE.md"),
    ("models", DOCS / "MODELS.md", "Модели", "docs/MODELS.md"),
    ("audit", DOCS / "AUDIT.md", "Аудит", "docs/AUDIT.md"),
]
DOC_KEY = {"README.md": "readme", "ARCHITECTURE.md": "arch", "MODELS.md": "models", "AUDIT.md": "audit"}

CSS = """
@page { size: A4; margin: 18mm 18mm 20mm 18mm; }
* { box-sizing: border-box; }
html { font-size: 10pt; }
body { font-family: "Segoe UI", system-ui, sans-serif; color: #1A1D24; line-height: 1.5; margin: 0;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
a { color: #5B21B6; text-decoration: none; }
h1, h2, h3, h4 { font-weight: 700; line-height: 1.25; break-after: avoid; page-break-after: avoid; }
h1 { font-size: 21pt; color: #5B21B6; margin: 1.6em 0 0.9em; padding-bottom: 0.35em; border-bottom: 1.5pt solid #5B21B6; }
h2 { font-size: 15pt; color: #4C1D95; margin: 1.5em 0 0.7em; }
h3 { font-size: 12pt; color: #1F2937; margin: 1.3em 0 0.6em; }
h4 { font-size: 10.5pt; color: #1F2937; margin: 1.1em 0 0.5em; }
p { margin: 0 0 0.85em; }
ul, ol { margin: 0 0 0.85em; padding-left: 1.6em; }
li { margin: 0.12em 0; }
hr { border: 0; border-top: 0.75pt solid #D6D0E6; margin: 1.6em 0; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: 0.88em; background: #F3F0FA;
       border-radius: 3pt; padding: 0.05em 0.3em; }
pre { background: #F6F5FA; border: 0.75pt solid #E3DEF0; border-radius: 4pt; padding: 0.9em 1em; margin: 0 0 1em;
      white-space: pre-wrap; word-break: break-word; line-height: 1.55; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.3pt; border-radius: 0; }
table { border-collapse: collapse; width: 100%; margin: 0 0 1.1em; font-size: 8.8pt; line-height: 1.45; }
th, td { border: 0.75pt solid #D6D0E6; padding: 0.55em 0.8em; text-align: left; vertical-align: top; }
th { background: #EDE9FE; font-weight: 700; }
tr { break-inside: avoid; }
blockquote { margin: 0 0 1em; padding: 0.2em 1em; border-left: 3pt solid #D6D0E6; color: #374151; }
strong { font-weight: 700; }
.part { break-before: page; page-break-before: always; }
.part > h1:first-child, .part-first > h1:first-child, .part > a:first-child + h1, .part-first > a:first-child + h1 { margin-top: 0; }
h1 code, h2 code, h3 code, h4 code { font-weight: 400; font-size: 0.72em; }
.cover { height: 250mm; padding-top: 72mm; break-after: page; page-break-after: always; }
.cover .t { font-size: 34pt; font-weight: 700; color: #5B21B6; line-height: 1.1; margin: 0 0 0.75em; }
.cover .s { font-size: 15pt; color: #374151; margin: 0 0 2.2em; }
.cover .m { font-size: 11pt; color: #6B7280; margin: 0; line-height: 1.6; }
.cover ol { margin-top: 2.6em; font-size: 12pt; line-height: 1.85; }
.cover ol .f { font-size: 9pt; color: #9CA3AF; margin-left: 0.3em; }
"""


def slugify(text: str) -> str:
    """Якорь заголовка как у GitHub: строчные, без знаков препинания, пробелы → дефисы."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def rewrite_href(href: str, key: str) -> str:
    if re.match(r"^(https?:|mailto:)", href):
        return href
    href = unquote(href)            # markdown-it кодирует кириллицу в якорях, id заголовков — в исходном виде
    if href.startswith("#"):
        return f"#{key}-{href[1:]}"
    path, _, frag = href.partition("#")
    name = Path(path).name
    if name in DOC_KEY and path.endswith(".md"):
        k = DOC_KEY[name]
        return f"#{k}-{frag}" if frag else f"#{k}"
    # прочие файлы репозитория — ссылкой на GitHub
    base = (ROOT / "README.md").parent if key == "readme" else DOCS
    try:
        rel = (base / path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return href
    return REPO + rel + (f"#{frag}" if frag else "")


def render(md_text: str, key: str) -> str:
    md = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")
    tokens = md.parse(md_text)
    used: dict[str, int] = {}
    first_h1 = True
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            inline = tokens[i + 1]
            text = "".join(c.content for c in (inline.children or []) if c.type in ("text", "code_inline"))
            slug = slugify(text)
            n = used.get(slug, 0)
            used[slug] = n + 1
            sid = f"{key}-{slug}" + (f"-{n}" if n else "")
            if t.tag == "h1" and first_h1:
                first_h1 = False
                t.attrSet("id", key)          # вершина части — для ссылок вида README.md / MODELS.md
                # и якорь по тексту заголовка тоже работает
                t.meta["extra_id"] = sid
            else:
                t.attrSet("id", sid)
        if t.children:
            for c in t.children:
                if c.type == "link_open" and c.attrGet("href"):
                    c.attrSet("href", rewrite_href(str(c.attrGet("href")), key))
    out = md.renderer.render(tokens, md.options, {})
    # дополнительный якорь у первого h1
    for t in tokens:
        if t.type == "heading_open" and t.meta.get("extra_id"):
            out = out.replace(f'<h1 id="{key}">', f'<a id="{t.meta["extra_id"]}"></a><h1 id="{key}">', 1)
    return out


def build_html() -> str:
    cover_items = "".join(
        f'<li><a href="#{k}">{html.escape(title)}</a><span class="f">{html.escape(f)}</span></li>'
        for k, _, title, f in PARTS)
    cover = (
        '<section class="cover">'
        '<div class="t">Лекало</div>'
        '<div class="s">Цифровой дизайнер презентаций — документация</div>'
        '<p class="m">ЛЦТ 2026 · задача №4 VK Tech · команда RealityFlex<br>'
        'Репозиторий: github.com/RealityFlex/LCT_pres</p>'
        f'<ol>{cover_items}</ol>'
        '</section>')
    body = [cover]
    for i, (key, path, _, _) in enumerate(PARTS):
        md_text = path.read_text(encoding="utf-8")
        cls = "part" if i else "part-first"
        body.append(f'<section class="{cls}">{render(md_text, key)}</section>')
    return ("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<title>Лекало — цифровой дизайнер презентаций: документация</title>"
            f"<style>{CSS}</style></head><body>{''.join(body)}</body></html>")


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="load")
        page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True,
                 outline=True, tagged=True)
        browser.close()


def finish(raw_pdf: Path, out: Path) -> int:
    """Номера страниц «N / M» (кроме обложки) и метаданные."""
    doc = pymupdf.open(raw_pdf)
    total = doc.page_count
    for i, page in enumerate(doc):
        if i == 0:
            continue
        label = f"{i + 1} / {total}"
        w = pymupdf.get_text_length(label, fontname="helv", fontsize=8.5)
        x = (page.rect.width - w) / 2
        page.insert_text((x, page.rect.height - 23.5), label, fontname="helv", fontsize=8.5,
                         color=(0x73 / 255, 0x73 / 255, 0x80 / 255))
    # Chromium иногда дублирует текст заголовка в закладке («МодулиМодули») — оставляем одну половину
    toc = doc.get_toc(simple=False)
    for item in toc:
        t = item[1]
        if len(t) % 2 == 0 and t[: len(t) // 2] == t[len(t) // 2:]:
            item[1] = t[: len(t) // 2]
    doc.set_toc(toc)
    meta = doc.metadata or {}
    meta.update({"title": "Лекало — цифровой дизайнер презентаций: документация", "author": "RealityFlex",
                 "subject": "ЛЦТ 2026, задача №4 VK Tech", "keywords": ""})
    doc.set_metadata(meta)
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="сохранить промежуточный HTML рядом с PDF")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    page_html = build_html()
    with tempfile.TemporaryDirectory() as tmp:
        hp = Path(tmp) / "doc.html"
        hp.write_text(page_html, encoding="utf-8")
        if args.html:
            args.out.with_suffix(".html").write_text(page_html, encoding="utf-8")
        raw = Path(tmp) / "raw.pdf"
        print_pdf(hp, raw)
        n = finish(raw, args.out)
    print(f"{args.out} — страниц: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
