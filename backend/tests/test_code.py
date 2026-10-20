"""Слайды с кодом: листинги из текста методички, вставка в колоду, вёрстка рецептом."""
from app.audit.contextual import excerpt
from app.planning.code import find_snippets, group_snippets
from app.planning.models import ContentSlide, DeckContent, Item
from app.planning.planner import diversify, ensure_code

METHOD = """Исходный код программы представлен функцией для проверки чётности
числа в листинге 1:
Листинг 1. Функция для проверки чётности числа
def is_even(n):
return n % 2 == 0
Для данной функции был разработан модульный тест (листинг 2):
Листинг 2. Модульный тест для функции проверки чётности числа
def test_is_even():
assert is_even(2) == True # проверка, что чётное число 2 правильно определя
ется как True
assert is_even(3) == False
Для более полного процесса проверки в код были добавлены «мутанты»:
1.
Замена оператора проверки остатка на деление:
def is_even(n):
return n / 2 == 0
Результат — Мутант «убит», так как тест не прошёл.
"""


def test_snippets_restore_indent_and_captions():
    sn = find_snippets(METHOD)
    assert [s.caption for s in sn][:2] == ["Листинг 1. Функция для проверки чётности числа",
                                          "Листинг 2. Модульный тест для функции проверки чётности числа"]
    assert sn[0].text == "def is_even(n):\n    return n % 2 == 0"
    assert sn[1].lines[1] == "    assert is_even(2) == True"           # комментарий и его перенос отброшены
    assert sn[2].lead == "Замена оператора проверки остатка на деление"
    groups = group_snippets(sn)
    assert len(groups) == 2 and "def test_is_even" in groups[0].text      # листинги вместе, мутант — отдельно
    assert groups[1].lines[0] == "# Замена оператора проверки остатка на деление"


def test_no_code_in_plain_text():
    assert find_snippets("Модульное тестирование — метод проверки отдельных компонентов.\nТесты пишутся заранее.") == []


def test_ensure_code_inserts_after_related_slide():
    deck = DeckContent(title="t", slides=[
        ContentSlide(id="s1", intent="title", title="Тестирование"),
        ContentSlide(id="s2", intent="cards", title="Модульные тесты проверяют функции",
                     items=[Item(head="Проверка чётности", text="функция и модульный тест")]),
        ContentSlide(id="s3", intent="bullets", title="Отчёт", items=[Item(head="ГОСТ", text="оформление")]),
        ContentSlide(id="s4", intent="closing", title="Итоги"),
    ])
    added = ensure_code(deck, METHOD)
    assert [s.intent for s in deck.slides] == ["title", "cards", "code", "code", "bullets", "closing"]
    assert [s.id for s in deck.slides] == ["s1", "s2", "s3", "s4", "s5", "s6"]
    assert added[0].code.caption.startswith("Листинг 1") and "Код уже стоит" in added[0].instruction
    assert ensure_code(deck, METHOD) == []                                   # второй раз не добавляет


def test_diversify_keeps_consecutive_processes():
    deck = DeckContent(title="t", slides=[ContentSlide(id=f"s{i}", intent=k, title=f"Этапы {i}",
                                                       items=[Item(head="a", text="b")] * 3)
                                          for i, k in enumerate(["process", "process", "timeline", "cards", "quote"], 1)])
    diversify(deck)
    assert [s.intent for s in deck.slides][:2] == ["process", "process"]


def test_excerpt_finds_middle_of_long_source():
    src = "Тема: тестирование\n" + "\n".join(f"Общий абзац номер {i} без нужных слов." for i in range(600)) \
        + "\nМодуль должен содержать минимум 5 функций.\n" + "\n".join("Хвост." for _ in range(300))
    out = excerpt(src, "Разработка модуля: минимум 5 функций", 1500)
    assert out.startswith("Тема: тестирование") and "минимум 5 функций" in out and len(out) <= 1700
