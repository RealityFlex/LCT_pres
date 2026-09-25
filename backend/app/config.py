"""Загрузка конфигурации: config.yaml + переменные окружения (.env)."""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Settings:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.llm = raw.get("llm", {})
        self.images = raw.get("images", {})
        self.render = raw.get("render", {})
        self.pipeline = raw.get("pipeline", {})
        self.variants = raw.get("variants", [])
        self.audit = raw.get("audit", {})
        self.skills = raw.get("skills", {})

        self.data_dir = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.data_dir / "templates"
        self.jobs_dir = self.data_dir / "jobs"
        self.cache_dir = self.data_dir / "cache"
        for d in (self.templates_dir, self.jobs_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.llm_api_key = os.environ.get("LLM_API_KEY", "")
        self.llm_folder = os.environ.get("LLM_FOLDER_ID", "")
        self.llm_base_url = os.environ.get("LLM_BASE_URL", self.llm.get("base_url"))
        self.gigachat_key = os.environ.get("GIGACHAT_AUTH_KEY", "")
        self.gigachat_scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

    def model(self, kind: str) -> str:
        name = self.llm.get(f"{kind}_model") or self.llm.get("text_model")
        return name.format(folder=self.llm_folder)

    @property
    def soffice(self) -> str:
        p = os.environ.get("SOFFICE_PATH") or self.render.get("soffice_path")
        if p:
            return p
        for cand in ("soffice", "libreoffice"):
            found = shutil.which(cand)
            if found:
                return found
        for cand in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "/usr/bin/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ):
            if Path(cand).exists():
                return cand
        raise RuntimeError("LibreOffice (soffice) не найден. Укажите SOFFICE_PATH.")


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    cfg_path = Path(os.environ.get("APP_CONFIG", ROOT / "config.yaml"))
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return Settings(raw)
