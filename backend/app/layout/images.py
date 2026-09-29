"""Генерация иллюстраций (GigaChat → Kandinsky) с кэшем по хэшу промпта."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from ..config import get_settings

log = logging.getLogger("images")

OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API = "https://gigachat.devices.sberbank.ru/api/v1"


class ImageGenError(RuntimeError):
    pass


class GigaChatImages:
    def __init__(self):
        s = get_settings()
        self.key = s.gigachat_key
        self.scope = s.gigachat_scope
        self.model = s.images.get("model", "GigaChat")
        self.timeout = float(s.images.get("timeout_s", 90))
        self._token: Optional[str] = None
        self._exp = 0.0
        self.cache = s.cache_dir / "images"
        self.cache.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return bool(self.key) and get_settings().images.get("provider", "gigachat") == "gigachat"

    async def _auth(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        r = await client.post(OAUTH, headers={"Authorization": f"Basic {self.key}", "RqUID": str(uuid.uuid4()),
                                              "Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"}, data={"scope": self.scope})
        if r.status_code != 200:
            raise ImageGenError(f"GigaChat OAuth {r.status_code}: {r.text[:120]}")
        j = r.json()
        self._token = j["access_token"]
        self._exp = j.get("expires_at", time.time() * 1000 + 25 * 60 * 1000) / 1000
        return self._token

    @staticmethod
    def _clean(t: str) -> str:
        """Kandinsky буквально рисует «3D», цифры и кавычки из промпта — заменяем их описаниями."""
        # предложения про цифры, надписи и текст модель рисует буквально (и с ошибками) — убираем их целиком;
        # запрет на текст и так стоит в самом запросе
        parts = re.split(r"(?<=[.!?;])\s+", t)
        t = " ".join(p for p in parts if not re.search(r"(?i)(цифр|числ|букв|надпис|текст|слов|подпис|лозунг|заголов|"
                                                          r"number|digit|text|letter|word)", p))
        t = re.sub(r"#[0-9A-Fa-f]{3,8}\b", "", t)   # HEX-коды: «#E8A33D» иначе превращался в «#E8Aобъёмные»
        t = re.sub(r"3[DdДд]-?", "объёмные ", t)
        t = re.sub(r"\([^)]*\)", "", t)   # скобки обычно перечисляют бренды и логотипы
        t = re.sub(r"[«»\"]", "", t)
        t = re.sub(r"\d+([.,]\d+)?\s*%?", "", t)
        # схемы, диаграммы, карты и инфографика у Kandinsky всегда обрастают выдуманными подписями
        t = re.sub(r"(?i)\b(диаграмм\w*|схем\w*|инфограф\w*|график\w*|карт[аеуыой]\w*|иконк\w*|пиктограм\w*|"
                   r"интерфейс\w*|экран\w*|надпис\w*|flat design|infographic\w*|diagram\w*|icons?)\b", "", t)
        # плоский вектор у Kandinsky превращается в инфографику с псевдобуквами — просим объём вместо него
        t = re.sub(r"(?i)(минималистичн\w*\s+)?векторн\w*|в плоском стиле|плоск\w*", "", t)
        t = re.sub(r"\s*,\s*(,\s*)+", ", ", t)
        return re.sub(r"\s+", " ", t).strip(" ,;")

    async def generate(self, prompt: str, style: str = "") -> Path:
        prompt, style = self._clean(prompt), self._clean(style)
        h = hashlib.sha256((prompt + "|" + style).encode()).hexdigest()[:16]
        target = self.cache / f"{h}.jpg"
        if target.exists():
            return target
        if not self.enabled:
            raise ImageGenError("генерация изображений выключена или нет ключа")
        # сертификаты Минцифры могут отсутствовать в системе — verify отключён только для этого хоста
        async with httpx.AsyncClient(verify=False, timeout=self.timeout) as client:
            tok = await self._auth(client)
            body = {"model": self.model, "function_call": "auto", "messages": [
                {"role": "system", "content": "Ты — иллюстратор корпоративных презентаций. Рисуешь без текста, букв и логотипов."},
                {"role": "user", "content": f"Нарисуй: {prompt}. Стиль: {style}; реалистичная объёмная предметная сцена, мягкий студийный свет, "
                                            "чистый светлый фон. Никаких букв, цифр, надписей, схем и логотипов в кадре, "
                                            "горизонтальная композиция."}]}
            for attempt in range(4):
                r = await client.post(f"{API}/chat/completions", json=body, headers={"Authorization": f"Bearer {tok}"})
                if r.status_code != 429:
                    break
                await asyncio.sleep(2.5 * (attempt + 1))   # личный тариф: один запрос одновременно
            if r.status_code != 200:
                raise ImageGenError(f"GigaChat {r.status_code}: {r.text[:120]}")
            content = r.json()["choices"][0]["message"]["content"]
            m = re.search(r'<img\s+src="([^"]+)"', content)
            if not m:
                raise ImageGenError("модель не вернула изображение")
            img = await client.get(f"{API}/files/{m.group(1)}/content", headers={"Authorization": f"Bearer {tok}",
                                                                              "Accept": "application/jpg"})
            if img.status_code != 200 or len(img.content) < 1000:
                raise ImageGenError("не удалось скачать изображение")
            target.write_bytes(img.content)
            return target


_gen: Optional[GigaChatImages] = None


def image_generator() -> GigaChatImages:
    global _gen
    if _gen is None:
        _gen = GigaChatImages()
    return _gen


async def generate_many(prompts: list[tuple[str, str]], style: str, limit: int) -> dict[str, Path]:
    """prompts: [(slide_id, prompt)] → {slide_id: path}. Ошибки не роняют пайплайн."""
    gen = image_generator()
    out: dict[str, Path] = {}
    if not gen.enabled:
        return out

    async def one(sid, pr):
        try:
            out[sid] = await gen.generate(pr, style)
        except Exception as e:
            log.warning("image %s failed: %s", sid, e)

    for s, p in prompts[:limit]:   # последовательно: у GigaChat лимит на параллельные запросы
        await one(s, p)
    return out
