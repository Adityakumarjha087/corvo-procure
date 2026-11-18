"""FastAPI entry point. Serves the API and, in production, the built React app."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import services as svc
from .api import routes_chat, routes_data, routes_policy, routes_runs
from .db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


app = FastAPI(title="Cantill PR-to-PO", version="1.0.0", lifespan=lifespan,
              description="Policy-driven purchase requisition to PO engine for Corvo Engineering.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
for r in (routes_data.router, routes_policy.router, routes_runs.router, routes_chat.router):
    app.include_router(r)


def startup() -> None:
    init_db()
    with SessionLocal() as db:
        svc.ensure_default_policy(db)
        kit = os.getenv("KIT_DIR")
        if kit and os.path.isdir(kit) and not svc.data_ready(db):
            log.info("Loading kit data from %s", kit)
            log.info("%s", svc.ingest_dir(db, kit))


STATIC_DIR = os.getenv("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = os.path.join(STATIC_DIR, path)
        if path and os.path.isfile(f) and not path.startswith("api"):
            return FileResponse(f)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
