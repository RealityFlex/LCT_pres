"""OpenAI-совместимый клиент (Yandex Cloud AI Studio / VK inference / vLLM).

* thinking отключается через chat_template_kwargs (Qwen3.x), иначе ответы в разы дольше;
* JSON извлекается из ответа устойчиво (```json-блоки, хвосты), при ошибке — один запрос на починку;
* при ошибке основной модели — запасная (fallback_model);
* общий семафор ограничивает параллелизм.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import openai

from ..config import get_settings

log = logging.getLogger("llm")


class LLMError(RuntimeError):
    pass


def _trace(trace: Optional[dict], model: str, messages: list[dict], response: str, seconds: float,
           usage, attempt: int, error: Optional[str]) -> None:
    """Журнал обмена с моделью (JSONL): промпты, ответ, время, токены. Картинки заменяются заглушкой."""
    if not trace or not trace.get("path"):
        return
    def clean(m):
        c = m.get("content")
        if isinstance(c, list):
            c = [x if x.get("type") == "text" else {"type": "image", "bytes": len(x.get("image_url", {}).get("url", ""))}
                 for x in c]
        return {"role": m.get("role"), "content": c}
    rec = {"ts": round(time.time(), 2), "skill": trace.get("skill"), "repair": trace.get("repair", False),
           "model": model, "attempt": attempt, "seconds": round(seconds, 2),
           "tokens_in": getattr(usage, "prompt_tokens", None), "tokens_out": getattr(usage, "completion_tokens", None),
           "messages": [clean(m) for m in messages], "response": response, "error": error}
    try:
        with open(trace["path"], "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def extract_json(text: str) -> Any:
    if text is None:
        raise ValueError("пустой ответ")
    t = text.strip()
    t = re.sub(r"^<think>.*?</think>", "", t, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("JSON не найден")
    t = t[start:]
    # отрезаем всё после последней закрывающей скобки верхнего уровня
    depth, end, in_str, esc = 0, None, False, False
    opener = t[0]
    closer = "}" if opener == "{" else "]"
    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("JSON обрезан")
    frag = t[:end]
    try:
        return json.loads(frag)
    except json.JSONDecodeError:
        # частые огрехи: висячие запятые
        frag2 = re.sub(r",\s*([}\]])", r"\1", frag)
        return json.loads(frag2)


class LLM:
    def __init__(self):
        s = get_settings()
        self.s = s
        if not s.llm_api_key:
            raise LLMError("LLM_API_KEY не задан (.env)")
        self.client = openai.AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url,
                                         project=s.llm_folder or None, timeout=float(s.llm.get("timeout_s", 90)),
                                         max_retries=1)
        self.sem = asyncio.Semaphore(int(s.llm.get("max_concurrency", 8)))
        self.stats = {"calls": 0, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "errors": 0}

    async def chat(self, messages: list[dict], kind: str = "text", temperature: Optional[float] = None,
                   max_tokens: int = 2000, json_mode: bool = False, trace: Optional[dict] = None) -> str:
        models = [self.s.model(kind)]
        fb = self.s.llm.get("fallback_model")
        if fb and kind == "text":
            models.append(fb.format(folder=self.s.llm_folder))
        last_err: Optional[Exception] = None
        for model in models:
            extra: dict[str, Any] = {}
            if self.s.llm.get("disable_thinking", True) and "qwen" in model.lower():
                extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            for attempt in range(2):
                t0 = time.time()
                try:
                    async with self.sem:
                        r = await self.client.chat.completions.create(
                            model=model, messages=messages, max_tokens=max_tokens,
                            temperature=self.s.llm.get("temperature", 0.3) if temperature is None else temperature,
                            **extra)
                    self.stats["calls"] += 1
                    self.stats["seconds"] += time.time() - t0
                    if r.usage:
                        self.stats["tokens_in"] += r.usage.prompt_tokens or 0
                        self.stats["tokens_out"] += r.usage.completion_tokens or 0
                    txt = r.choices[0].message.content or ""
                    _trace(trace, model, messages, txt, time.time() - t0, r.usage, attempt, None)
                    if not txt.strip():
                        raise LLMError("пустой ответ модели")
                    return txt
                except Exception as e:  # сеть/лимиты/пустой ответ
                    last_err = e
                    if not isinstance(e, LLMError):
                        _trace(trace, model, messages, "", time.time() - t0, None, attempt, repr(e))
                    self.stats["errors"] += 1
                    log.warning("LLM %s attempt %s failed: %s", model, attempt, e)
                    await asyncio.sleep(0.8 * (attempt + 1))
        raise LLMError(f"модель недоступна: {last_err}")

    async def json(self, system: str, user: str, kind: str = "text", temperature: Optional[float] = None,
                   max_tokens: int = 4000, images: Optional[list[Path | bytes]] = None,
                   trace: Optional[dict] = None) -> Any:
        content: Any = user
        if images:
            content = [{"type": "text", "text": user}]
            for im in images:
                data = im if isinstance(im, bytes) else Path(im).read_bytes()
                mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        txt = await self.chat(messages, kind=kind, temperature=temperature, max_tokens=max_tokens, trace=trace)
        try:
            return extract_json(txt)
        except Exception as e:
            repair = [{"role": "system", "content": "Исправь JSON. Верни только валидный JSON без пояснений."},
                      {"role": "user", "content": f"Ошибка: {e}\n\n{txt[-12000:]}"}]
            rt = dict(trace or {}, repair=True)
            txt2 = await self.chat(repair, kind="text", temperature=0, max_tokens=max_tokens, trace=rt)
            return extract_json(txt2)


_clients: dict[int, LLM] = {}


def get_llm() -> LLM:
    """Клиент на каждый event loop (API-цикл и рабочие потоки не делят httpx-соединения)."""
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    if key not in _clients:
        _clients[key] = LLM()
    return _clients[key]


def reset_llm() -> None:
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    _clients.pop(key, None)


def total_stats() -> dict:
    out = {"calls": 0, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "errors": 0}
    for c in _clients.values():
        for k in out:
            out[k] += c.stats.get(k, 0)
    return out
