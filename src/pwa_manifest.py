"""Web manifest and service-worker policy for the phone remote (#341). Pure.

Only public immutable shell assets are cacheable; anything under /api/, pairing,
media, queue, history or per-user data never is. Install guidance is offered
only in a secure context. ``manifest`` carries just the non-secret start URL.
"""
from __future__ import annotations

import json

SHELL_ASSETS = ("/static/app.css", "/static/app.js", "/static/icon-192.png", "/static/icon-512.png", "/offline.html")
NEVER_CACHE_PREFIXES = ("/api/", "/pair", "/login", "/media", "/stream", "/queue", "/history", "/events", "/status")
CACHE_VERSION = 1


def manifest(name: str = "SmoothCast Remote", start_url: str = "/") -> str:
    if not start_url.startswith("/") or start_url.startswith("//") or "?" in start_url or "#" in start_url:
        start_url = "/"                      # relative, no tokens or room secrets in the URL
    return json.dumps({
        "name": name[:45], "short_name": "SmoothCast", "start_url": start_url, "scope": "/",
        "display": "standalone", "background_color": "#101418", "theme_color": "#101418",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}]}, sort_keys=True)


def cacheable(path: str, method: str = "GET") -> bool:
    """May the service worker store/serve this request? Exact shell allow-list only."""
    if method.upper() != "GET" or not isinstance(path, str) or "?" in path or "#" in path:
        return False
    if any(path.startswith(p) for p in NEVER_CACHE_PREFIXES):
        return False
    return path in SHELL_ASSETS


def install_offer(secure_context: bool, supports_sw: bool, https_lan: bool) -> dict:
    if secure_context and supports_sw and https_lan:
        return {"offer": True, "message": "Add SmoothCast to your home screen for one-tap control."}
    if not https_lan:
        return {"offer": False, "message": "Home-screen install needs trusted HTTPS on your network. The remote still works in the browser."}
    return {"offer": False, "message": "This browser can't install the remote. It still works here."}


def service_worker() -> str:
    allow = json.dumps(list(SHELL_ASSETS))
    return f"""const V='smoothcast-shell-{CACHE_VERSION}',OK=new Set({allow});
self.addEventListener('install',e=>e.waitUntil(caches.open(V).then(c=>c.addAll([...OK]))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(n=>n!==V).map(n=>caches.delete(n))))));
self.addEventListener('fetch',e=>{{const u=new URL(e.request.url);
if(e.request.method!=='GET'||u.origin!==location.origin||u.search||!OK.has(u.pathname))return;
e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)))}});
"""
