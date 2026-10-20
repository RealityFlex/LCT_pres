"""Минимальный декодер формата kiwi (github.com/evanw/kiwi) — в нём Figma хранит .fig.

Схема лежит в самом файле (первый блок), поэтому декодер общий: читает определения enum / struct / message
и по ним раскодирует данные. Кодирование значений:
  bool, byte — байт; int — zigzag-varint; uint — varint; float — 0 или 4 байта с циклическим сдвигом;
  string — UTF-8 до нуля; struct — поля подряд; message — пары (номер поля, значение) до нуля;
  массив — varint-длина и элементы; byte[] — длина и сырые байты.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

BUILTIN = ["bool", "byte", "int", "uint", "float", "string", "int64", "uint64"]
ENUM, STRUCT, MESSAGE = 0, 1, 2


@dataclass
class Field:
    name: str
    type: str            # имя встроенного типа или определения
    array: bool
    value: int


@dataclass
class Definition:
    name: str
    kind: int
    fields: list[Field] = field(default_factory=list)
    by_value: dict[int, Field] = field(default_factory=dict)


class Reader:
    __slots__ = ("b", "i", "obj")

    def __init__(self, data: bytes):
        self.obj = bytes(data)          # bytes.find — быстрый поиск конца строки
        self.b = self.obj               # индексация bytes даёт int и быстрее memoryview
        self.i = 0

    def byte(self) -> int:
        v = self.b[self.i]
        self.i += 1
        return v

    def uint(self) -> int:
        b, i = self.b, self.i
        shift = res = 0
        while True:
            c = b[i]
            i += 1
            res |= (c & 127) << shift
            if c < 128 or shift >= 35:
                break
            shift += 7
        self.i = i
        return res

    def uint64(self) -> int:
        b, i = self.b, self.i
        shift = res = 0
        while True:
            c = b[i]
            i += 1
            if shift == 56:
                res |= c << 56
                break
            res |= (c & 127) << shift
            if c < 128:
                break
            shift += 7
        self.i = i
        return res

    def int(self) -> int:
        v = self.uint()
        return ~(v >> 1) if v & 1 else v >> 1

    def int64(self) -> int:
        v = self.uint64()
        return ~(v >> 1) if v & 1 else v >> 1

    def float(self) -> float:
        b, i = self.b, self.i
        first = b[i]
        if first == 0:
            self.i = i + 1
            return 0.0
        bits = first | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)
        self.i = i + 4
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def string(self) -> str:
        b = self.b
        start = self.i
        i = self.obj.find(b"\x00", start)
        if i < 0:
            i = len(b)
        self.i = i + 1
        return bytes(b[start:i]).decode("utf-8", "replace")

    def raw(self, n: int) -> bytes:
        v = bytes(self.b[self.i:self.i + n])
        self.i += n
        return v


def parse_schema(data: bytes) -> dict[str, Definition]:
    r = Reader(data)
    n = r.uint()
    defs: list[Definition] = []
    raw_types: list[list[tuple[str, int, bool, int]]] = []
    for _ in range(n):
        name = r.string()
        kind = r.byte()
        fc = r.uint()
        fl = []
        for _ in range(fc):
            fname = r.string()
            t = r.int()
            arr = bool(r.byte())
            val = r.uint()
            fl.append((fname, t, arr, val))
        defs.append(Definition(name=name, kind=kind))
        raw_types.append(fl)
    for d, fl in zip(defs, raw_types):
        for fname, t, arr, val in fl:
            tname = BUILTIN[-1 - t] if t < 0 else defs[t].name
            f = Field(fname, tname, arr, val)
            d.fields.append(f)
            d.by_value[val] = f
    return {d.name: d for d in defs}


class Decoder:
    """Раскодирует сообщение по схеме. skip — имена полей, которые пропускаются (байтовые блобы)."""

    def __init__(self, schema: dict[str, Definition], skip: tuple[str, ...] = ()):
        self.s = schema
        self.skip = set(skip)

    def _value(self, r: Reader, t: str) -> Any:
        if t == "uint":
            return r.uint()
        if t == "float":
            return r.float()
        if t == "string":
            return r.string()
        if t == "bool":
            return r.byte() != 0
        if t == "int":
            return r.int()
        if t == "byte":
            return r.byte()
        if t == "int64":
            return r.int64()
        if t == "uint64":
            return r.uint64()
        d = self.s[t]
        if d.kind == ENUM:
            v = r.uint()
            f = d.by_value.get(v)
            return f.name if f else v
        if d.kind == STRUCT:
            return {f.name: self._field(r, f) for f in d.fields}
        out: dict[str, Any] = {}
        while True:
            fid = r.uint()
            if fid == 0:
                return out
            f = d.by_value.get(fid)
            if f is None:
                raise ValueError(f"неизвестное поле {fid} в {d.name} @ {r.i}")
            v = self._field(r, f)
            if f.name not in self.skip:
                out[f.name] = v

    def _field(self, r: Reader, f: Field) -> Any:
        if f.array:
            n = r.uint()
            if f.type == "byte":
                return r.raw(n)
            return [self._value(r, f.type) for _ in range(n)]
        return self._value(r, f.type)

    def decode(self, data: bytes, root: str = "Message") -> dict:
        return self._value(Reader(data), root)
