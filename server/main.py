"""TotalFootball - everything about football in one place."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .auth import basic_auth_middleware
from .config import WEB_DIR, settings
from .providers import apifootball as af
from .routers.api import router as api_router

log = logging.getLogger("totalfootball")


async def _warm() -> None:
    """First-run warm-up: pull squads and transfers so search and the transfer
    feed are populated immediately instead of on the user's first click.

    Only runs when a store is empty, so restarts cost nothing. Roughly 190
    requests on a cold start - about 2.5% of a Pro day.
    """
    from .routers.api import provider

    if not settings.is_live or not hasattr(provider, "sweep_squads"):
        return
    try:
        if not provider._squad_store().get("clubs"):
            result = await provider.sweep_squads()
            log.info("warm-up: squads %s/%s", result["covered"], result["total_clubs"])
        if not provider._load_store().get("clubs"):
            result = await provider.sweep_transfers()
            log.info("warm-up: transfers %s/%s", result["covered"], result["total_clubs"])
    except Exception as exc:  # never block startup on a warm-up failure
        log.warning("warm-up skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_warm())
    yield
    task.cancel()
    await af.client.close()


app = FastAPI(title="TotalFootball", version="1.0.0", lifespan=lifespan)
app.middleware("http")(basic_auth_middleware)
app.include_router(api_router)


class RevalidatingStatics(StaticFiles):
    """Always revalidate. Without an explicit Cache-Control, browsers apply
    heuristic caching and happily serve a stale bundle after an edit - which
    looks exactly like the new code never shipped."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.mount("/static", RevalidatingStatics(directory=WEB_DIR), name="static")


# The shell must never be cached: it is the one file that decides which
# script URLs the browser loads, so a stale copy pins the whole app to an old
# build (it kept serving a nav that pointed at the wrong landing route).
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


def _build_id() -> str:
    """Fingerprint of the frontend, from every asset's size and mtime.

    Appended to the script and stylesheet URLs. `Cache-Control: no-cache` only
    helps if the browser asks; anything it cached *before* those headers
    existed is served from disk without a request. A changing URL is the only
    thing that reliably breaks that, and it makes every future deploy pick up
    instantly too.
    """
    import hashlib

    h = hashlib.sha256()
    for path in sorted(WEB_DIR.rglob("*")):
        if path.suffix in (".js", ".css", ".html") and path.is_file():
            st = path.stat()
            h.update(f"{path.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:10]


BUILD = _build_id()


@app.get("/{full_path:path}")
async def spa(full_path: str):
    """Serve the single-page app for every non-API route."""
    candidate = (WEB_DIR / full_path).resolve()
    if full_path and candidate.is_file() and WEB_DIR in candidate.parents:
        return FileResponse(candidate, headers=_NO_CACHE)

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__BUILD__", BUILD)
    return HTMLResponse(html, headers=_NO_CACHE)
