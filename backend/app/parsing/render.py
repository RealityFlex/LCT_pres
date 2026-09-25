"""Рендер PPTX → PDF → PNG (LibreOffice headless + PyMuPDF).

Каждый вызов использует собственный профиль LibreOffice, поэтому конвертации
можно запускать параллельно (ограничено семафором из config.render.max_parallel).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import pymupdf

from ..config import get_settings
from .fonts import font_dirs_for_render

_sem: threading.Semaphore | None = None
_sem_lock = threading.Lock()


def _semaphore() -> threading.Semaphore:
    global _sem
    with _sem_lock:
        if _sem is None:
            _sem = threading.Semaphore(int(get_settings().render.get("max_parallel", 3)))
        return _sem


_registered: set[str] = set()


def register_fonts() -> None:
    """Делает шрифты шаблонов видимыми для LibreOffice.

    Windows: AddFontResourceW регистрирует шрифт на сессию без прав администратора
    (папку user/fonts профиля LibreOffice не читает). Linux/macOS: ~/.fonts + fc-cache.
    """
    files = [f for d in font_dirs_for_render() for f in list(d.glob("*.ttf")) + list(d.glob("*.otf"))]
    new = [f for f in files if str(f) not in _registered]
    if not new:
        return
    if sys.platform.startswith("win"):
        import ctypes
        for f in new:
            try:
                ctypes.windll.gdi32.AddFontResourceW(str(f.resolve()))
            except Exception:
                pass
            _registered.add(str(f))
        try:
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 1000, None)
        except Exception:
            pass
    else:
        target = Path.home() / ".fonts"
        target.mkdir(parents=True, exist_ok=True)
        for f in new:
            try:
                shutil.copy2(f, target / f.name)
            except OSError:
                pass
            _registered.add(str(f))
        subprocess.run(["fc-cache", "-f", str(target)], capture_output=True, check=False)


def _profile_dir() -> Path:
    base = get_settings().cache_dir / "lo_profiles"
    base.mkdir(parents=True, exist_ok=True)
    d = base / uuid.uuid4().hex[:10]
    d.mkdir()
    return d


def pptx_to_pdf(pptx: Path, out_dir: Path | None = None, timeout: int = 240) -> Path:
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir or pptx.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    register_fonts()
    with _semaphore():
        prof = _profile_dir()
        try:
            with tempfile.TemporaryDirectory(dir=s.cache_dir) as tmp:
                cmd = [
                    s.soffice,
                    f"-env:UserInstallation={prof.as_uri()}",
                    "--headless", "--norestore", "--nolockcheck", "--nodefault",
                    "--convert-to", "pdf", "--outdir", tmp, str(pptx),
                ]
                env = dict(os.environ)
                env.pop("PYTHONPATH", None)
                subprocess.run(cmd, check=False, timeout=timeout, capture_output=True, env=env)
                produced = Path(tmp) / (pptx.stem + ".pdf")
                if not produced.exists():
                    raise RuntimeError(f"LibreOffice не создал PDF для {pptx.name}")
                target = out_dir / (pptx.stem + ".pdf")
                shutil.move(str(produced), target)
                return target
        finally:
            shutil.rmtree(prof, ignore_errors=True)


def pdf_to_pngs(pdf: Path, out_dir: Path, prefix: str = "slide", dpi: int | None = None,
                pages: list[int] | None = None) -> list[Path]:
    dpi = dpi or int(get_settings().render.get("preview_dpi", 110))
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    res = []
    zoom = dpi / 72
    for i, page in enumerate(doc):
        if pages is not None and i not in pages:
            continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        p = out_dir / f"{prefix}-{i + 1:03d}.png"
        pix.save(p)
        res.append(p)
    doc.close()
    return res


def render_deck(pptx: Path, out_dir: Path, prefix: str = "slide", dpi: int | None = None) -> tuple[Path, list[Path]]:
    pdf = pptx_to_pdf(pptx, out_dir)
    for old in out_dir.glob(f"{prefix}-*.png"):
        old.unlink()
    return pdf, pdf_to_pngs(pdf, out_dir, prefix, dpi)


async def render_deck_async(pptx: Path, out_dir: Path, prefix: str = "slide", dpi: int | None = None):
    return await asyncio.to_thread(render_deck, pptx, out_dir, prefix, dpi)
