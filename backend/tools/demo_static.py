"""Сборка трёх вариантов по фиксированному контенту (без LLM) — для визуальной отладки вёрстки."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.parsing.profile import load_profile
from app.planning.models import DeckContent
from app.planning.variants import build_variant, slide_extras
from app.layout.recipes import Composer
from app.layout.builder import DeckBuilder
from app.parsing.render import render_deck

tid = sys.argv[1]; out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
only = sys.argv[3] if len(sys.argv) > 3 else "ABC"
p = load_profile(tid)
content = DeckContent.model_validate_json(Path(__file__).resolve().parents[1].joinpath('tests/fixtures/demo_content.json').read_text(encoding='utf-8'))
for vid, strat in [("A","faithful"),("B","visual"),("C","dense")]:
    if vid not in only: continue
    t=time.time()
    plan = build_variant(content, p, vid, vid, strat)
    comp = Composer(p); b = DeckBuilder(p)
    for i, spec in enumerate(plan.slides, 1):
        lay = comp.compose_best(spec, i, content.title, slide_extras(content, spec))
        if lay.warnings or any(e.overflow for e in lay.elements):
            print(vid, i, spec.recipe, lay.warnings, [e.role for e in lay.elements if e.overflow])
        b.add(lay)
    f = b.save(out / f"{p.name}_{vid}.pptx")
    pdf, pngs = render_deck(f, out / f"{p.name}_{vid}", prefix="s")
    ims=[Image.open(x).convert('RGB') for x in pngs]; w,h=ims[0].size; sc=640/w
    ims=[im.resize((640,int(h*sc))) for im in ims]; w,h=ims[0].size; cols=3; rows=(len(ims)+cols-1)//cols
    g=Image.new('RGB',(w*cols+ (cols-1)*6,h*rows+(rows-1)*6),'white')
    for i,im in enumerate(ims): g.paste(im,((i%cols)*(w+6),(i//cols)*(h+6)))
    g.save(out/f"{p.name}_{vid}.jpg",quality=82); print(vid, len(pngs), 'slides', round(time.time()-t,1),'s', out/f"{p.name}_{vid}.jpg")
