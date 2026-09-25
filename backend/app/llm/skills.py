"""Реестр версионированных скиллов (промптов агентов).

Файлы: backend/skills/<name>/<version>.yaml
    name, version, description, kind (text|vision), temperature, max_tokens, system, user
Активная версия задаётся в config.yaml → skills.<name>. Подстановка переменных — {{var}}.
Каждый вызов фиксирует name@version в манифесте прогона (воспроизводимость).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from ..config import BACKEND, get_settings
from .client import get_llm

SKILLS_DIR = BACKEND / "skills"


@dataclass
class Skill:
    name: str
    version: str
    description: str
    kind: str
    temperature: float
    max_tokens: int
    system: str
    user: str
    sha: str

    def render(self, **vars: Any) -> tuple[str, str]:
        def sub(tpl: str) -> str:
            def rep(m):
                v = vars.get(m.group(1), "")
                if isinstance(v, (dict, list)):
                    return json.dumps(v, ensure_ascii=False, indent=1)
                return str(v)
            return re.sub(r"\{\{\s*(\w+)\s*\}\}", rep, tpl)
        return sub(self.system), sub(self.user)


def available() -> dict[str, list[str]]:
    res: dict[str, list[str]] = {}
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir():
            res[d.name] = sorted(p.stem for p in d.glob("*.yaml"))
    return res


@lru_cache(maxsize=64)
def load(name: str, version: Optional[str] = None) -> Skill:
    version = version or get_settings().skills.get(name) or sorted(p.stem for p in (SKILLS_DIR / name).glob("*.yaml"))[-1]
    path = SKILLS_DIR / name / f"{version}.yaml"
    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    return Skill(name=name, version=str(raw.get("version", version)), description=raw.get("description", ""),
                 kind=raw.get("kind", "text"), temperature=float(raw.get("temperature", 0.3)),
                 max_tokens=int(raw.get("max_tokens", 3000)), system=raw["system"], user=raw["user"],
                 sha=hashlib.sha256(raw_text.encode()).hexdigest()[:10])


class SkillRun:
    """Журнал использованных скиллов в рамках одного прогона."""

    def __init__(self, trace_path: Optional[Path] = None):
        self.used: dict[str, str] = {}
        self.trace_path = trace_path

    async def call(self, name: str, images: Optional[list] = None, **vars: Any) -> Any:
        sk = load(name)
        self.used[name] = f"{sk.version}#{sk.sha}"
        system, user = sk.render(**vars)
        trace = {"path": str(self.trace_path), "skill": f"{name}@{sk.version}"} if self.trace_path else None
        return await get_llm().json(system, user, kind=sk.kind, temperature=sk.temperature,
                                    max_tokens=sk.max_tokens, images=images, trace=trace)
