"""Бесплатный источник фактов и фото: API Википедии и Wikimedia Commons (без ключей).

Правила Wikimedia: осмысленный User-Agent с адресом проекта, последовательные запросы, умеренный объём —
на одну колоду уходит 5–15 запросов.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Optional

import httpx

from ..config import get_settings

log = logging.getLogger("wiki")
DEFAULT_UA = "LekaloBot/1.0 (https://lct.levandrovskiy.ru; presentation generator) httpx"
COMMONS = "https://commons.wikimedia.org/w/api.php"


def _plain(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


class Wiki:
    def __init__(self):
        cfg = get_settings().raw.get("search", {}) or {}
        self.lang = cfg.get("wiki_lang", "ru")
        self.ua = cfg.get("user_agent") or DEFAULT_UA
        self.timeout = float(cfg.get("timeout_s", 30))
        self.sem = asyncio.Semaphore(2)

    async def _get(self, url: str, **params) -> dict:
        params = dict(params, format="json", formatversion=2)
        async with self.sem:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()

    @property
    def api(self) -> str:
        return f"https://{self.lang}.wikipedia.org/w/api.php"

    async def search(self, query: str, n: int = 5) -> list[dict]:
        """[{"title", "snippet"}] — полнотекстовый поиск; отбор по смыслу делает вызывающий код."""
        j = await self._get(self.api, action="query", list="search", srsearch=query, srlimit=n, srprop="snippet")
        return [{"title": x["title"], "snippet": _plain(x.get("snippet", ""))} for x in j.get("query", {}).get("search", [])]

    async def titles(self, query: str, n: int = 3) -> list[str]:
        """Статьи, чьё название начинается с запроса (opensearch): точные понятия вроде «Электронное обучение»."""
        async with self.sem:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(self.api, params={"action": "opensearch", "search": query, "limit": n,
                                                  "namespace": 0, "format": "json"})
        r.raise_for_status()
        j = r.json()
        return list(j[1]) if isinstance(j, list) and len(j) > 1 else []

    async def article(self, title: str) -> Optional[dict]:
        """{"title", "url", "text", "image"} — полный текст без разметки и главная картинка статьи."""
        j = await self._get(self.api, action="query", prop="extracts|info|pageimages", inprop="url", explaintext=1,
                            exsectionformat="plain", piprop="name", titles=title, redirects=1)
        pages = j.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        pg = pages[0]
        text = pg.get("extract") or ""
        # хвостовые служебные разделы не несут фактов
        text = re.split(r"\n(?:Примечания|Литература|Ссылки|См\. также|Notes|References|See also)\n", text)[0]
        return {"title": pg.get("title", title), "url": pg.get("fullurl", ""), "text": text.strip(),
                "image": pg.get("pageimage")}

    async def commons(self, query: str, n: int = 12, files: Optional[list[str]] = None) -> list[dict]:
        """Кандидаты-фото: поиск по Commons или конкретные файлы (главные картинки статей)."""
        common = dict(action="query", prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=1600)
        if files:
            j = await self._get(COMMONS, titles="|".join(f"File:{f}" for f in files[:20]), **common)
        else:
            j = await self._get(COMMONS, generator="search", gsrsearch=f"{query} filetype:bitmap", gsrnamespace=6,
                                gsrlimit=n, **common)
        out = []
        for p in j.get("query", {}).get("pages", []) or []:
            ii = (p.get("imageinfo") or [{}])[0]
            if not ii:
                continue
            md = ii.get("extmetadata", {}) or {}
            val = lambda k: _plain((md.get(k) or {}).get("value", ""))   # noqa: E731
            out.append({"title": p.get("title", ""), "url": ii.get("thumburl") or ii.get("url", ""),
                        "width": int(ii.get("width") or 0), "height": int(ii.get("height") or 0),
                        "mime": ii.get("mime", ""), "page": ii.get("descriptionurl", ""),
                        "license": val("LicenseShortName"), "artist": val("Artist")[:80],
                        "description": val("ImageDescription")[:200], "date": val("DateTimeOriginal")[:20]})
        return out

    async def download(self, url: str, limit: int = 15_000_000) -> bytes:
        async with self.sem:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}, follow_redirects=True) as c:
                r = await c.get(url)
        r.raise_for_status()
        if len(r.content) > limit:
            raise ValueError("слишком большой файл")
        return r.content


_wiki: dict[int, Wiki] = {}


def wiki() -> Wiki:
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    if key not in _wiki:
        _wiki[key] = Wiki()
    return _wiki[key]
