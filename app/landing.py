"""Host-based routing for the cheetahmoongames.com home page.

The Bartenders service answers on two hostnames:

* ``bartenders.cheetahmoongames.com`` — the game, unchanged, served at ``/``.
* ``cheetahmoongames.com`` (``LANDING_HOST``) — only the games home page.
  Every other path there redirects to the same path on ``BARTENDERS_URL`` so
  old bookmarks, share links and push-notification links keep working.

Both settings come from the environment. When ``LANDING_HOST`` is unset (local
runs, tests, k3s) the middleware does nothing.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response

LANDING_PAGE = os.path.join("static", "landing.html")

NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

# Browsers that installed the Bartenders service worker on the old hostname
# keep it until it is replaced. Serving this script at /sw.js on the landing
# host makes it unregister itself on the next visit, so it stops polling the
# old origin; players get a fresh worker on the Bartenders subdomain.
RETIRE_SERVICE_WORKER = """\
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.registration.unregister()));
"""


def _landing_host() -> str:
    return os.getenv("LANDING_HOST", "").strip().lower()


def _bartenders_url() -> str:
    return os.getenv("BARTENDERS_URL", "").strip().rstrip("/")


class LandingHostMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        landing_host = _landing_host()
        if not landing_host:
            return await call_next(request)

        host = request.headers.get("host", "").split(":")[0].lower()
        if host != landing_host:
            return await call_next(request)

        path = request.url.path
        if path == "/":
            return FileResponse(LANDING_PAGE, headers=NO_CACHE)
        if path == "/sw.js":
            return Response(
                RETIRE_SERVICE_WORKER,
                media_type="application/javascript",
                headers=NO_CACHE,
            )
        # The landing page uses shared images; the health check stays local.
        if path.startswith("/static/") or path == "/health":
            return await call_next(request)

        target = _bartenders_url()
        if not target:
            return Response(status_code=404)
        query = request.url.query
        location = f"{target}{path}" + (f"?{query}" if query else "")
        # 307 keeps the method and body, and is not cached forever by browsers.
        return RedirectResponse(location, status_code=307)
