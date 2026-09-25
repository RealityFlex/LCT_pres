from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Issue(BaseModel):
    id: str
    check: str                       # код проверки (см. docs/AUDIT.md)
    title: str                       # человекочитаемое название проверки
    category: str                    # layout | template | density | integrity | content
    severity: str = "warning"        # error | warning | info
    deterministic: bool = True
    slide: int                       # 1-based номер слайда (0 — вся колода)
    message: str
    bbox: Optional[list[int]] = None  # [x, y, w, h] в EMU для подсветки
    element: Optional[str] = None    # id элемента IR или sid фигуры
    fix: Optional[dict[str, Any]] = None
    fixable: bool = False


class AuditReport(BaseModel):
    variant: str
    issues: list[Issue] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    seconds: float = 0.0

    def summary(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for i in self.issues:
            out[i.severity] = out.get(i.severity, 0) + 1
        return out
