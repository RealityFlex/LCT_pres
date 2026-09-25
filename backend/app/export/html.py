"""Экспорт в HTML: каждая страница PDF-рендера → векторный SVG, единый файл-вьюер с навигацией."""
from __future__ import annotations

import html
from pathlib import Path

import pymupdf

TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#0f1115;--fg:#e8eaf0;--muted:#8a90a0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
header{{position:sticky;top:0;z-index:2;display:flex;gap:16px;align-items:center;padding:10px 20px;background:rgba(15,17,21,.9);backdrop-filter:blur(8px)}}
header b{{font-weight:600}}header span{{color:var(--muted)}}
main{{display:flex;flex-direction:column;align-items:center;gap:28px;padding:24px 16px 80px}}
section{{width:min(1280px,96vw);box-shadow:0 10px 40px rgba(0,0,0,.45);border-radius:6px;overflow:hidden;background:#fff}}
section svg{{display:block;width:100%;height:auto}}
.sr{{position:absolute;left:-9999px}}
body.present header{{display:none}}body.present main{{padding:0;gap:0}}
body.present section{{display:none;width:100vw;height:100vh;border-radius:0;box-shadow:none;background:#000}}
body.present section.on{{display:flex;align-items:center;justify-content:center}}
body.present section svg{{max-height:100vh;width:auto;max-width:100vw}}
</style></head><body>
<header><b>{title}</b><span>{n} слайдов · ← → для навигации · F — полноэкранный показ</span></header>
<main>{slides}</main>
<script>
const s=[...document.querySelectorAll('section')];let i=0;
function show(k){{i=Math.max(0,Math.min(s.length-1,k));s.forEach((e,j)=>e.classList.toggle('on',j===i));
if(!document.body.classList.contains('present'))s[i].scrollIntoView({{behavior:'smooth',block:'center'}});}}
document.addEventListener('keydown',e=>{{if(['ArrowRight','PageDown',' '].includes(e.key)){{show(i+1);e.preventDefault()}}
else if(['ArrowLeft','PageUp'].includes(e.key)){{show(i-1);e.preventDefault()}}
else if(e.key==='f'||e.key==='F'){{document.body.classList.toggle('present');show(i)}}
else if(e.key==='Escape'){{document.body.classList.remove('present')}}}});
</script></body></html>"""


def pdf_to_html(pdf: Path, out: Path, title: str, texts: list[str] | None = None) -> Path:
    doc = pymupdf.open(pdf)
    parts = []
    for i, page in enumerate(doc):
        svg = page.get_svg_image(text_as_path=True)
        svg = svg[svg.find("<svg"):]
        alt = html.escape(texts[i]) if texts and i < len(texts) else ""
        parts.append(f'<section id="s{i + 1}" aria-label="Слайд {i + 1}">{svg}<div class="sr">{alt}</div></section>')
    doc.close()
    out.write_text(TEMPLATE.format(title=html.escape(title), n=len(parts), slides="\n".join(parts)), encoding="utf-8")
    return out
