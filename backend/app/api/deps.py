from __future__ import annotations

from typing import Iterator

from fastapi import Header, HTTPException

from ..db import SessionLocal


def get_db() -> Iterator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(x_user: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict:
    """Lightweight identity: the UI sends who is acting. Every write is audited with it."""
    name = (x_user or "anonymous").strip()[:64] or "anonymous"
    role = (x_role or "buyer").strip().lower()[:32]
    return {"name": name, "role": role}


def require(cond: bool, msg: str, code: int = 400) -> None:
    if not cond:
        raise HTTPException(status_code=code, detail=msg)
