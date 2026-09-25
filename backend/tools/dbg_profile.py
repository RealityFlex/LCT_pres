import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from app.parsing.profile import load_profile
p = load_profile(sys.argv[1])
W,H=p.slide_w,p.slide_h
pal=p.palette
print('palette', pal.bg_light, pal.bg_dark, pal.text_dark, pal.primary, pal.accents, 'chart', pal.chart, 'surface', pal.surface, 'muted', pal.muted_dark)
print('colors', [(c['hex'],c['weight'],c['role']) for c in pal.colors[:12]])
t=p.typography
for r in ['title','subtitle','kicker','heading','body','caption','number']:
    s=getattr(t,r); print(r, s and (s.font,s.size,s.color,s.bold,s.caps))
print('scale', t.scale, 'caps', t.title_caps, 'fonts', p.fonts_found)
print('margins', [round(v/914400,2) for v in (p.margins.x,p.margins.y,p.margins.w,p.margins.h)], 'gap', round(p.gap/914400,2))
print('cards', [(c.source_slide,c.geom,c.fill,c.line,c.accent,c.text_color, bool(c.marker_xml)) for c in p.card_styles])
print('table', p.table_style)
print('narr', p.narrative)
ims=[]
for c in p.canvases:
    im=Image.open(c.preview).convert('RGB'); iw,ih=im.size; d=ImageDraw.Draw(im)
    b=c.content_box; sx,sy=iw/W,ih/H
    d.rectangle([b.x*sx,b.y*sy,b.x2*sx,b.y2*sy],outline=(255,0,0),width=3)
    for sl in c.slots:
        bb=sl.box; d.rectangle([bb.x*sx,bb.y*sy,bb.x2*sx,bb.y2*sy],outline=(0,200,0),width=2); d.text((bb.x*sx+2,bb.y*sy+2),sl.role,fill=(0,160,0))
    d.rectangle([0,0,300,22],fill='black'); d.text((4,4),f"{c.id} {c.kind} dark={c.dark} busy={c.bg_busy} sc={c.score:.2f} {c.bg}",fill='white')
    ims.append(im.resize((480,int(480*ih/iw))))
cols=4; w,h=ims[0].size; rows=(len(ims)+cols-1)//cols
g=Image.new('RGB',(w*cols,h*rows),'white')
for i,im in enumerate(ims): g.paste(im,((i%cols)*w,(i//cols)*h))
out=Path(sys.argv[2]); g.save(out,quality=85); print(out)
