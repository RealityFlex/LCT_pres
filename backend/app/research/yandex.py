"""Клиент Яндекс Поиск API v2 (тот же ключ и каталог Yandex Cloud, что и у LLM).

- answer(): генеративный ответ с пронумерованными источниками — основа «исследования» темы;
- web(): обычная выдача (заголовок, адрес, фрагмент);
- images(): поиск картинок (оригинал, размеры, страница-источник).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx

from ..config import get_settings

log = logging.getLogger("search")
BASE = "https://searchapi.api.cloud.yandex.net/v2"


class SearchError(RuntimeError):
    pass


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _text(el: Optional[ET.Element]) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


class YandexSearch:
    def __init__(self):
        s = get_settings()
        self.cfg = s.raw.get("search", {}) or {}
        self.key, self.folder = s.llm_api_key, s.llm_folder
        self.timeout = float(self.cfg.get("timeout_s", 40))
        self.sem = asyncio.Semaphore(int(self.cfg.get("max_concurrency", 3)))

    @property
    def enabled(self) -> bool:
        return self.cfg.get("provider", "yandex") == "yandex" and bool(self.key and self.folder)

    async def _post(self, path: str, body: dict) -> Any:
        if not self.enabled:
            raise SearchError("поиск отключён (search.provider) или нет ключа")
        body = dict(body, folderId=self.folder)
        async with self.sem:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{BASE}/{path}", json=body, headers={"Authorization": f"Api-Key {self.key}"})
        if r.status_code != 200:
            raise SearchError(f"{path}: HTTP {r.status_code} {r.text[:160]}")
        return r.json()

    async def answer(self, query: str) -> dict:
        """{"text": ответ со ссылками [n], "sources": [{"url", "title", "used"}]}"""
        raw = await self._post("gen/search", {"messages": [{"role": "ROLE_USER", "content": query}]})
        part = raw[-1] if isinstance(raw, list) and raw else raw
        msg = (part or {}).get("message", {}) or {}
        if (part or {}).get("isAnswerRejected") or (part or {}).get("problematicAnswer"):
            return {"text": "", "sources": []}
        srcs = [{"url": s.get("url", ""), "title": (s.get("title") or "").strip(), "used": bool(s.get("used"))}
                for s in (part or {}).get("sources", []) if s.get("url")]
        return {"text": (msg.get("content") or "").strip(), "sources": srcs}

    async def web(self, query: str, n: int = 5) -> list[dict]:
        raw = await self._post("web/search", {"query": {"searchType": "SEARCH_TYPE_RU", "queryText": query},
                                              "responseFormat": "FORMAT_XML",
                                              "groupSpec": {"groupsOnPage": n, "docsInGroup": 1}})
        root = ET.fromstring(base64.b64decode(raw["rawData"]))
        out = []
        for doc in root.iter("doc"):
            url = _text(doc.find("url"))
            if url:
                out.append({"url": url, "title": _text(doc.find("title")),
                            "passage": " ".join(_text(p) for p in doc.iter("passage"))[:500]})
        return out[:n]

    async def images(self, query: str, n: int = 12, horizontal: bool = True) -> list[dict]:
        spec: dict[str, Any] = {"size": "IMAGE_SIZE_LARGE"}
        if horizontal:
            spec["orientation"] = "IMAGE_ORIENTATION_HORIZONTAL"
        raw = await self._post("image/search", {"query": {"searchType": "SEARCH_TYPE_RU", "queryText": query},
                                                "docsOnPage": n, "imageSpec": spec})
        root = ET.fromstring(base64.b64decode(raw["rawData"]))
        out = []
        for doc in root.iter("doc"):
            pr = doc.find("image-properties")
            if pr is None:
                continue
            try:
                w, h = int(_text(pr.find("original-width")) or 0), int(_text(pr.find("original-height")) or 0)
            except ValueError:
                w = h = 0
            page = _text(pr.find("html-link"))
            out.append({"url": _text(doc.find("url")), "alt": _text(pr.find("image-link")),
                        "thumb": _text(pr.find("thumbnail-link")), "width": w, "height": h,
                        "page": page, "host": host_of(page or _text(doc.find("url"))),
                        "mime": _text(pr.find("mime-type")).lower()})
        return out


_search: dict[int, YandexSearch] = {}


def searcher() -> YandexSearch:
    """Клиент на каждый event loop (семафор привязан к циклу), как и у LLM."""
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    if key not in _search:
        _search[key] = YandexSearch()
    return _search[key]
