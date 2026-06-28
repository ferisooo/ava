"""Serves the Ava control dashboard from inside the bot via aiohttp.

aiohttp ships with discord.py, so there's no extra dependency. The server is
opt-in: it only starts when DASHBOARD_PORT is set. Bind on 0.0.0.0 so it's
reachable on the host's public IP (open the port in your panel).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

log = logging.getLogger("ava.dashboard")

_HTML_PATH = Path(__file__).parent / "web" / "dashboard.html"


async def _index(_request: web.Request) -> web.StreamResponse:
    # Read per-request so the page can be edited without restarting.
    return web.Response(
        text=_HTML_PATH.read_text(encoding="utf-8"), content_type="text/html"
    )


async def _health(_request: web.Request) -> web.StreamResponse:
    return web.Response(text="ok")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    return app


async def start(port: int) -> web.AppRunner:
    """Start the dashboard server and return its runner (for cleanup)."""
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Dashboard listening on 0.0.0.0:%s", port)
    return runner
