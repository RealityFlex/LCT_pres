import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.parsing.analyze import TemplateAnalyzer
t=time.time(); a=TemplateAnalyzer(Path(sys.argv[1])); sl=a.run()
print('time', round(time.time()-t,2))
for s in sl:
    t=s.title
    print(f"{s.index:2} {s.kind:8} svc={int(s.service)} lay={s.layout[:18]!r:20} title={(t.text[:40] if t else None)!r} sz={t.max_size if t else 0} kick={bool(s.kicker)} label={bool(s.label)} chrome={len(s.chrome)} content={len(s.content)} groups={[ (g.count,g.arrangement,len(g.items[0]['members'])) for g in s.groups]} {s.service_reason}")
