import sys, asyncio, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.parsing.profile import load_profile
from app.planning.models import Brief
from app.planning.planner import plan_deck
from app.llm.skills import SkillRun
from app.llm.client import get_llm

async def main():
    p = load_profile(sys.argv[1])
    brief = Brief(topic="Внедрение платформы «Умный склад» в розничной сети", purpose="проект",
                  audience="совет директоров",
                  details=("Пилот на складе в Москве, январь–июнь 2026. Время сборки заказа снизилось с 4,5 до 1,5 часа. "
                           "Точность учёта выросла с 91% до 99,2%. Потери выручки из-за пересортицы сократились с 12% до 3%. "
                           "Бюджет проекта 48 млн руб., окупаемость 9 месяцев. План: 12 складов до конца 2026 года. "
                           "Время сборки по месяцам (ч): янв 4,5; фев 4,2; мар 3,1; апр 2,2; май 1,7; июн 1,5."))
    run = SkillRun(); t = time.time()
    deck = await plan_deck(brief, p, run)
    print('seconds', round(time.time()-t,1), run.used, get_llm().stats)
    for s in deck.slides:
        print(s.id, s.intent, '|', s.kicker, '|', s.title, '|', len(s.items), 'chart' if s.chart else '', 'table' if s.table else '', [i.value for i in s.items if i.value])
    Path(sys.argv[2]).write_text(deck.model_dump_json(indent=1), encoding='utf-8')
asyncio.run(main())
