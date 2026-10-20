"""Чтение табличных данных: CSV/TSV, XLSX/XLS, табличный JSON и текстовые файлы с таблицами внутри.

Из каждого файла получается один или несколько датасетов (`Table`): DataFrame с «сырыми» строками
(типы колонок определяет analyze.py) и текстом вокруг таблицы — он идёт сценаристу как контекст.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

DATA_EXT = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".json"}
TEXT_EXT = {".txt", ".md", ".markdown"}


@dataclass
class Table:
    name: str                      # имя датасета (файл, лист, номер таблицы в тексте)
    df: pd.DataFrame
    source: str                    # csv | xlsx | json | text
    context: str = ""              # текст вокруг таблицы (для текстовых файлов)
    notes: list[str] = field(default_factory=list)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    df.columns = [str(c).strip() or f"col{i + 1}" for i, c in enumerate(df.columns)]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")] if len(df.columns) else df
    return df.reset_index(drop=True)


def read_csv(text: str, name: str) -> Table:
    # разделитель — тот, что даёт одинаковое число колонок в первых строках (запятая в «47,93» не в счёт:
    # стандартный Sniffer на русских CSV с «;» часто выбирает запятую)
    head = [ln for ln in text.splitlines()[:15] if ln.strip()]
    best, sep = -1, ","
    for cand in (";", "\t", "|", ","):
        counts = [ln.count(cand) for ln in head]
        if counts and counts[0] > 0 and len(set(counts)) == 1 and counts[0] > best:
            best, sep = counts[0], cand
    if best < 0:
        try:
            sep = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            sep = ";" if text.count(";") > text.count(",") else ","
    # значения читаются строками: числа с запятой, «12 500 ₽» и проценты разбирает analyze.py
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=True, na_values=["", "NA", "N/A", "-", "—", "null", "None"])
    return Table(name=name, df=_clean(df), source="csv")


def read_xlsx(data: bytes, name: str) -> list[Table]:
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object)
    out = []
    for sheet, df in sheets.items():
        df = _clean(df)
        if df.shape[0] >= 2 and df.shape[1] >= 1:
            out.append(Table(name=name if len(sheets) == 1 else f"{name} · {sheet}", df=df, source="xlsx"))
    return out


def read_json(text: str, name: str) -> list[Table]:
    obj = json.loads(text)
    out = []

    def add(rows, label):
        df = _clean(pd.DataFrame(rows))
        if df.shape[0] >= 2:
            out.append(Table(name=label, df=df.astype(object), source="json"))

    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        add(obj, name)
    elif isinstance(obj, dict):
        if isinstance(obj.get("columns"), list) and isinstance(obj.get("data"), list):
            add(pd.DataFrame(obj["data"], columns=obj["columns"]), name)
        elif all(isinstance(v, list) for v in obj.values()) and len({len(v) for v in obj.values()}) == 1:
            add(obj, name)                                   # {"колонка": [...], ...}
        else:
            for k, v in obj.items():                         # {"набор": [{...}, ...], ...}
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    add(v, f"{name} · {k}")
            if not out and all(isinstance(v, (int, float)) for v in obj.values()):
                add({"Категория": list(obj.keys()), "Значение": list(obj.values())}, name)
    return out


# ------------------------------------------------------------------ таблицы внутри текста
PIPE = re.compile(r"^\s*\|?.+\|.+\|?\s*$")
SEP_ROW = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _split_row(line: str, sep: str) -> list[str]:
    if sep == "|":
        return [c.strip() for c in line.strip().strip("|").split("|")]
    if sep == "\t":
        return [c.strip() for c in line.split("\t")]
    if sep == ";":
        return [c.strip() for c in line.split(";")]
    return [c.strip() for c in re.split(r"\s{2,}", line.strip())]


def find_text_tables(text: str, name: str, min_rows: int = 3) -> list[Table]:
    """Таблицы в тексте: markdown («| a | b |»), через табуляцию, через «;» или выровненные пробелами колонки."""
    lines = text.splitlines()
    out: list[Table] = []
    used = [False] * len(lines)
    i = 0
    while i < len(lines):
        line = lines[i]
        sep = "|" if PIPE.match(line) and line.count("|") >= 2 else "\t" if line.count("\t") >= 1 \
            else ";" if line.count(";") >= 2 else " " if len(re.split(r"\s{2,}", line.strip())) >= 3 else None
        if sep is None:
            i += 1
            continue
        ncol = len(_split_row(line, sep))
        block = [i]
        j = i + 1
        while j < len(lines):
            ln = lines[j]
            if sep == "|" and SEP_ROW.match(ln):
                block.append(j)
                j += 1
                continue
            if not ln.strip() or len(_split_row(ln, sep)) != ncol:
                break
            block.append(j)
            j += 1
        rows = [_split_row(lines[k], sep) for k in block if not (sep == "|" and SEP_ROW.match(lines[k]))]
        if len(rows) >= min_rows + 1 and ncol >= 2:
            df = _clean(pd.DataFrame(rows[1:], columns=rows[0]))
            before = " ".join(ln.strip() for ln in lines[max(0, i - 4):i] if ln.strip())
            out.append(Table(name=f"{name} · таблица {len(out) + 1}", df=df, source="text", context=before[-400:]))
            for k in block:
                used[k] = True
            i = j
        else:
            i += 1
    return out


def text_outside_tables(text: str) -> str:
    """Текст файла без строк таблиц — повествование для сценариста."""
    lines = text.splitlines()
    tables = find_text_tables(text, "x")
    if not tables:
        return text
    keep = []
    for ln in lines:
        if (PIPE.match(ln) and ln.count("|") >= 2) or SEP_ROW.match(ln) or ln.count("\t") >= 2:
            continue
        keep.append(ln)
    return "\n".join(keep)


def load(name: str, data: bytes) -> tuple[list[Table], str]:
    """Датасеты файла и его текст вне таблиц (для текстовых файлов)."""
    ext = Path(name).suffix.lower()
    stem = Path(name).stem
    if ext in (".csv", ".tsv"):
        return [read_csv(_decode(data), stem)], ""
    if ext in (".xlsx", ".xlsm", ".xls"):
        return read_xlsx(data, stem), ""
    if ext == ".json":
        return read_json(_decode(data), stem), ""
    if ext in TEXT_EXT:
        text = _decode(data)
        return find_text_tables(text, stem), text_outside_tables(text)
    return [], ""
